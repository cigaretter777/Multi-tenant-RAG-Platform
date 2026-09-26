"""认证编排：API Key 校验与主体解析。

所有失败类别统一抛出 AuthenticationError("invalid credentials")，
避免通过错误信息区分「Key 不存在 / 签名错误 / 已禁用 / 已过期」。
"""
from datetime import datetime, timezone

from platform_auth.api_keys import parse_api_key, verify_api_key
from platform_auth.models import Principal


class AuthenticationError(Exception):
    pass


class AuthenticationService:
    def __init__(self, repository, pepper: str):
        self.repository = repository
        self.pepper = pepper

    async def authenticate(self, raw_key: str) -> Principal:
        try:
            prefix = parse_api_key(raw_key).prefix
        except (TypeError, ValueError):
            raise AuthenticationError("invalid credentials")
        record = await self.repository.get_api_key_record(prefix)
        if not record or not self._record_is_active(record):
            raise AuthenticationError("invalid credentials")
        if not verify_api_key(raw_key, record["key_digest"], self.pepper):
            raise AuthenticationError("invalid credentials")
        return Principal(
            principal_id=record["principal_id"],
            tenant_id=record["tenant_id"],
            name=record["principal_name"],
        )

    @staticmethod
    def _record_is_active(record: dict) -> bool:
        if any(record[field] != "active" for field in (
            "key_status", "principal_status", "tenant_status"
        )):
            return False
        expires_at = record.get("expires_at")
        return expires_at is None or expires_at > datetime.now(timezone.utc)
