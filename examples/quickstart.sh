#!/usr/bin/env bash
# 一键本地体验：bootstrap 租户 → 创建知识库 → 列表查询
# 前置：docker compose up -d postgres 且 uvicorn api:app 已启动
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${RAG_API_KEY:-}" ]; then
  RAG_API_KEY="$(.venv/bin/python scripts/bootstrap_tenant.py --tenant-name demo --principal-name developer)"
  echo "bootstrap key (仅显示一次): $RAG_API_KEY"
fi

curl -s -X POST -H "Authorization: Bearer $RAG_API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"manuals","graph_enabled":false}' http://localhost:8000/v1/knowledge-bases
echo
curl -s -H "Authorization: Bearer $RAG_API_KEY" http://localhost:8000/v1/knowledge-bases
echo
