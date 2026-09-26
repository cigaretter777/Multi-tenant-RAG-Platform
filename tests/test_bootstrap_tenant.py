from pathlib import Path
import subprocess
import sys
import unittest

from scripts.bootstrap_tenant import bootstrap_tenant


class FakeBootstrapRepository:
    def __init__(self):
        self.saved_record = None

    async def create_tenant_principal_and_key(
        self,
        tenant_id,
        tenant_name,
        principal_id,
        principal_name,
        key_id,
        key_prefix,
        key_digest,
    ) -> None:
        self.saved_record = {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "principal_id": principal_id,
            "principal_name": principal_name,
            "key_id": key_id,
            "key_prefix": key_prefix,
            "key_digest": key_digest,
        }


class BootstrapTenantTest(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_persists_only_digest_and_returns_raw_key_once(self):
        repository = FakeBootstrapRepository()

        raw_key = await bootstrap_tenant("demo", "developer", repository, "pepper")

        self.assertTrue(raw_key.startswith("rag_"))
        self.assertNotIn(raw_key, repr(repository.saved_record))
        self.assertEqual(len(repository.saved_record["key_digest"]), 64)


class BootstrapTenantCliTest(unittest.TestCase):
    def test_documented_script_command_can_start_from_repository_root(self):
        repository_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "scripts/bootstrap_tenant.py", "--help"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--tenant-name", result.stdout)
