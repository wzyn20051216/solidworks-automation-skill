"""@brief 使用仓库自身的 GitHub 权限生成可嵌入 README 的星标趋势图。"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path


GRAPHQL_URL = "https://api.github.com/graphql"
QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    stargazerCount
    stargazers(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: ASC}) {
      edges { starredAt }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def _graphql(token: str, variables: dict) -> dict:
    """@brief 调用 GitHub GraphQL API，并将服务端错误转成明确异常。"""
    payload = json.dumps({"query": QUERY, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "solidworks-automation-skill-star-history",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub GraphQL 请求失败: HTTP {exc.code}: {detail}") from exc
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL 返回错误: {result['errors']}")
    return result["data"]


def fetch_star_timeline(repository: str, token: str) -> tuple[list[datetime], int]:
    """@brief 分页读取仓库全部加星时间，不读取或保存用户身份。"""
    if repository.count("/") != 1:
        raise ValueError("repository 必须采用 owner/name 格式")
    owner, name = repository.split("/", 1)
    cursor = None
    timestamps: list[datetime] = []
    total_count = 0
    while True:
        data = _graphql(token, {"owner": owner, "name": name, "cursor": cursor})
        repo = data.get("repository")
        if repo is None:
            raise RuntimeError(f"GitHub 仓库不存在或当前令牌无权读取: {repository}")
        total_count = int(repo.get("stargazerCount") or 0)
        connection = repo["stargazers"]
        for edge in connection.get("edges") or []:
            timestamps.append(datetime.fromisoformat(edge["starredAt"].replace("Z", "+00:00")))
        page_info = connection["pageInfo"]
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            raise RuntimeError("GitHub 分页声明存在下一页，但未返回 endCursor")
    timestamps.sort()
    if len(timestamps) > total_count:
        raise RuntimeError(f"星标时间线数量超过仓库总数: timeline={len(timestamps)}, total={total_count}")
    return timestamps, total_count


def _nice_ceiling(value: int) -> int:
    """@brief 计算便于阅读的纵轴上界。"""
    value = max(1, int(value))
    magnitude = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 5, 10):
        candidate = factor * magnitude
        if candidate >= value:
            return candidate
    return 10 * magnitude


def render_svg(repository: str, timestamps: list[datetime], total_count: int, *, dark: bool = False) -> str:
    """@brief 将加星时间序列渲染为无外部依赖的亮色或暗色 SVG。"""
    width, height = 960, 500
    left, right, top, bottom = 82, 36, 92, 66
    plot_width = width - left - right
    plot_height = height - top - bottom
    now = datetime.now(timezone.utc)
    first = timestamps[0] if timestamps else now
    start = first - timedelta(days=1)
    end = max(now, start + timedelta(days=1))
    span_seconds = max(1.0, (end - start).total_seconds())
    y_max = _nice_ceiling(total_count)

    palette = {
        "background": "#0d1117" if dark else "#ffffff",
        "panel": "#161b22" if dark else "#f8fafc",
        "grid": "#30363d" if dark else "#dbe3ec",
        "text": "#e6edf3" if dark else "#172033",
        "muted": "#8b949e" if dark else "#64748b",
        "line": "#58a6ff" if dark else "#2563eb",
        "fill": "#1f6feb" if dark else "#60a5fa",
        "badge": "#238636" if dark else "#16a34a",
    }

    def x_position(timestamp: datetime) -> float:
        return left + ((timestamp - start).total_seconds() / span_seconds) * plot_width

    def y_position(count: int) -> float:
        return top + plot_height - (count / y_max) * plot_height

    points = [(left, y_position(0))]
    points.extend((x_position(timestamp), y_position(index)) for index, timestamp in enumerate(timestamps, start=1))
    points.append((left + plot_width, y_position(total_count)))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{left},{top + plot_height} {polyline} {left + plot_width},{top + plot_height}"

    y_grid = []
    for index in range(6):
        count = round(y_max * index / 5)
        y = y_position(count)
        y_grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="{palette["grid"]}" />'
            f'<text x="{left - 14}" y="{y + 4:.1f}" text-anchor="end" fill="{palette["muted"]}" font-size="13">{count}</text>'
        )

    x_grid = []
    date_format = "%m-%d" if (end - start).days < 180 else "%Y-%m"
    for index in range(6):
        timestamp = start + (end - start) * (index / 5)
        x = left + plot_width * index / 5
        x_grid.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_height}" stroke="{palette["grid"]}" />'
            f'<text x="{x:.1f}" y="{top + plot_height + 30}" text-anchor="middle" fill="{palette["muted"]}" font-size="13">{timestamp.strftime(date_format)}</text>'
        )

    repo_label = escape(repository)
    generated_date = now.strftime("%Y-%m-%d")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{repo_label} Star History</title>
  <desc id="desc">{total_count} stars as of {generated_date}</desc>
  <defs>
    <linearGradient id="star-area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{palette['fill']}" stop-opacity="0.42" />
      <stop offset="100%" stop-color="{palette['fill']}" stop-opacity="0.04" />
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="18" fill="{palette['background']}" />
  <rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" rx="10" fill="{palette['panel']}" />
  <text x="{left}" y="42" fill="{palette['text']}" font-family="Segoe UI,Arial,sans-serif" font-size="24" font-weight="700">Star History</text>
  <text x="{left}" y="68" fill="{palette['muted']}" font-family="Segoe UI,Arial,sans-serif" font-size="14">{repo_label} · updated {generated_date}</text>
  <rect x="{width - 174}" y="27" width="138" height="38" rx="19" fill="{palette['badge']}" />
  <text x="{width - 105}" y="52" text-anchor="middle" fill="#ffffff" font-family="Segoe UI,Arial,sans-serif" font-size="15" font-weight="700">★ {total_count} stars</text>
  <g font-family="Segoe UI,Arial,sans-serif">{''.join(y_grid)}{''.join(x_grid)}</g>
  <polygon points="{area}" fill="url(#star-area)" />
  <polyline points="{polyline}" fill="none" stroke="{palette['line']}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="5" fill="{palette['line']}" stroke="{palette['background']}" stroke-width="3" />
  <text x="{width - right}" y="{height - 18}" text-anchor="end" fill="{palette['muted']}" font-family="Segoe UI,Arial,sans-serif" font-size="12">Data: GitHub GraphQL API</text>
</svg>
'''


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="生成仓库星标趋势 SVG")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "wzyn20051216/solidworks-automation-skill"))
    parser.add_argument("--output-light", default="assets/star-history.svg")
    parser.add_argument("--output-dark", default="assets/star-history-dark.svg")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("缺少 GITHUB_TOKEN 或 GH_TOKEN，无法读取星标时间线。", file=sys.stderr)
        return 2
    try:
        timestamps, total_count = fetch_star_timeline(args.repository, token)
        if len(timestamps) < total_count:
            print(f"提示: GitHub 返回 {len(timestamps)} 个历史时间点，曲线末端按当前总数 {total_count} 锚定。")
        for output, dark in ((args.output_light, False), (args.output_dark, True)):
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_svg(args.repository, timestamps, total_count, dark=dark), encoding="utf-8")
            print(f"已生成: {path} ({total_count} stars)")
    except Exception as exc:
        print(f"生成星标趋势图失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
