"""v1 请求/响应模型。

请求模型中不包含 tenant_id：租户身份只能来自服务端解析的 API Key。
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    graph_enabled: bool = False


class KnowledgeBaseView(BaseModel):
    id: UUID
    name: str
    graph_enabled: bool
    status: Literal["active", "disabled", "deleting"]
