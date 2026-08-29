"""星标趋势图生成器的离线测试。"""

from datetime import datetime, timezone
from xml.etree import ElementTree

import scripts.generate_star_history as star_history
from scripts.generate_star_history import _nice_ceiling, fetch_star_timeline, render_svg


def test_nice_ceiling_uses_readable_axis_limits():
    """@brief 纵轴应落在 1/2/5 倍数量级，避免难读刻度。"""
    assert _nice_ceiling(0) == 1
    assert _nice_ceiling(47) == 50
    assert _nice_ceiling(797) == 1000


def test_render_svg_is_valid_and_contains_no_stargazer_identity():
    """@brief SVG 只展示时间与累计数量，不包含用户身份。"""
    timestamps = [
        datetime(2026, 3, 22, tzinfo=timezone.utc),
        datetime(2026, 3, 24, tzinfo=timezone.utc),
    ]

    svg = render_svg("owner/repo", timestamps, 2)
    root = ElementTree.fromstring(svg)

    assert root.tag.endswith("svg")
    assert "owner/repo" in svg
    assert "★ 2 stars" in svg
    assert "api.star-history.com" not in svg


def test_fetch_timeline_allows_github_total_to_exceed_visible_history(monkeypatch):
    """@brief 少量不可见历史记录不应阻断，当前总数用于曲线末端锚定。"""
    monkeypatch.setattr(star_history, "_graphql", lambda _token, _variables: {
        "repository": {
            "stargazerCount": 2,
            "stargazers": {
                "edges": [{"starredAt": "2026-03-22T16:35:10Z"}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            },
        },
    })

    timestamps, total = fetch_star_timeline("owner/repo", "token")

    assert len(timestamps) == 1
    assert total == 2
