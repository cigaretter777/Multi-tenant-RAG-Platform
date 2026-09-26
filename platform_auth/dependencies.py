"""FastAPI 鉴权依赖：Bearer Token → Principal。"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from configs.config import settings
from platform_auth.service import AuthenticationError, AuthenticationService
from repositories.control_plane import ControlPlaneRepository
from utils.db import DatabaseManager

_bearer = HTTPBearer(auto_error=False)


def get_authentication_service() -> AuthenticationService:
    return AuthenticationService(ControlPlaneRepository(DatabaseManager), settings.api_key_pepper)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    service: AuthenticationService = Depends(get_authentication_service),
) -> "Principal":  # noqa: F821 - 仅为文档化返回类型
    from platform_auth.models import Principal

    if credentials is None:
        raise _unauthorized()
    try:
        principal: Principal = await service.authenticate(credentials.credentials)
    except AuthenticationError:
        raise _unauthorized()
    return principal


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
