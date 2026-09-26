import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from platform_auth.api_keys import generate_api_key
from platform_auth.service import AuthenticationError, AuthenticationService


class FakeAuthRepository:
    def __init__(self, record):
        self.record = record

    async def get_api_key_record(self, prefix):
        if self.record and self.record["key_prefix"] == prefix:
            return self.record
        return None


class AuthenticationServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.generated = generate_api_key("pepper")
        self.record = {
            "key_prefix": self.generated.prefix,
            "key_digest": self.generated.digest,
            "key_status": "active",
            "principal_id": uuid4(),
            "principal_name": "developer",
            "principal_status": "active",
            "tenant_id": uuid4(),
            "tenant_status": "active",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        }

    async def test_valid_key_returns_principal(self):
        service = AuthenticationService(FakeAuthRepository(self.record), "pepper")
        principal = await service.authenticate(self.generated.raw_key)
        self.assertEqual(principal.tenant_id, self.record["tenant_id"])

    async def test_unknown_prefix_is_unauthorized(self):
        service = AuthenticationService(FakeAuthRepository(None), "pepper")
        with self.assertRaisesRegex(AuthenticationError, "invalid credentials"):
            await service.authenticate(self.generated.raw_key)

    async def test_bad_signature_is_unauthorized(self):
        service = AuthenticationService(FakeAuthRepository(self.record), "wrong-pepper")
        with self.assertRaisesRegex(AuthenticationError, "invalid credentials"):
            await service.authenticate(self.generated.raw_key)

    async def test_inactive_or_expired_record_is_unauthorized(self):
        cases = (
            ("key_status", "disabled"),
            ("principal_status", "disabled"),
            ("tenant_status", "disabled"),
            ("expires_at", datetime.now(timezone.utc) - timedelta(seconds=1)),
        )
        for field, value in cases:
            with self.subTest(field=field):
                record = {**self.record, field: value}
                service = AuthenticationService(FakeAuthRepository(record), "pepper")
                with self.assertRaisesRegex(AuthenticationError, "invalid credentials"):
                    await service.authenticate(self.generated.raw_key)
