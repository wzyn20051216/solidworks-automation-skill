"""@brief 两个固定来源下载器的 HTTPS/重定向/大小边界，无新增服务。"""
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def validate_https_url(url, allowed_host):
    """@brief 校验实际请求来源；拒绝凭据、异常端口、片段和控制字符。
    @param url 完整请求 URL。
    @param allowed_host 调用方代码声明的固定主机，不来自任务输入。
    @return 解析后的 SplitResult。
    """
    if not isinstance(url, str) or any(ord(char) <= 32 or char == "\\" for char in url):
        raise ValueError("请求 URL 包含不允许的字符")
    try:
        parts = urlsplit(url)
        allowed = parts.scheme == "https" and parts.hostname == allowed_host and parts.port in (None, 443)
    except ValueError as error:
        raise ValueError("请求 URL 的主机或端口无效") from error
    if not allowed or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("请求必须是无凭据、无查询/片段的固定 HTTPS 来源")
    return parts


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """@brief 固定 GraphQL/提交原始文件应直接响应，跳转时不转发凭据。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "固定来源请求禁止重定向", headers, fp)


def read_https_response(request, *, allowed_host, max_bytes, timeout=30):
    """@brief 在真正请求处校验并有界读取，调用方不能绕过清单预检。"""
    validate_https_url(request.full_url, allowed_host)
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("响应大小上限必须为正整数")
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > max_bytes:
            raise ValueError("响应超过大小上限")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("响应超过大小上限")
        return data
