import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "services" / "visualization_service.py"


def load_visualization_service():
    spec = importlib.util.spec_from_file_location("visualization_service_under_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.VisualizationService


class DeepResearchNormalizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_visualization_service()

    def test_missing_fields_are_backfilled(self):
        result = self.service._normalize_deep_research({})

        self.assertEqual(result["title"]["id"], "1")
        self.assertEqual(result["summary"]["id"], "2")
        self.assertEqual(result["research_overview"]["id"], "3")
        self.assertEqual(result["mindmap"]["id"], "6")
        self.assertEqual(result["conclusion"]["id"], "8")
        self.assertEqual(result["metadata"]["visualization_type"], "deep_research_webpage")
        self.assertEqual(result["metadata"]["chart_count"], 0)
        self.assertEqual(result["metadata"]["kpi_count"], 0)
        self.assertEqual(result["kpis"], [])
        self.assertEqual(result["sources"], [])
        self.assertFalse(result["metadata"]["web_search_requested"])
        self.assertFalse(result["metadata"]["web_search_enabled"])

    def test_string_text_blocks_are_normalized(self):
        result = self.service._normalize_deep_research({
            "title": "测试报告",
            "summary": 123,
            "conclusion": None
        })

        self.assertEqual(result["title"], {"text": "测试报告", "id": "1"})
        self.assertEqual(result["summary"], {"text": "123", "id": "2"})
        self.assertEqual(result["conclusion"]["text"], "")
        self.assertEqual(result["conclusion"]["id"], "8")
        self.assertEqual(result["conclusion"]["headline"], "")
        self.assertEqual(result["outlook_trends"], [])

    def test_invalid_list_items_are_filtered_and_ids_are_backfilled(self):
        result = self.service._normalize_deep_research({
            "key_findings": ["bad", {"title": "发现"}],
            "sections": ["bad", {"content": "分析"}],
            "recommendations": ["bad", {"description": "建议"}]
        })

        self.assertEqual(len(result["key_findings"]), 1)
        self.assertEqual(result["key_findings"][0]["id"], "4.1")
        self.assertEqual(result["key_findings"][0]["confidence"], "medium")
        self.assertEqual(result["key_findings"][0]["evidence"], [])

        self.assertEqual(len(result["sections"]), 1)
        self.assertEqual(result["sections"][0]["id"], "5.1")
        self.assertEqual(result["sections"][0]["evidence"], [])
        self.assertEqual(result["sections"][0]["visual_refs"], [])

        self.assertEqual(len(result["recommendations"]), 1)
        self.assertEqual(result["recommendations"][0]["id"], "9.1")
        self.assertEqual(result["recommendations"][0]["priority"], "P1")

    def test_charts_are_filtered_and_parallel_arrays_are_aligned(self):
        result = self.service._normalize_deep_research({
            "charts": [
                {"type": "bubble", "data": {}},
                {"type": "bar", "data": {"labels": ["A", "B"], "values": [1]}},
                {"type": "pie", "data": {"labels": [], "values": []}},
                {"type": "table", "data": {"headers": ["A"], "rows": []}},
                {"type": "line", "data": {"labels": ["2023", "2024"], "values": [10, 20, 30]}},
            ]
        })

        self.assertEqual(len(result["charts"]), 2)
        self.assertEqual(result["charts"][0]["type"], "bar")
        self.assertEqual(result["charts"][0]["data"]["labels"], ["A"])
        self.assertEqual(result["charts"][0]["data"]["values"], [1])
        self.assertEqual(result["charts"][1]["type"], "line")
        self.assertEqual(result["charts"][1]["data"]["categories"], ["2023", "2024"])
        self.assertEqual(result["charts"][1]["data"]["values"], [10, 20])
        self.assertIn("dropped_invalid_chart_type: bubble", result["metadata"]["warnings"])

    def test_kpis_are_normalized(self):
        result = self.service._normalize_deep_research({
            "kpis": ["bad", {"label": "规模", "value": "100"}, {"label": "", "value": "x"}]
        })
        self.assertEqual(len(result["kpis"]), 1)
        self.assertEqual(result["kpis"][0]["id"], "2.1")
        self.assertEqual(result["metadata"]["kpi_count"], 1)

    def test_kpis_are_capped_at_six(self):
        kpis = [{"label": f"指标{i}", "value": str(i)} for i in range(10)]
        result = self.service._normalize_deep_research({"kpis": kpis})
        self.assertEqual(len(result["kpis"]), 6)
        self.assertIn("truncated_kpis: max_6", result["metadata"]["warnings"])

    def test_kpi_label_is_truncated(self):
        result = self.service._normalize_deep_research({
            "kpis": [{"label": "这是一个超过十六个字符限制的指标名称", "value": "100%"}]
        })
        self.assertLessEqual(len(result["kpis"][0]["label"]), 16)
        self.assertIn("truncated_kpi_label", result["metadata"]["warnings"])

    def test_kpis_non_array_becomes_empty(self):
        result = self.service._normalize_deep_research({"kpis": "bad"})
        self.assertEqual(result["kpis"], [])
        self.assertIn("fixed_kpis: non_array", result["metadata"]["warnings"])

    def test_visual_refs_remove_invalid_chart_ids(self):
        result = self.service._normalize_deep_research({
            "sections": [{"title": "A", "visual_refs": ["7.1", "9.9"]}],
            "charts": [{"type": "bar", "id": "7.1", "data": {"labels": ["A"], "values": [1]}}]
        })
        self.assertEqual(result["sections"][0]["visual_refs"], ["7.1"])
        self.assertIn("removed_invalid_visual_ref: 9.9", result["metadata"]["warnings"])

    def test_table_rows_are_aligned_to_headers(self):
        result = self.service._normalize_deep_research({
            "charts": [{
                "type": "table",
                "id": "7.1",
                "data": {
                    "headers": ["A", "B", "C"],
                    "rows": [["1"], ["1", "2", "3", "4"]]
                }
            }]
        })
        rows = result["charts"][0]["data"]["rows"]
        self.assertEqual(rows[0], ["1", "", ""])
        self.assertEqual(rows[1], ["1", "2", "3"])
        self.assertTrue(any("fixed_table_row_length" in w for w in result["metadata"]["warnings"]))

    def test_empty_charts_and_invalid_types_are_dropped(self):
        result = self.service._normalize_deep_research({
            "charts": [
                {"type": "bubble", "data": {}},
                {"type": "pie", "data": {"labels": [], "values": []}},
            ]
        })
        self.assertEqual(result["charts"], [])
        self.assertIn("dropped_invalid_chart_type: bubble", result["metadata"]["warnings"])
        self.assertGreater(result["metadata"]["warning_count"], 0)

    def test_charts_are_not_capped(self):
        charts = [
            {"type": "bar", "id": f"7.{i}", "data": {"labels": ["A"], "values": [i]}}
            for i in range(1, 8)
        ]
        result = self.service._normalize_deep_research({"charts": charts})
        self.assertEqual(len(result["charts"]), 7)
        self.assertFalse(any("truncated_charts" in w for w in result["metadata"]["warnings"]))

    def test_extended_chart_types_are_accepted(self):
        result = self.service._normalize_deep_research({
            "charts": [
                {"type": "radar", "data": {
                    "indicators": [{"name": "A", "max": 100}, {"name": "B", "max": 100}],
                    "values": [80, 90]
                }},
                {"type": "gauge", "data": {"value": 72, "max": 100, "name": "完成率"}},
                {"type": "scatter", "data": {"x": [1, 2], "y": [3, 4]}},
            ]
        })
        self.assertEqual(len(result["charts"]), 3)
        types = {c["type"] for c in result["charts"]}
        self.assertEqual(types, {"radar", "gauge", "scatter"})

    def test_parallel_array_mismatch_adds_warning(self):
        result = self.service._normalize_deep_research({
            "charts": [{"type": "bar", "data": {"labels": ["A", "B"], "values": [1]}}]
        })
        self.assertTrue(any(w.startswith("fixed_chart_data_length:") for w in result["metadata"]["warnings"]))

    def test_source_markers_preserved_in_chart_when_valid(self):
        result = self.service._normalize_deep_research(
            {
                "charts": [{
                    "type": "bar",
                    "title": "销量预测",
                    "description": "基于输入文本与来源[s1]信息。",
                    "chart_insight": "市场继续增长 [s1]",
                    "interpretation": "渗透率继续提升",
                    "data": {"labels": ["2025"], "values": [1200]},
                    "data_source_refs": ["s1"],
                }],
            },
            {
                "requested": True,
                "enabled": True,
                "sources": [{"id": "s1", "title": "来源", "url": "", "snippet": "", "summary": ""}],
            },
        )
        chart = result["charts"][0]
        self.assertIn("[s1]", chart["chart_insight"])
        self.assertIn("[s1]", chart["description"])
        self.assertEqual(chart["data_source_refs"], ["s1"])

    def test_mindmap_nodes_are_normalized_recursively(self):
        result = self.service._normalize_deep_research({
            "mindmap": {
                "title": "知识结构",
                "nodes": [
                    {"title": "一级", "children": [{"label": "二级"}]},
                    "bad"
                ]
            }
        })

        nodes = result["mindmap"]["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], "6.1")
        self.assertEqual(nodes[0]["label"], "一级")
        self.assertEqual(nodes[0]["children"][0]["id"], "6.1.1")
        self.assertEqual(nodes[0]["children"][0]["label"], "二级")
        self.assertEqual(nodes[0]["children"][0]["children"], [])

    def test_web_search_context_controls_sources_and_metadata(self):
        result = self.service._normalize_deep_research(
            {
                "sources": [{"id": "s99", "title": "模型伪造来源"}],
                "key_findings": [{
                    "title": "发现",
                    "evidence": ["[s1] 明确来源片段。"]
                }]
            },
            {
                "requested": True,
                "enabled": True,
                "query": "测试查询",
                "provider": "mock",
                "sources": [{
                    "id": "s1",
                    "title": "真实来源",
                    "url": "https://example.com",
                    "snippet": "明确来源片段。",
                    "summary": ""
                }],
                "warnings": ["web_search_test_warning"]
            }
        )

        self.assertEqual(result["sources"][0]["id"], "s1")
        self.assertEqual(result["sources"][0]["title"], "真实来源")
        self.assertTrue(result["metadata"]["web_search_requested"])
        self.assertTrue(result["metadata"]["web_search_enabled"])
        self.assertEqual(result["metadata"]["source_count"], 1)
        self.assertIn("web_search_test_warning", result["metadata"]["warnings"])
        self.assertIn("dropped_llm_sources", result["metadata"]["warnings"])

    def test_answer_only_context_not_enabled_in_metadata(self):
        result = self.service._normalize_deep_research(
            {"title": {"id": "1", "text": "T"}},
            {
                "requested": True,
                "enabled": False,
                "query": "测试",
                "provider": "mock",
                "sources": [],
                "answer": "仅有搜索总结。",
                "has_web_answer": True,
                "warnings": ["web_search_no_sources"],
            },
        )
        self.assertFalse(result["metadata"]["web_search_enabled"])
        self.assertTrue(result["metadata"]["web_search_requested"])
        self.assertEqual(result["metadata"]["source_count"], 0)
        self.assertIn("仅有搜索总结", result["metadata"]["web_answer_preview"])

    def test_invalid_source_reference_adds_warning(self):
        result = self.service._normalize_deep_research(
            {
                "key_findings": [{
                    "title": "发现",
                    "insight": "某发现内容",
                    "used_source_ids": ["s2"],
                }]
            },
            {
                "requested": True,
                "enabled": True,
                "query": "测试查询",
                "provider": "mock",
                "sources": [{"id": "s1", "title": "来源1", "url": "", "snippet": "", "summary": ""}],
                "warnings": []
            }
        )

        self.assertIn("removed_invalid_source_ref:s2", result["metadata"]["warnings"])
        self.assertEqual(result["key_findings"][0]["used_source_ids"], ["s1"])
        self.assertIn("auto_assigned_source_refs", result["metadata"]["warnings"])

    def test_section_analysis_fields_are_preserved(self):
        result = self.service._normalize_deep_research({
            "sections": [{
                "title": "市场规模",
                "observation": "市场扩张",
                "interpretation": "需求驱动",
                "implication": "机会增加",
                "uncertainty": "预测口径不一",
                "outlook": "继续增长",
                "insight": "增长具有结构性",
                "evidence": ["4500亿美元"],
            }]
        })
        sec = result["sections"][0]
        self.assertEqual(sec["observation"], "市场扩张")
        self.assertEqual(sec["insight"], "增长具有结构性")

    def test_chart_insight_fields_are_preserved(self):
        result = self.service._normalize_deep_research({
            "charts": [{
                "type": "line",
                "data": {"labels": ["2023", "2024"], "values": [10, 20]},
                "chart_insight": "增速提升",
                "why_this_chart": "时间序列",
                "interpretation": "商业化加速",
            }]
        })
        chart = result["charts"][0]
        self.assertEqual(chart["chart_insight"], "增速提升")
        self.assertEqual(chart["interpretation"], "商业化加速")
        self.assertFalse(any("missing_chart_insight" in w for w in result["metadata"]["warnings"]))

    def test_recommendation_extended_fields_and_legacy_mapping(self):
        result = self.service._normalize_deep_research({
            "recommendations": [
                {
                    "target": "布局生成式AI",
                    "rationale": "占比最高",
                    "action": "优先行业Agent",
                    "risk": "关注ROI",
                    "priority": "high",
                },
                {"title": "旧标题", "description": "旧描述"},
            ]
        })
        self.assertEqual(result["recommendations"][0]["action"], "优先行业Agent")
        self.assertEqual(result["recommendations"][0]["priority"], "P0")
        self.assertEqual(result["recommendations"][1]["target"], "旧标题")
        self.assertEqual(result["recommendations"][1]["action"], "旧描述")

    def test_cross_section_insights_normalized(self):
        result = self.service._normalize_deep_research({
            "cross_section_insights": ["联动1", "联动2", "联动3", "联动4"]
        })
        self.assertEqual(len(result["cross_section_insights"]), 3)
        self.assertEqual(result["metadata"]["cross_section_insight_count"], 3)


    def test_section_evidence_is_cleared(self):
        result = self.service._normalize_deep_research({
            "sections": [{
                "title": "测试",
                "observation": "事实",
                "evidence": ["不应出现在正文"],
            }]
        })
        self.assertEqual(result["sections"][0]["evidence"], [])
        self.assertIn("cleared_section_evidence: 5.1", result["metadata"]["warnings"])

    def test_source_markers_preserved_when_valid_in_section_body(self):
        result = self.service._normalize_deep_research(
            {
                "sections": [{
                    "title": "市场规模与渗透率趋势分析",
                    "summary": "本节摘要",
                    "observation": "2024年销量约950万辆。",
                    "interpretation": "市场增长由补贴退坡后的消费端需求主导，[s1] 市场已进入快速普及阶段。",
                    "implication": "高渗透率会推动竞争从增量转向存量。",
                    "uncertainty": "预测仍受宏观经济影响。",
                    "outlook": "未来市场将从爆发期转向稳健期。",
                    "insight": "增长具有结构性 [s1]。",
                    "content": "",
                    "used_source_ids": ["s1"],
                }],
                "sources": [{"id": "s1", "title": "来源1", "url": "https://a.com", "snippet": "x", "summary": ""}],
            },
            {"requested": True, "enabled": True, "sources": [
                {"id": "s1", "title": "来源1", "url": "https://a.com", "snippet": "x", "summary": ""},
            ]},
        )
        section = result["sections"][0]
        self.assertIn("[s1]", section["interpretation"])
        self.assertEqual(section["used_source_ids"], ["s1"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["metadata"]["source_count"], 1)

    def test_invalid_source_markers_removed_from_section_body(self):
        result = self.service._normalize_deep_research(
            {
                "sections": [{
                    "title": "节",
                    "observation": "事实",
                    "interpretation": "解释 [s9]",
                    "insight": "洞察",
                }],
            },
            {
                "requested": True,
                "enabled": True,
                "sources": [{"id": "s1", "title": "来源1", "url": "", "snippet": "", "summary": ""}],
            },
        )
        section = result["sections"][0]
        self.assertNotIn("[s9]", section["interpretation"])
        self.assertIn("removed_invalid_source_ref:s9", result["metadata"]["warnings"])

    def test_conclusion_extended_fields_are_normalized(self):
        result = self.service._normalize_deep_research({
            "conclusion": {
                "headline": "总判断",
                "problem_analysis": "核心问题",
                "root_causes": "驱动因素",
                "strategic_implications": "战略启示",
                "text": "展望收束",
                "disclaimer": "研究说明",
            }
        })
        c = result["conclusion"]
        self.assertEqual(c["headline"], "总判断")
        self.assertEqual(c["problem_analysis"], "核心问题")
        self.assertEqual(c["text"], "展望收束")
        self.assertEqual(c["disclaimer"], "研究说明")

    def test_outlook_trends_normalized_and_capped(self):
        trends = [
            {"title": f"趋势{i}", "description": f"说明{i}"}
            for i in range(1, 9)
        ]
        result = self.service._normalize_deep_research({"outlook_trends": trends})
        self.assertEqual(len(result["outlook_trends"]), 6)
        self.assertEqual(result["outlook_trends"][0]["id"], "8.1")
        self.assertEqual(result["metadata"]["outlook_trend_count"], 6)
        self.assertIn("truncated_outlook_trends: max_6", result["metadata"]["warnings"])

    def test_recommendations_sorted_by_priority(self):
        result = self.service._normalize_deep_research({
            "recommendations": [
                {"target": "低", "action": "a", "priority": "P2"},
                {"target": "高", "action": "b", "priority": "P0"},
                {"target": "中", "action": "c", "priority": "P1"},
            ]
        })
        priorities = [r["priority"] for r in result["recommendations"]]
        self.assertEqual(priorities, ["P0", "P1", "P2"])

    def test_needs_section_deepening_triggers_for_shallow_sections_even_with_short_input(self):
        sections = [{
            "title": "测试",
            "observation": "事实很少",
            "interpretation": "",
            "implication": "",
            "outlook": "会变化",
            "insight": "结论",
        }]
        self.assertTrue(self.service._needs_section_deepening(sections, "短文本"))

    def test_chat_completion_falls_back_to_curl_on_requests_ssl_error(self):
        completed = Mock()
        completed.returncode = 0
        completed.stdout = '{"choices":[{"message":{"content":"{\\"ok\\": true}"}}]}'
        completed.stderr = ""

        module = importlib.import_module(self.service.__module__)
        with patch.object(module.requests, "post", side_effect=module.requests.exceptions.SSLError("tls eof")), \
             patch.object(module.subprocess, "run", return_value=completed) as run, \
             patch.object(module.settings, "chat_model_request_retries", 1), \
             patch.object(module.settings, "chat_model_curl_fallback", True):
            response = self.service._post_chat_completion(
                "https://api.example.com/v1/chat/completions",
                {"model": "m", "messages": []},
                {"Content-Type": "application/json", "Authorization": "Bearer secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("choices", response.json())
        args = run.call_args.args[0]
        self.assertIn("curl", args[0])
        self.assertIn("Authorization: Bearer secret", args)

    def test_parse_llm_report_json_repairs_truncated_json(self):
        broken = '{"title": {"id": "1", "text": "测试"}, "summary": {"id": "2", "text": "摘要"'
        parsed, flags = self.service._parse_llm_report_json(broken, "输入文本")
        self.assertFalse(flags["degraded"])
        self.assertTrue(flags["partial_recovery"])
        self.assertEqual(parsed["title"]["text"], "测试")

    def test_parse_llm_report_json_degrades_on_total_failure(self):
        parsed, flags = self.service._parse_llm_report_json("not json at all", "用户原文内容")
        self.assertTrue(flags["degraded"])
        self.assertIn("用户原文", parsed["summary"]["text"])

    def test_merge_deepened_sections_locks_summary_and_visual_refs(self):
        original = [{
            "id": "5.1",
            "title": "原标题",
            "summary": "原摘要",
            "visual_refs": ["7.1"],
            "observation": "旧观察",
        }]
        rewritten = [{
            "id": "5.1",
            "title": "新标题",
            "summary": "新摘要",
            "observation": "新观察",
            "interpretation": "新解释",
            "implication": "新影响",
            "uncertainty": "不确定",
            "outlook": "展望",
            "insight": "洞察",
            "visual_refs": ["7.9"],
        }]
        merged = self.service._merge_deepened_sections(original, rewritten)
        self.assertEqual(merged[0]["title"], "原标题")
        self.assertEqual(merged[0]["summary"], "原摘要")
        self.assertEqual(merged[0]["visual_refs"], ["7.1"])
        self.assertEqual(merged[0]["interpretation"], "新解释")

    def test_infer_research_complexity_deep_for_complex_short_topic(self):
        complexity, reason = self.service._infer_research_complexity(
            "请深度分析全球电动车竞争格局、趋势预测与主要风险。",
            {"enabled": True, "sources": [{"id": "s1"}]},
        )
        self.assertEqual(complexity, "deep")
        self.assertTrue(reason)

    def test_infer_research_complexity_simple_for_brief_request(self):
        complexity, _ = self.service._infer_research_complexity("请简要概述人工智能。", {})
        self.assertEqual(complexity, "simple")

    def test_metadata_research_complexity_and_quality_issues_message(self):
        result = self.service._normalize_deep_research(
            {"title": "t", "summary": "s", "metadata": {"research_complexity": "deep", "complexity_reason": "多维分析"}},
            report_flags={"degraded": True, "partial_recovery": False},
            complexity_hint="standard",
            complexity_reason_hint="后端预判",
        )
        self.assertTrue(result["metadata"]["degraded"])
        self.assertEqual(result["metadata"]["research_complexity"], "deep")
        self.assertEqual(result["metadata"]["complexity_reason"], "多维分析")
        self.assertTrue(result["metadata"]["quality_banner"])
        issues = result["metadata"]["quality_issues"]
        self.assertTrue(any(i.get("message") for i in issues))

    def test_used_source_ids_preserved_in_sections_and_charts(self):
        result = self.service._normalize_deep_research(
            {
                "sections": [{
                    "title": "市场",
                    "observation": "增长",
                    "interpretation": "需求驱动",
                    "used_source_ids": ["s1", "s1"],
                }],
                "charts": [{
                    "type": "bar",
                    "data": {"labels": ["A"], "values": [1]},
                    "chart_insight": "洞察",
                    "data_source_refs": ["s1"],
                    "data_notes": "来自搜索摘要",
                }],
            },
            {
                "requested": True,
                "enabled": True,
                "sources": [{"id": "s1", "title": "来源", "url": "", "snippet": "1", "summary": ""}],
            },
        )
        self.assertEqual(result["sections"][0]["used_source_ids"], ["s1"])
        self.assertEqual(result["charts"][0]["data_source_refs"], ["s1"])
        self.assertEqual(result["charts"][0]["data_notes"], "来自搜索摘要")

    def test_orphan_source_markers_removed_without_web_search(self):
        result = self.service._normalize_deep_research({
            "summary": {"text": "摘要含来源 [s1]"},
            "sections": [{"title": "节", "observation": "事实 [s2]", "insight": "洞察"}],
        })
        self.assertIn("removed_orphan_source_markers", result["metadata"]["warnings"])
        self.assertNotIn("[s1]", result["summary"]["text"])

    def test_autofill_structured_source_refs_when_web_search_enabled(self):
        result = self.service._normalize_deep_research(
            {
                "sections": [{"title": "A", "observation": "x", "interpretation": "y"}],
                "charts": [{
                    "type": "bar",
                    "data": {"labels": ["A"], "values": [1]},
                    "chart_insight": "洞察",
                }],
                "key_findings": [{"title": "F", "insight": "I"}],
            },
            {
                "requested": True,
                "enabled": True,
                "sources": [
                    {"id": "s1", "title": "来源1", "url": "", "snippet": "", "summary": ""},
                    {"id": "s2", "title": "来源2", "url": "", "snippet": "", "summary": ""},
                    {"id": "s3", "title": "来源3", "url": "", "snippet": "", "summary": ""},
                ],
            },
        )
        # 新策略：零引用兜底只选一个锚点模块（sections 优先），不再给 findings/charts 机械挂来源
        self.assertEqual(result["sections"][0]["used_source_ids"], ["s1"])
        self.assertEqual(result["key_findings"][0]["used_source_ids"], [])
        self.assertEqual(result["charts"][0]["data_source_refs"], [])
        self.assertIn("low_confidence_refs", result["metadata"]["warnings"])
        self.assertNotIn("web_content_unreferenced", result["metadata"]["warnings"])

        result = self.service._normalize_deep_research(
            {
                "sections": [{
                    "title": "节",
                    "observation": "事实",
                    "interpretation": "解释",
                    "implication": "影响",
                    "insight": "洞察",
                    "used_source_ids": ["s1"],
                }],
            },
            {
                "requested": True,
                "enabled": True,
                "sources": [{"id": "s1", "title": "来源", "url": "", "snippet": "", "summary": ""}],
            },
        )
        self.assertNotIn("web_content_unreferenced", result["metadata"]["warnings"])

    def test_filter_sources_to_cited_only(self):
        web_sources = [
            {"id": f"s{i}", "title": f"来源{i}", "url": f"https://ex.com/{i}", "snippet": f"snippet{i}", "summary": ""}
            for i in range(1, 11)
        ]
        result = self.service._normalize_deep_research(
            {
                "sections": [{
                    "title": "主题",
                    "observation": "观察",
                    "interpretation": "解释一",
                    "implication": "影响一",
                    "outlook": "趋势一",
                    "insight": "洞察",
                }],
                "key_findings": [{"title": "发现", "insight": "说明：要点"}],
                "recommendations": [{"target": "目标", "action": "行动"}],
            },
            {"requested": True, "enabled": True, "sources": web_sources},
        )
        self.assertLessEqual(len(result["sources"]), 3)
        self.assertEqual(result["metadata"]["source_count"], len(result["sources"]))
        self.assertEqual(result["metadata"]["web_search_retrieved_count"], 10)
        self.assertIn("unused_web_sources:", "|".join(result["metadata"]["warnings"]))

    def test_sources_ordered_by_first_appearance_with_cite_no(self):
        web_sources = [
            {"id": "s1", "title": "来源1", "url": "https://ex.com/1", "snippet": "", "summary": ""},
            {"id": "s2", "title": "来源2", "url": "https://ex.com/2", "snippet": "", "summary": ""},
            {"id": "s5", "title": "来源5", "url": "https://ex.com/5", "snippet": "", "summary": ""},
        ]
        result = self.service._normalize_deep_research(
            {
                "sections": [
                    {"title": "A", "observation": "观察", "interpretation": "先引用 [s5]"},
                    {"title": "B", "observation": "观察", "interpretation": "再引用 [s2]"},
                ],
            },
            {"requested": True, "enabled": True, "sources": web_sources},
        )
        self.assertEqual([s["id"] for s in result["sources"]], ["s5", "s2"])
        self.assertEqual([s["cite_no"] for s in result["sources"]], [1, 2])
        self.assertEqual(result["metadata"]["cited_source_count"], 2)

    def test_chart_insight_fallback_when_missing(self):
        result = self.service._normalize_deep_research({
            "charts": [{
                "type": "bar",
                "data": {"labels": ["A"], "values": [1]},
                "interpretation": "解读说明",
            }]
        })
        self.assertEqual(result["charts"][0]["chart_insight"], "解读说明")
        self.assertTrue(any("missing_chart_insight" in w for w in result["metadata"]["warnings"]))

    def test_legacy_recommendation_priority_maps_to_p_labels(self):
        result = self.service._normalize_deep_research({
            "recommendations": [{"target": "目标", "action": "行动", "priority": "high"}]
        })
        self.assertEqual(result["recommendations"][0]["priority"], "P0")

    def test_regression_samples_from_fixtures(self):
        fixtures_path = ROOT / "tests" / "fixtures" / "deep_research_regression_samples.json"
        samples = json.loads(fixtures_path.read_text(encoding="utf-8"))
        web_ctx = {
            "requested": True,
            "enabled": True,
            "sources": samples["web_search_structured_refs"]["sources"],
        }
        for name, payload in samples.items():
            ctx = web_ctx if name == "web_search_structured_refs" else None
            result = self.service._normalize_deep_research(payload, ctx)
            self.assertEqual(result["metadata"]["visualization_type"], "deep_research_webpage")
            self.assertIn("research_complexity", result["metadata"])
        legacy = self.service._normalize_deep_research(samples["legacy_minimal"])
        self.assertEqual(legacy["recommendations"][0]["priority"], "P0")
        self.assertEqual(legacy["sections"][0].get("content", ""), "只有旧 content 字段")

    def test_short_text_with_explicit_data_keeps_chart(self):
        result = self.service._normalize_deep_research(
            {"charts": [{"type": "bar", "data": {"labels": ["A"], "values": [42]}, "chart_insight": "单点数据"}]},
            source_text="市场份额 42%",
            complexity_hint="simple",
        )
        self.assertEqual(len(result["charts"]), 1)
        self.assertIn("data_confidence", result["charts"][0])

    def test_long_text_without_chart_data_stays_empty(self):
        long_text = "这是一段没有明确数字的材料。" * 50
        result = self.service._normalize_deep_research(
            {"charts": [{"type": "pie", "data": {"labels": [], "values": []}}]},
            source_text=long_text,
        )
        self.assertEqual(result["charts"], [])

    def test_model_citations_are_trusted_without_autofill(self):
        """模型已主动引用时，不应再被机械补全到其他模块。"""
        result = self.service._normalize_deep_research(
            {
                "sections": [
                    {"title": "A", "observation": "事实A", "interpretation": "解释A [s1]"},
                    {"title": "B", "observation": "事实B", "interpretation": "解释B"},
                ],
                "key_findings": [{"title": "F", "insight": "说明：要点"}],
            },
            {
                "requested": True,
                "enabled": True,
                "sources": [
                    {"id": "s1", "title": "来源1", "url": "", "snippet": "", "summary": ""},
                    {"id": "s2", "title": "来源2", "url": "", "snippet": "", "summary": ""},
                ],
            },
        )
        # 模型只引用了 s1，第二个 section 与 finding 不应被机械挂来源
        self.assertEqual(result["sections"][0]["used_source_ids"], ["s1"])
        self.assertEqual(result["sections"][1].get("used_source_ids"), [])
        self.assertEqual(result["key_findings"][0].get("used_source_ids"), [])
        self.assertNotIn("low_confidence_refs", result["metadata"]["warnings"])
        self.assertNotIn("auto_assigned_source_refs", result["metadata"]["warnings"])

    def test_zero_citation_fallback_marks_low_confidence(self):
        """全报告零引用时，仅补一个锚点模块并打 low_confidence_refs。"""
        result = self.service._normalize_deep_research(
            {"sections": [{"title": "A", "observation": "事实", "interpretation": "解释"}]},
            {
                "requested": True,
                "enabled": True,
                "sources": [{"id": "s1", "title": "来源1", "url": "", "snippet": "", "summary": ""}],
            },
        )
        self.assertEqual(result["sections"][0]["used_source_ids"], ["s1"])
        self.assertIn("low_confidence_refs", result["metadata"]["warnings"])

    def test_schema_version_present_in_metadata(self):
        result = self.service._normalize_deep_research({"summary": {"text": "x"}})
        self.assertEqual(
            result["metadata"]["schema_version"],
            self.service.DEEP_RESEARCH_SCHEMA_VERSION,
        )

    def test_text_overlap_ratio_detects_paraphrase(self):
        ratio_dup = self.service._text_overlap_ratio(
            "敏捷开发强调迭代交付与持续反馈", "敏捷开发强调迭代交付以及持续反馈"
        )
        ratio_diff = self.service._text_overlap_ratio(
            "市场规模持续扩张", "团队组织结构调整"
        )
        self.assertGreaterEqual(ratio_dup, 0.6)
        self.assertLess(ratio_diff, 0.3)

    def test_complexity_no_double_count_for_single_keyword(self):
        complexity, _ = self.service._infer_research_complexity("请帮我做一个对比")
        self.assertIn(complexity, {"simple", "standard"})
        deep_complexity, _ = self.service._infer_research_complexity(
            "请做深度分析：对比竞争格局与趋势预测"
        )
        self.assertEqual(deep_complexity, "deep")


if __name__ == "__main__":
    unittest.main()
