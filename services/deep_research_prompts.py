"""Deep Research 分层 Prompt 片段（与 settings.webpage_prompt 拼接，不替代完整 schema）。"""

COMPLEXITY_GUIDANCE = {
    "simple": (
        "研究复杂度：simple。建议 sections 1~2 个、KPI 0~3 个、charts 0~2 个（仅当存在可视化价值数据时）。"
        "分析保持精炼，不要堆砌模块。"
    ),
    "standard": (
        "研究复杂度：standard。建议 sections 3~5 个、KPI 3~6 个、charts 1~3 个（数据驱动，宁缺毋滥）。"
        "每节完整 OIIUO+mechanism+insight。"
    ),
    "deep": (
        "研究复杂度：deep。建议 sections 4~7 个、KPI 4~8 个、charts 2~5 个（仅当有可靠可视化数据）。"
        "强化机制、风险、趋势、交叉分析；cross_section_insights 1~3 条。"
    ),
}

RESEARCH_COMPLEXITY_PROMPT = """
# 研究复杂度（必须由你判断并写入 metadata）

在 report_json 的 metadata 中输出：
"research_complexity": "simple | standard | deep",
"complexity_reason": "一句话说明为何选择该复杂度"

判断依据（综合，不按输入字数）：
- 研究主题是否复杂、是否多维比较/趋势预测/风险判断
- 数据丰富程度与可分析价值
- 是否启用 Web Search 且获得有效来源
- 用户是否要求深度分析/对比/竞争格局/预测

{complexity_hint}

{complexity_guidance}
"""

QUALITY_RULES_PROMPT = """
# Deep Research 质量规则

## 模块递进（禁止机械重复）
Summary(What happened) → Findings(最重要发现) → Section(Why/So What/What Next) → Chart(Evidence+Insight) → Recommendation(行动)

## 正文与来源
- 启用 Web Search 时，在 interpretation / mechanism / implication / outlook / insight 等分析句末**可且应尽量**标注 [sN]（N 须对应 sources 中真实 id）。
- 每个 [sN] 必须同时在 used_source_ids / data_source_refs 中出现；禁止引用不存在的编号。
- 优先消化 Web 来源材料：不同 section 分散引用，尽量覆盖更多来源，避免只引用 s1。
- 用户原文优先级最高；不要机械堆砌 snippet；summary 保持简洁，少放 [sN]。

## Section 深度链（每节尽量完整）
observation / interpretation / mechanism / implication / uncertainty / outlook / insight + used_source_ids

## 图表（数据驱动，非长度驱动）
仅当输入或 Web snippet 存在时间序列、占比、排名、对比等可视化价值数据时才生成 charts。
每项含 chart_insight、interpretation、data_confidence(verified|derived|unverified)、data_source_refs、data_notes。

## recommendations
target、rationale（来自前文）、action、priority(P0|P1|P2)、risk、used_source_ids；禁止空泛口号。
"""

WEB_SEARCH_PROMPT = """
# Web Search 专用规则（已启用）

- 用户原文优先级最高；Web 用于 interpretation / mechanism / implication / outlook 的原因、趋势、背景。
- 不要大段复制 snippet；不要堆在 summary。
- 在分析层句末使用 [s1]、[s2] 等标注（仅引用来源列表中存在的 id）；同步填写 used_source_ids / data_source_refs。
- 尽量**分散引用**检索到的多条来源：每个 section、key_finding、recommendation 至少 1 个 used_source_ids；有图表则填写 data_source_refs 与 data_notes。
- 若检索到 N 条来源，目标是在全报告中引用尽可能多的相关来源（通常应明显多于 1 条）。
- charts/kpis 数字须来自用户原文或来源 snippet，不得仅凭 Web Answer 编造精确数字。
"""

SCHEMA_SOURCE_FIELDS_PROMPT = """
# 结构化来源字段（Web Search 有 sources 时尽量填写）

sections[]: used_source_ids: ["s1","s3"], interpretation 句末可写 "...趋势加强 [s3]"
key_findings[]: used_source_ids: ["s2"]
charts[]: data_source_refs: ["s1"], data_notes: "数据说明"
recommendations[]: used_source_ids: ["s4"]

sections[] 新增分析层 mechanism（机制层，解释驱动因素）。
recommendations[].priority 使用 P0 | P1 | P2。
"""
