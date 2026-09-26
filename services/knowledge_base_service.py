"""租户隔离的知识库业务规则。

所有仓储调用都使用 principal.tenant_id；跨租户与不存在的知识库
统一抛 KnowledgeBaseForbidden，避免通过错误语义枚举资源。
"""
from typing import Dict, List
from uuid import UUID

from platform_auth.models import Principal
from repositories.control_plane import DuplicateKnowledgeBaseName


class KnowledgeBaseForbidden(Exception):
    """知识库对当前租户不可用（不存在或属于其他租户）。"""


class KnowledgeBaseConflict(Exception):
    """同一租户下知识库重名。"""


class KnowledgeBaseService:
    def __init__(self, repository):
        self.repository = repository

    async def create(self, principal: Principal, name: str, graph_enabled: bool) -> Dict:
        try:
            return await self.repository.create_knowledge_base(
                principal.tenant_id, name, graph_enabled
            )
        except DuplicateKnowledgeBaseName as exc:
            raise KnowledgeBaseConflict("knowledge base name already exists") from exc

    async def list(self, principal: Principal) -> List[Dict]:
        return await self.repository.list_knowledge_bases(principal.tenant_id)

    async def get(self, principal: Principal, kb_id: UUID) -> Dict:
        row = await self.repository.get_knowledge_base(principal.tenant_id, kb_id)
        if row is None:
            raise KnowledgeBaseForbidden("knowledge base unavailable")
        return row
