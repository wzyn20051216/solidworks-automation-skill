"""@brief 同一 MCP 的可选 HTTP 传输；显式 Host/Origin 与共享密钥边界。"""
import hmac


class TokenAuthMiddleware:
    """@brief 在 HTTP 层校验 Bearer，不接触工具 Schema、COM 锁或日志内容。"""
    def __init__(self, app, token):
        self.app = app
        self.expected = ("Bearer " + token).encode("utf-8") if token else None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.expected is not None:
            supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer realm=solidworks")]})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await self.app(scope, receive, send)
