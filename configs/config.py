"""
配置管理模块
使用 pydantic-settings 管理配置，支持从 .env 文件读取
"""
from typing import Dict, Any, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ============ 应用配置 ============
    app_env: str = Field(default="prod", description="运行环境")
    app_name: str = Field(default="embedding-service", description="应用名称")
    app_version: str = Field(default="2.0.0", description="应用版本")
    visualization_only: bool = Field(default=False, description="是否仅启动知识可视化接口")

    # ============ Embedding 模型配置 ============
    embedding_model_name: str = Field(default="bge-m3-finetune", description="Embedding 模型名称")
    embedding_server: str = Field(default="http://localhost:8090/v1", description="Embedding 服务地址")
    embedding_key: str = Field(default="", description="Embedding key")
    embedding_dim: int = Field(default=1024, description="向量维度")
    chunk_size: int = Field(default=300, description="文本分块大小")
    chunk_overlap: int = Field(default=100, description="分块重叠大小")

    # ============ Milvus 配置 ============
    milvus_uri: str = Field(default="http://localhost:19530", description="Milvus URI")
    milvus_user: str = Field(default="root", description="Milvus 用户名")
    milvus_password: str = Field(default="", description="Milvus 密码")
    milvus_db_name: str = Field(default="kbs", description="Milvus 数据库名")
    milvus_insert_batch_size: int = Field(default=500, description="Milvus 单次 insert 批次大小，避免超过 gRPC 64MB 限制")

    # Milvus 测试环境配置
    milvus_test_uri: str = Field(default="http://localhost:19530", description="Milvus 测试 URI")
    milvus_test_user: str = Field(default="root", description="Milvus 测试用户名")
    milvus_test_password: str = Field(default="", description="Milvus 测试密码")
    milvus_test_db_name: str = Field(default="kbs", description="Milvus 测试数据库名")

    # ============ 检索配置 ============
    similarity_threshold: float = Field(default=0.5, description="相似度阈值")
    similarity_top_k: int = Field(default=3, description="默认返回结果数量")
    hybrid_ranker_k: int = Field(default=60, description="RRF 融合参数 k")

    # ============ 外部服务配置 ============
    ocr_url: str = Field(default="http://localhost:31780/upload_pic", description="OCR 服务地址")
    vl_model_url: str = Field(default="http://127.0.0.1:8000/v1/chat/completions", description="VL模型服务地址，用于生成图片描述")
    vl_model_name: str = Field(default="gpt-4-vision-preview", description="VL模型名称")
    vl_model_key: str = Field(default="", description="VL模型 API Key")
    vl_model_timeout: int = Field(default=60, description="VL模型超时时间(秒)")
    vl_model_prompt: str = Field(
        default="请详细描述这张图片的内容，生成适合用于向量匹配的描述性文本。\n\n要求：\n1. 全面描述图片中的所有视觉元素（物体、人物、场景、颜色、布局等）\n2. 使用自然、流畅的语言，避免过于简单的词汇\n3. 包含图片的主题、风格、情感等抽象特征\n4. 描述应该足够详细，能够用于后续的语义检索和向量匹配\n5. 输出应该是连贯的段落，而不是列表或要点\n\n请直接输出描述文本，不要包含任何解释性文字。",
        description="VL模型生成图片描述的Prompt"
    )
    v2t_url: str = Field(default="http://localhost:30086/v2t", description="音频转文本服务地址")
    v2t_timeout: int = Field(default=120, description="音频转文本超时时间(秒)")
    domain_name: str = Field(default="http://localhost:8000", description="域名")
    guard_url: str = Field(default="http://localhost:8020/llm08/preprocess", description="防护服务地址")
    graphrag_base_url: str = Field(
        default="http://localhost:8001",
        description="GraphRAG 服务地址",
    )
    graphrag_timeout: int = Field(default=120, description="GraphRAG 请求超时时间(秒)")
    graphrag_enabled: bool = Field(default=True, description="是否启用 GraphRAG 对接")
    graphrag_chunk_size: int = Field(default=500, description="GraphRAG 建图切块大小（字符）")
    graphrag_chunk_overlap: int = Field(default=50, description="GraphRAG 建图切块重叠（字符）")
    graphrag_poll_interval: int = Field(default=2, description="GraphRAG 建图进度轮询间隔(秒)")

    # ============ Chat 模型配置 ============
    chat_model_url: str = Field(default="http://127.0.0.1:8000/v1/chat/completions", description="Chat模型服务地址")
    chat_model_name: str = Field(default="default", description="Chat模型名称")
    chat_model_key: str = Field(default="", description="Chat模型 API Key")
    chat_model_timeout: int = Field(default=120, description="Chat模型超时时间(秒)")
    chat_model_request_retries: int = Field(default=2, description="Chat模型 requests 调用失败重试次数")
    chat_model_curl_fallback: bool = Field(default=True, description="Chat模型 requests TLS/连接失败时是否回退到 curl")
    chat_model_curl_path: str = Field(default="curl", description="curl 可执行文件路径")

    # ============ Web Search 配置 ============
    # 服务端能力开关：默认开启。实际是否发起检索由 API 请求参数 enable_web_search 控制（默认 false）。
    web_search_enabled: bool = Field(
        default=True,
        description="是否允许服务端调用 Web Search（管理员关闭开关；用户侧仍用 enable_web_search 控制单次请求）",
    )
    web_search_provider: str = Field(default="bocha_internal", description="Web Search 提供方: bocha_internal/mock/none")
    web_search_url: str = Field(default="http://localhost:31887/web_search", description="Web Search 服务地址")
    web_search_default_count: int = Field(default=3, description="Web Search 默认返回条数")
    web_search_max_count: int = Field(default=10, description="Web Search 最大返回条数")
    web_search_default_answer: bool = Field(default=False, description="Web Search 是否默认请求搜索侧总结")
    web_search_timeout: int = Field(default=15, description="Web Search 超时时间(秒)")
    web_search_context_max_len: int = Field(default=3000, description="注入 Prompt 的 Web Search 上下文最大字符数")

    mindmap_prompt: str = Field(
        default="请基于以下回答内容，生成一个思维导图结构，要求：\n\n1. 使用JSON格式\n2. 包含字段：title, children\n3. 每个节点不超过10个字\n4. 层级不超过3层\n5. 结构清晰、无重复\n\n输出仅包含JSON，不要解释。\n\n内容如下：\n{text}",
        description="Chat模型生成思维导图的Prompt"
    )
    mermaid_prompt: str = Field(
        default="请基于以下回答内容，生成一个Mermaid，要求：\n\n1. Mermaid代码必须语法正确\n2. Mermaid代码必须可以直接渲染\n3. 不允许省略节点定义\n4. 节点名称简洁\n5. 节点文本长度不超过15个字符\n6. 层级不超过4层\n\n输出仅包含JSON，不要解释。\n\n内容如下：\n{text}",
        description="Chat模型生成Mermaid图表的Prompt"
    )
    webpage_prompt: str = Field(
        default="""你是一个 Deep Research 报告生成助手。

请根据输入文本，生成 Deep Research 结构化报告 JSON。输出必须仅包含合法 JSON，不允许 Markdown，不允许解释文字。

# 顶层输出格式

{
  "title": {
    "id": "1",
    "text": "研究报告标题"
  },
  "summary": {
    "id": "2",
    "text": "300字以内执行摘要"
  },
  "kpis": [
    {
      "id": "2.1",
      "label": "指标名称",
      "value": "指标数值",
      "description": "指标说明",
      "evidence": ["来自输入文本的证据片段"]
    }
  ],
  "research_overview": {
    "id": "3",
    "question": "核心研究问题",
    "scope": "研究范围与边界",
    "method": "基于输入文本进行归纳、比较、趋势判断和结构化分析"
  },
  "key_findings": [
    {
      "id": "4.1",
      "title": "发现标题",
      "insight": "发现说明",
      "evidence": [],
      "confidence": "high"
    }
  ],
  "sections": [
    {
      "id": "5.1",
      "title": "章节标题",
      "summary": "本节分析角度导言（40~80字）",
      "observation": "核心事实观察（避免重复 Executive Summary 与 KPI 原句）",
      "interpretation": "原因解释：为什么发生",
      "implication": "影响判断：意味着什么",
      "uncertainty": "不确定性或信息局限（涉及预测时尽量填写，可为空字符串）",
      "outlook": "未来趋势或演化方向",
      "insight": "本节最有价值的研究洞察（1~2句，必填）",
      "content": "",
      "evidence": [],
      "visual_refs": ["7.1"]
    }
  ],
  "mindmap": {
    "id": "6",
    "title": "知识结构",
    "nodes": [
      {
        "id": "6.1",
        "label": "节点名称",
        "children": []
      }
    ]
  },
  "charts": [
    {
      "id": "7.1",
      "type": "bar",
      "title": "图表标题",
      "description": "图表数据来源说明",
      "chart_insight": "该图表最重要的研究结论（必填，不得只重复 data 中的数字）",
      "why_this_chart": "为何选择此图表类型展示该数据",
      "interpretation": "图表背后的含义、结构变化或趋势解读",
      "data": {
        "labels": [],
        "values": []
      }
    }
  ],
  "cross_section_insights": [
    "跨章节关联洞察：不同 section 之间的联动、共因或张力（1~3 条，证据不足可为 []）"
  ],
  "conclusion": {
    "id": "8",
    "headline": "一句话总判断（收束全文核心结论）",
    "problem_analysis": "综合判断：归纳前文发现的核心问题、态势或矛盾（按研究主题自适应表述）",
    "root_causes": "关键驱动：根本原因、结构性因素或主要因果链",
    "strategic_implications": "战略启示：对决策方、产业或组织的含义与影响（按主题自适应，非投资报告也可写运营/技术启示）",
    "text": "展望收束：基于证据的下一阶段方向与综合判断",
    "disclaimer": "研究边界、数据周期与后续评估建议（勿写固定行业话术）"
  },
  "outlook_trends": [
    {
      "id": "8.1",
      "title": "趋势或要点标题",
      "description": "基于前文分析提炼的展望要点（40~100 字）"
    }
  ],
  "recommendations": [
    {
      "id": "9.1",
      "target": "建议目标",
      "rationale": "基于前文分析为何提出该建议",
      "action": "具体可执行行动",
      "priority": "P0",
      "risk": "潜在风险或注意事项",
      "title": "",
      "description": ""
    }
  ],
  "sources": [],
  "warnings": []
}

---

# 通用规则

1. 必须保留 title、summary、mindmap、charts 四个字段，以兼容既有 webpage 渲染。
2. 必须生成 research_overview、key_findings、sections、conclusion 字段。
3. 必须生成 kpis 字段；无明确数字指标时返回 []。
4. recommendations 可以为空数组，但字段必须存在。
5. cross_section_insights 可以为空数组，但字段必须存在。
6. outlook_trends 可以为空数组，但字段必须存在。
7. sources 和 warnings 字段必须存在；无 Web Search 来源或无警告时返回 []。
8. 所有 id 必须是字符串类型，必须唯一，并按编号规则生成。
9. 不得编造输入文本或 Web Search 来源中没有的事实、数字、比例、金额、年份、排名或外部背景。
10. 关键数据与 Web 来源观点须自然融入 analysis 正文字段（如 observation、interpretation）；启用 Web Search 时可在分析句末标注 [sN]（N 须为真实来源 id），并同步填写 used_source_ids / data_source_refs；sections 与 key_findings 的 evidence 字段固定返回 []。
11. 对短文本不要强行编造复杂章节，数组可以为空，但顶层字段必须完整。
12. key_findings.confidence 只允许 high、medium、low；recommendations.priority 只允许 P0、P1、P2（兼容 high/medium/low，后端会规范化）。

---

# 模块分工与反重复规则（重要）

各模块职责必须区分，禁止同一组数字/句子在多处机械重复：

1. summary：整体判断与叙事框架；可概括 2~3 个最重要结论，但不要罗列全部 KPI 数字。
2. kpis：只承担「指标卡片」职能——label、value、一句话 description；不在此做深度因果分析。
3. key_findings：跨主题、跨章节的高层次发现；每条 insight 侧重「说明+影响」，不要复制 section 全文。
4. sections：Deep Research 核心深度层；必须按 OIIUO 范式展开（见下），提供 summary/KPI/findings 中没有的新增分析。
5. charts：data 展示事实；chart_insight / interpretation 必须解释「所以呢」，不得只复述坐标轴数字。
6. conclusion（结构化）：problem_analysis / root_causes / strategic_implications / text 分工明确，收束 cross_section_insights；不要复制 summary 原句。
7. outlook_trends：从前文 OIIUO 与 cross_section_insights 提炼 3~6 条展望要点；短文本可为 []。
8. recommendations：必须能从 sections/findings 的分析逻辑推导，禁止空泛口号。

硬性禁止：
- 不要在 section 中机械重复 summary、KPI 或 key_findings 已出现的完整句子。
- 若某数字已在 KPI 出现，section 中应解释其原因、影响与趋势，而非再次报数。
- evidence 是引用片段，不得与 observation/interpretation 正文逐字重复。
- sections 与 key_findings 的 evidence 必须返回 []；[sN] 仅允许引用 sources 中存在的编号，须与 used_source_ids 一致；禁止 [Web Answer] 或“来源：...”等不规范标记。
- 不要为了凑长度重复同一事实。

---

# 可选 Web Search 上下文规则

系统可能会提供 Web Search 上下文。如果没有 Web Search 上下文，请完全基于输入文本生成报告，不要声称使用了外部检索。

Web Search 上下文如下：
{web_context}

使用 Web Search 时必须遵守：

1. 用户输入文本是最高优先级；Web Search 只作为背景、补充信息和来源材料。
2. 每条来源带有 [s1]、[s2] 等编号；在 interpretation / mechanism / implication / outlook 等分析句末标注对应 [sN]，并写入 used_source_ids / data_source_refs；尽量分散引用多条来源。
3. Web Search 信息须融入 sections 的 OIIUO 分析句中；不要将所有 Web 材料堆在同一段。
4. sections 的 interpretation/implication 应优先吸收 Web 补充观点，与章节主题一致；不要把所有 Web 材料堆在同一段。
5. 参考来源由前端在报告末尾单独展示，正文中不要写「来源列表」或「Web Search 来源」章节。
6. charts 和 kpis 只能使用输入文本或 [sN] 来源 snippet 中明确出现的数字；不得只根据 Web Answer/summary 生成精确图表或 KPI。
7. Web Answer/summary 只是辅助阅读，优先级低于输入文本和来源 snippet；如果没有 sources，不能生成依赖外部数字的 charts/kpis。
8. 不得编造 URL、来源标题、年份、比例、金额或排名。
9. 如果 Web Search 结果为空、只有总结没有来源，或与输入文本冲突，应在 warnings 中简短说明。

---

# 编号规则

- title: "1"
- summary: "2"
- kpis: "2.1", "2.2" ...（建议 3~6 个，位于 summary 之后）
- research_overview: "3"
- key_findings: "4.1", "4.2" ...
- sections: "5.1", "5.2" ...
- mindmap: "6"，节点从 "6.1" 开始
- charts: "7.1", "7.2" ...
- conclusion: "8"
- outlook_trends: "8.1", "8.2" ...
- recommendations: "9.1", "9.2" ...

---

# summary 要求

1. 提炼执行摘要，不超过 400 字；需体现 Deep Research 深度，而非简单罗列事实。
2. 必须覆盖：核心问题、2~3 个最重要发现、整体判断方向。
3. 先结论后论据，避免空泛口号。

---

# Deep Research 分析范式（OIIUO）

每个 section 必须按以下逻辑组织（使用独立字段，content 留空 ""）：

1. observation（发生了什么）：100~180 字。提炼本节最关键事实，可含必要数字，但不做 KPI 式罗列；必须说明事实之间的关系，避免重复 Executive Summary。
2. interpretation（为什么发生）：140~240 字。解释因果链、传导机制、对比关系、结构约束或历史背景；必须回答“为什么是现在发生、为什么以这种方式发生”，不能只写单一原因。
3. implication（意味着什么）：140~240 字。分析对产业、市场、技术路线、竞争、用户或决策的直接影响与二阶影响，至少包含“受益方/承压方/变化方向”中的两个角度。
4. uncertainty（不确定性）：60~120 字。说明口径差异、样本局限、政策连续性、价格波动、技术成熟度或预测风险；涉及预测/占比/未来趋势时必须填写。
5. outlook（接下来可能怎样）：100~180 字。基于已有证据给出情景判断、触发条件和演化方向，禁止无依据的精确预测。
6. insight（必填）：80~140 字。本节独占的研究结论，必须回答「所以呢」，并提炼一个可用于决策的判断，不得复述 observation 原句。

写作要求：
- 各层之间必须信息递进，禁止五层写同一句话的换皮重复。
- interpretation / implication / outlook 至少两层非空且各不少于 120 字（短文本输入时可适当缩减）。
- 每个 section 的 insight 必须非空且与其他 section 角度不同。
- 输入充足时建议 2~5 个 sections；短文本可减少。
- Web 来源观点写入 interpretation 或 implication；启用 Web Search 时可在引用了该来源的分析句末标注 [sN]（N 须为真实来源 id），并与 used_source_ids 保持一致；不要输出 evidence 数组。

key_findings.insight 每条 120~220 字，必须含「说明：」与「影响：」两段（换行分隔）；evidence 返回 []。
conclusion 各层合计 400~800 字；text 单独 80~180 字作收束展望。
cross_section_insights 1~3 条，每条 80~160 字，揭示章节间联动。
outlook_trends 输入充足时 3~6 条，每条 description 40~100 字。

---

# kpis 要求

1. 从输入文本或 Web Search 来源 snippet 中提取明确数字、比例、金额、时间、数量等关键指标。
2. 不得编造；若不存在明确指标，kpis 必须返回 []。
3. 建议提取 3~6 个 KPI；每条包含 label（简短，建议不超过 12 字）、value（保留原文单位）、description（一句话说明）、evidence。
4. evidence 必须来自输入文本或 [sN] 来源 snippet，不得虚构；Web 数字须在 evidence 标注 [sN]。
5. 不得仅依据 Web Answer/summary 生成 KPI 数字。
6. value 保留原文表述（如 "25%"、"4500亿美元"）。

---

# research_overview 要求

1. question: 概括输入文本对应的核心研究问题。
2. scope: 说明研究范围与边界。
3. method: 未提供 Web Search 上下文时，写“基于输入文本进行归纳、比较、趋势判断和结构化分析”；提供 Web Search 来源时，写“基于输入文本，并结合 Web Search 公开信息补充分析”。不要声称使用了数据库或 RAG。

---

# key_findings 要求

1. 提炼关键发现，每条包含 title、insight、confidence；evidence 固定返回 []。
2. insight 须为跨章节的宏观判断（120~220 字），含「说明：」「影响：」两行，不可复制 section 的 OIIUO 原文。
3. 文本与 Web 证据不足时 key_findings 可以为空数组，不要编造。

---

# sections 要求

1. sections 是报告最核心的深度内容，必须完整填写 OIIUO 六层 + insight。
2. 每节必填：title、summary、observation、interpretation、implication、outlook、insight、visual_refs；uncertainty 尽量填写；content 留空 ""；evidence 返回 []。
3. summary：50~100 字，点明本节分析角度，不重复 observation。
4. 输入充足时，每个 section 至少保证 5 个非空分析层，observation / interpretation / implication / uncertainty / outlook 为优先必填层。
5. 禁止只写 observation 而 interpretation/implication 为空或敷衍（输入充足时）；interpretation 必须解释机制，implication 必须分析二阶影响。
6. 避免“口号式”句子；每层至少包含 2 个信息点（事实+解释、原因+机制、影响+对象、趋势+条件等）。
7. 启用 Web Search 时，section 分析层可在句末标注 [sN]（须为真实来源 id），并同步填写 used_source_ids；报告末尾仅展示被引用的来源。
8. visual_refs 只能引用存在的 chart id；无关联图表时返回 []。
9. 文本很短时 sections 可少于 2 节或为空数组。

---

# cross_section_insights 要求

1. 数组，0~3 条字符串；每条 60~150 字。
2. 揭示不同 section 之间的联动、共因、张力或因果链，不得重复单节 insight 原句。
3. 证据不足时返回 []。

---

# mindmap 要求

1. 使用 mindmap 表达研究主题的知识结构。
2. 格式必须为 {"id":"6","title":"...","nodes":[{"id":"6.1","label":"...","children":[]}]}。
3. 每个节点必须有 id、label、children。
4. 层级不超过 4 层，节点名称简洁。

---

# charts 要求

1. charts 支持以下 type（按数据特征选择最合适的一种）：
   bar、line、pie、table、area、horizontal_bar、scatter、radar、gauge、funnel、donut、stacked_bar、heatmap
2. table 也必须放在 charts 中，type 为 "table"，不要生成 tables 字段。
3. charts 数量不设上限；不得重复表达同一组数据。
4. 只有输入文本或 Web Search 来源 snippet 中存在明确数字、比例、金额、年份、时间序列、排名或分类统计时，才允许生成 charts。
5. 不得凭常识、Web Answer/summary 或外部知识补充图表数据。
6. 如果没有明确可视化数据，charts 必须返回 []。
7. 每个 chart 必须包含 id、type、title、description、data、chart_insight。
8. chart_insight 必填：80~150 字，说明趋势/结构/差异的研究结论，不得只重复 labels/values 数字。
9. interpretation 必填：80~150 字，解释图表背后含义；why_this_chart 简要说明选图理由。
10. description 说明 data 来自输入文本或 [sN] 来源 snippet 的什么信息。
11. 每个 chart 应尽量通过 sections.visual_refs 关联到最相关章节。

charts 数据格式：

- bar / pie / funnel / donut / horizontal_bar: {"labels": ["A", "B"], "values": [10, 20]}
- line / area: {"categories": ["2021", "2022"], "values": [100, 120]}（也接受 labels 代替 categories）
- table: {"headers": ["字段1", "字段2"], "rows": [["值1", "值2"]]}
- scatter: {"x": [1, 2], "y": [10, 20]} 或 {"points": [[1, 10], [2, 20]]}
- radar: {"indicators": [{"name": "维度A", "max": 100}], "values": [80, 90]} 或 {"indicators": [...], "series": [{"name": "系列1", "values": [...]}]}
- gauge: {"value": 75, "max": 100, "name": "完成率"}
- stacked_bar: {"labels": ["Q1", "Q2"], "series": [{"name": "A", "values": [10, 20]}, {"name": "B", "values": [5, 15]}]}
- heatmap: {"xLabels": ["Mon", "Tue"], "yLabels": ["A", "B"], "values": [[1, 2], [3, 4]]}

---

# 第 07 章「总结与建议」要求（conclusion + outlook_trends + recommendations）

本章是全文收束层，须从前文 sections / key_findings / cross_section_insights 推导，按研究主题自适应表述（安全态势、产业研究、技术综述等均可），禁止写死某一行业话术。

## conclusion 结构化字段

1. headline：20~50 字，一句话总判断，可作为章节副标题。
2. problem_analysis（综合判断）：120~220 字。归纳核心问题、态势特征或主要矛盾；可条理化（1）…（2）…，但须基于前文，禁止复述 summary。
3. root_causes（关键驱动）：80~180 字。解释结构性原因、因果链或驱动因素；与 problem_analysis 信息递进，禁止同句换皮。
4. strategic_implications（战略启示）：80~180 字。对决策方/组织/产业的含义；非投资主题时写运营、技术或管理启示，勿强行写「投资主线」。
5. text（展望收束）：80~180 字。下一阶段方向、情景判断或结语；吸收 cross_section_insights 但不逐条复制。
6. disclaimer（研究说明）：40~100 字。说明数据/文本边界、评估周期与后续跟踪建议；按实际 scope 撰写，勿编造日期或机构名。

短文本输入时：headline 与 text 必填；problem_analysis / root_causes / strategic_implications 至少填 2 项；disclaimer 可简写。

## outlook_trends

1. 从前文 outlook / implication / cross_section_insights 提炼 3~6 条（短文本可为 []）。
2. 每条 title 8~20 字，description 40~100 字；角度应彼此区分，不得复制 section.insight 原句。
3. 编号 id 从 "8.1" 递增。

## recommendations（行动建议）

1. 输入充足时建议 3~6 条；每条必填 target、rationale、action、priority；risk 尽量填写。
   - target：建议目标（一句话，可含机制/制度名称）
   - rationale：基于哪些 section/findings 分析得出（40~100 字）
   - action：具体可执行行动（40~120 字）
   - risk：执行风险或注意事项
2. priority 只允许 P0、P1、P2（兼容 high/medium/low）；至少 1 条 P0 当存在紧迫问题时。
3. title、description 可留空；优先使用 target/rationale/action/risk。
4. 禁止空泛建议如「加大投入」「关注机会」而无前文依据。
5. 建议按 priority 排序：P0 在前。

---

请严格按照上述 JSON 结构输出。

内容如下：
{text}""",
        description="Chat模型生成 Deep Research 网页结构化JSON的Prompt"
    )
    webpage_prompt_light: str = Field(
        default="""你是一个 Deep Research 报告生成助手（轻量模式：输入较短，勿过度展开）。

请根据输入文本生成 Deep Research JSON。输出必须仅包含合法 JSON，不允许 Markdown。

轻量模式约束：
- sections 最多 2 节；kpis 最多 3 个；charts 最多 1 个；key_findings 最多 2 条
- cross_section_insights、outlook_trends、recommendations 可为 []
- 无明确数字则不生成 charts/kpis
- 不得编造输入中不存在的事实与数字

顶层字段：title, summary, kpis, research_overview, key_findings, sections, mindmap, charts,
cross_section_insights, conclusion, outlook_trends, recommendations, sources, warnings

sections 每层字段：id, title, summary, observation, interpretation, implication, uncertainty, outlook, insight, content(""), evidence([]), visual_refs

charts 每项含：id, type, title, description, chart_insight, interpretation, data_confidence(verified|derived|unverified), data

模块分工：summary=What happened；findings=最重要发现；section=Why/So What/What Next；chart=证据+洞察

Web Search 上下文：
{web_context}

内容如下：
{text}""",
        description="短文本（<300字）Deep Research Prompt"
    )

    # ============ NLTK 配置 ============
    nltk_data: str = Field(default="tmp/nltk_data", description="NLTK 数据目录")

    # ============ 日志配置 ============
    log_level: str = Field(default="INFO", description="日志级别")
    log_max_bytes: int = Field(default=10485760, description="日志文件最大大小")
    log_backup_count: int = Field(default=5, description="日志备份数量")

    # ============ 下载配置 ============
    download_dir: str = Field(default="downloads", description="文件下载目录")
    cleanup_downloads: bool = Field(default=True, description="是否清理下载的文件")

    # ============ 并发配置 ============
    max_workers: int = Field(default=4, description="最大工作线程数")
    embed_batch_size: int = Field(default=1024, description="Embedding 批处理大小")
    embed_timeout: int = Field(default=120, description="Embedding 超时时间")

    # ============ 解析结果存储配置 ============
    parse_result_ttl: int = Field(default=86400, description="解析结果默认过期时间(秒)，默认24小时")
    parse_result_max_ttl: int = Field(default=604800, description="解析结果最大过期时间(秒)，默认7天")
    parse_cleanup_interval: int = Field(default=3600, description="清理过期解析结果的间隔(秒)，默认1小时")

    # ============ PostgreSQL 配置 ============
    pg_host: str = Field(default="localhost", description="PostgreSQL 主机")
    pg_port: int = Field(default=5432, description="PostgreSQL 端口")
    pg_user: str = Field(default="postgres", description="PostgreSQL 用户名")
    pg_password: str = Field(default="", description="PostgreSQL 密码")
    pg_database: str = Field(default="embedding_db", description="PostgreSQL 数据库名")
    pg_schema: str = Field(default="rag", description="PostgreSQL schema")

    # PostgreSQL 测试环境配置
    pg_test_host: str = Field(default="localhost", description="PostgreSQL 测试主机")
    pg_test_port: int = Field(default=5432, description="PostgreSQL 测试端口")
    pg_test_user: str = Field(default="postgres", description="PostgreSQL 测试用户名")
    pg_test_password: str = Field(default="", description="PostgreSQL 测试密码")
    pg_test_database: str = Field(default="embedding_db_test", description="PostgreSQL 测试数据库名")
    pg_test_schema: str = Field(default="rag", description="PostgreSQL 测试 schema")

    @property
    def is_test_env(self) -> bool:
        """是否为测试环境"""
        return self.app_env == "test"

    @property
    def milvus_config(self) -> Dict[str, Any]:
        """获取当前环境的 Milvus 配置"""
        if self.is_test_env:
            return {
                "uri": self.milvus_test_uri,
                "user": self.milvus_test_user,
                "password": self.milvus_test_password,
                "db_name": self.milvus_test_db_name,
            }
        return {
            "uri": self.milvus_uri,
            "user": self.milvus_user,
            "password": self.milvus_password,
            "db_name": self.milvus_db_name,
        }

    @property
    def postgres_config(self) -> Dict[str, Any]:
        """获取当前环境的 PostgreSQL 配置"""
        if self.is_test_env:
            return {
                "host": self.pg_test_host,
                "port": self.pg_test_port,
                "user": self.pg_test_user,
                "password": self.pg_test_password,
                "database": self.pg_test_database,
                "schema": self.pg_test_schema,
            }
        return {
            "host": self.pg_host,
            "port": self.pg_port,
            "user": self.pg_user,
            "password": self.pg_password,
            "database": self.pg_database,
            "schema": self.pg_schema,
        }


