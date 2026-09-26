from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    principal_id: UUID
    tenant_id: UUID
    name: str
