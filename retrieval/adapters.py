"""既有检索实现与存储后端的适配层。

`build_milvus_expr` 把检索上下文翻译为 Milvus 过滤表达式；
所有检索必须同时带租户与知识库过滤（设计文档 §5.3）。
旧链路 id 为 BIGINT，故表达式使用整数字面量。
"""
from retrieval.base import RetrievalContext


def build_milvus_expr(ctx: RetrievalContext) -> str:
    kb_list = ", ".join(str(int(kb)) for kb in ctx.kb_ids)
    return f"tenant_id == {int(ctx.tenant_id)} and kb_id in [{kb_list}]"
