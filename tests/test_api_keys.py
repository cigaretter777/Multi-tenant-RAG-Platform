import unittest
from uuid import uuid4

from platform_auth.api_keys import generate_api_key, parse_api_key, verify_api_key
from platform_auth.models import Principal


class ApiKeyTest(unittest.TestCase):
    def test_generated_key_round_trips_and_verifies(self):
        generated = generate_api_key("test-pepper")

        parsed = parse_api_key(generated.raw_key)

        self.assertEqual(parsed.prefix, generated.prefix)
        self.assertTrue(verify_api_key(generated.raw_key, generated.digest, "test-pepper"))
        self.assertFalse(verify_api_key(generated.raw_key + "x", generated.digest, "test-pepper"))

    def test_malformed_keys_are_rejected(self):
        for value in ("", "Bearer x", "rag_short", "rag_bad_prefix_secret"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_api_key(value)

    def test_principal_is_tenant_scoped_and_immutable(self):
        principal = Principal(principal_id=uuid4(), tenant_id=uuid4(), name="local")

        with self.assertRaises(Exception):
            principal.name = "changed"
