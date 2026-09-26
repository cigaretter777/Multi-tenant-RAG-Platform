"""本地租户 bootstrap：单事务创建租户/主体/API Key，raw key 仅打印一次。"""
import argparse
import asyncio
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from configs.config import settings
from platform_auth.api_keys import generate_api_key
from repositories.control_plane import ControlPlaneRepository
from utils.db import DatabaseManager, close_database, init_database


async def bootstrap_tenant(name: str, principal_name: str, repository, pepper: str) -> str:
    generated = generate_api_key(pepper)
    await repository.create_tenant_principal_and_key(
        tenant_id=uuid4(),
        tenant_name=name,
        principal_id=uuid4(),
        principal_name=principal_name,
        key_id=uuid4(),
        key_prefix=generated.prefix,
        key_digest=generated.digest,
    )
    return generated.raw_key


async def _run(args: argparse.Namespace) -> int:
    await init_database()
    try:
        raw_key = await bootstrap_tenant(
            args.tenant_name,
            args.principal_name,
            ControlPlaneRepository(DatabaseManager),
            settings.api_key_pepper,
        )
        print(raw_key)
        return 0
    finally:
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap a local tenant and print its one-time API key"
    )
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--principal-name", default="developer")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
