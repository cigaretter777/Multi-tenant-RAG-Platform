"""双租户四知识库演示 fixtures 与问题集（设计文档 §10.1）。

问题集覆盖：单文档事实、关键词匹配、口语化表达、跨段落、跨文档、多跳、
无答案、越权请求。chunk/问题规模仅为 harness 自证与示例，真实评测需扩集。
"""
from typing import Dict, List

TENANTS = ["tenant_auto", "tenant_tech"]

KNOWLEDGE_BASES: Dict[str, List[str]] = {
    "tenant_auto": ["汽车用户手册", "汽车售后FAQ"],
    "tenant_tech": ["Python框架文档", "数据库运维文档"],
}

CHUNKS: Dict[str, List[Dict]] = {
    "汽车用户手册": [
        {"chunk_id": "um-1", "text": "胎压报警灯亮起时，请先停车检查四个轮胎的胎压是否低于标准值。", "page": 36},
        {"chunk_id": "um-2", "text": "标准胎压值标注在驾驶员侧门框标签上，冷胎测量为准。", "page": 36},
        {"chunk_id": "um-3", "text": "更换机油的保养间隔为每一万公里或十二个月，以先到者为准。", "page": 58},
        {"chunk_id": "um-4", "text": "电池管理系统负责监控电芯电压、温度与充放电回路。", "page": 71},
    ],
    "汽车售后FAQ": [
        {"chunk_id": "faq-1", "text": "胎压传感器电池耗尽会导致胎压报警误报，需更换传感器总成。", "page": 3},
        {"chunk_id": "faq-2", "text": "保养后未复位保养灯会导致下次保养提醒提前出现。", "page": 7},
    ],
    "Python框架文档": [
        {"chunk_id": "py-1", "text": "FastAPI 的依赖注入系统通过函数签名声明依赖并自动解析。", "page": 12},
        {"chunk_id": "py-2", "text": "Pydantic 模型在请求进入路由前完成校验与类型转换。", "page": 15},
    ],
    "数据库运维文档": [
        {"chunk_id": "db-1", "text": "PostgreSQL  vacuum 回收死元组，长期不执行会导致表膨胀。", "page": 44},
        {"chunk_id": "db-2", "text": "连接池大小应按 CPU 核数两倍加有效磁盘数估算。", "page": 51},
    ],
}

QUESTIONS: List[Dict] = [
    {"question": "胎压报警后应该怎么办？", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": ["um-1"], "type": "single_fact", "answerable": True},
    {"question": "门框标签 冷胎", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": ["um-2"], "type": "keyword", "answerable": True},
    {"question": "车子提示胎压不对劲，我先干啥？", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": ["um-1"], "type": "colloquial", "answerable": True},
    {"question": "胎压标准值在哪里看，测量有什么条件？", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": ["um-1", "um-2"], "type": "cross_paragraph", "answerable": True},
    {"question": "胎压报警误报可能和售后说的哪个部件有关？", "tenant": "tenant_auto",
     "kbs": ["汽车用户手册", "汽车售后FAQ"], "relevant": ["um-1", "faq-1"], "type": "cross_doc", "answerable": True},
    {"question": "电池管理系统与充放电回路之间是什么关系？", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": ["um-4"], "type": "multi_hop", "answerable": True},
    {"question": "如何更换车机系统的液晶屏幕供应商？", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": [], "type": "no_answer", "answerable": False},
    {"question": "PostgreSQL vacuum 的作用是什么？", "tenant": "tenant_auto", "kbs": ["汽车用户手册"],
     "relevant": [], "type": "cross_tenant", "answerable": False},
]
