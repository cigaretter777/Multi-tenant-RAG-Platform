"""v1 路由组合。"""
from fastapi import APIRouter

from platform_api.ingest import router as ingest_router
from platform_api.knowledge_bases import router as knowledge_bases_router

router = APIRouter()
router.include_router(knowledge_bases_router)
router.include_router(ingest_router)
