"""鉴权后的知识库路由：/v1/knowledge-bases。"""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from configs.config import settings
from platform_api.schemas import KnowledgeBaseCreate, KnowledgeBaseView
from platform_auth.dependencies import get_current_principal
from platform_auth.models import Principal
from repositories.control_plane import ControlPlaneRepository
from services.knowledge_base_service import (
    KnowledgeBaseConflict,
    KnowledgeBaseForbidden,
    KnowledgeBaseService,
)
from utils.db import DatabaseManager

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


def get_knowledge_base_service() -> KnowledgeBaseService:
    return KnowledgeBaseService(ControlPlaneRepository(DatabaseManager))


@router.post("", response_model=KnowledgeBaseView, status_code=201)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
):
    try:
        row = await service.create(principal, payload.name, payload.graph_enabled)
    except KnowledgeBaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return KnowledgeBaseView(**row)


@router.get("", response_model=List[KnowledgeBaseView])
async def list_knowledge_bases(
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
):
    rows = await service.list(principal)
    return [KnowledgeBaseView(**row) for row in rows]


@router.get("/{kb_id}", response_model=KnowledgeBaseView)
async def get_knowledge_base(
    kb_id: UUID,
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
):
    try:
        row = await service.get(principal, kb_id)
    except KnowledgeBaseForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return KnowledgeBaseView(**row)
