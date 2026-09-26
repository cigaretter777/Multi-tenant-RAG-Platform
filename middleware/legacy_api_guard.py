"""旧版 /embedding/* 接口的默认拒绝守卫。

LEGACY_API_ENABLED=false（默认）时，未鉴权的旧接口一律返回 404，
直到它们迁移到服务端推导租户上下文的 v1 路由。
"""
from starlette.responses import JSONResponse


class LegacyApiGuardMiddleware:
    def __init__(self, app, enabled: bool):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/embedding/") and not self.enabled:
            response = JSONResponse({"detail": "not found"}, status_code=404)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