# ============ 全局配置实例 ============

settings = Settings()


# ============ 向后兼容的变量导出 ============
# 保留原有的全局变量以便旧代码可以继续工作

EMB_ENV = settings.app_env
EMBEDDING_MODEL_NAME = settings.embedding_model_name
EMBEDDING_SERVER = settings.embedding_server
EMBEDDING_DIM = settings.embedding_dim
CHUNK_SIZE = settings.chunk_size
CHUNK_OVERLAP = settings.chunk_overlap
OCR_URL = settings.ocr_url
V2T_URL = settings.v2t_url
NLTK_DATA = settings.nltk_data
SIMILARITY_THRESHOLD = settings.similarity_threshold
SIMILARITY_TOP_K = settings.similarity_top_k
DOMAIN_NAME = settings.domain_name
GUARD_URL = settings.guard_url

MILVUS_CONFIG = {
    "uri": settings.milvus_uri,
    "user": settings.milvus_user,
    "password": settings.milvus_password,
    "db_name": settings.milvus_db_name,
}

MILVUS_CONFIG_TEST = {
    "uri": settings.milvus_test_uri,
    "user": settings.milvus_test_user,
    "password": settings.milvus_test_password,
    "db_name": settings.milvus_test_db_name,
}

# 导入 logger（需要在 settings 之后）
from utils.logger import get_logger
logger = get_logger()

# 打印配置信息
logger.info(f"========== 配置加载完成 ==========")
logger.info(f"环境: {settings.app_env}")
logger.info(f"Embedding 模型: {settings.embedding_model_name}")
logger.info(f"Milvus URI: {settings.milvus_uri if not settings.is_test_env else settings.milvus_test_uri}")
logger.info(f"===================================")
