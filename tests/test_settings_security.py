import unittest

from configs.config import Settings


class SettingsSecurityTest(unittest.TestCase):
    def test_clean_settings_use_local_infrastructure_and_no_passwords(self):
        settings = Settings(_env_file=None)

        self.assertEqual(settings.milvus_uri, "http://localhost:19530")
        self.assertEqual(settings.pg_host, "localhost")
        self.assertEqual(settings.milvus_password, "")
        self.assertEqual(settings.pg_password, "")
        self.assertEqual(settings.embedding_key, "")
        self.assertEqual(settings.api_key_pepper, "")

    def test_legacy_api_is_disabled_by_default(self):
        settings = Settings(_env_file=None)

        self.assertFalse(settings.legacy_api_enabled)
