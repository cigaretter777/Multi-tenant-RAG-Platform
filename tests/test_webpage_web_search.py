import json
import unittest
from unittest.mock import Mock, patch

from services.visualization_service import VisualizationService


MINIMAL_REPORT = {
    "title": {"id": "1", "text": "测试报告"},
    "summary": {"id": "2", "text": "摘要"},
    "kpis": [],
    "research_overview": {
        "id": "3",
        "question": "Q",
        "scope": "S",
        "method": "M",
    },
    "key_findings": [],
    "sections": [],
    "mindmap": {"id": "6", "title": "结构", "nodes": []},
    "charts": [],
    "conclusion": {"id": "8", "text": "结论"},
    "recommendations": [],
    "sources": [],
    "warnings": [],
}


def _mock_chat_response(report: dict):
    body = {"choices": [{"message": {"content": json.dumps(report, ensure_ascii=False)}}]}
    response = Mock()
    response.status_code = 200
    response.text = json.dumps(body)
    response.json.return_value = body
    return response


class WebpageWebSearchIntegrationTest(unittest.TestCase):
    def test_enable_false_does_not_call_search(self):
        mock_search = Mock()
        service = VisualizationService(web_search_service=mock_search)

        with patch("services.visualization_service.requests.post", return_value=_mock_chat_response(MINIMAL_REPORT)) as post:
            result = service.generate_webpage("用户输入", enable_web_search=False)

        mock_search.search.assert_not_called()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result["sources"], [])
        self.assertFalse(result["metadata"]["web_search_requested"])

    def test_enable_true_uses_mock_sources_and_web_prompt(self):
        mock_search = Mock()
        mock_search.search.return_value = {
            "query": "用户输入",
            "provider": "mock",
            "sources": [{
                "id": "s1",
                "title": "Mock Source",
                "url": "https://example.com/mock",
                "snippet": "2026年市场规模100亿元。",
                "summary": "",
            }],
            "answer": "",
            "warnings": [],
        }
        service = VisualizationService(web_search_service=mock_search)

        report_with_section = {
            **MINIMAL_REPORT,
            "sections": [{
                "id": "5.1",
                "title": "分析",
                "observation": "观察内容足够长以满足最小长度校验要求。" * 3,
                "interpretation": "解释内容足够长以满足最小长度校验要求。" * 3,
            }],
        }
        with patch("services.visualization_service.requests.post", return_value=_mock_chat_response(report_with_section)) as post:
            result = service.generate_webpage("用户输入", enable_web_search=True, web_search_count=3)

        mock_search.search.assert_called_once()
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("[s1]", prompt)
        self.assertIn("Mock Source", prompt)
        self.assertEqual(result["sources"][0]["id"], "s1")
        self.assertTrue(result["metadata"]["web_search_enabled"])
        self.assertEqual(result["metadata"]["source_count"], 1)
        self.assertEqual(result["metadata"]["cited_source_count"], 1)
        self.assertEqual(result["metadata"]["web_search_retrieved_count"], 1)

    def test_search_failure_still_returns_report(self):
        mock_search = Mock()
        mock_search.search.return_value = {
            "query": "用户输入",
            "provider": "bocha_internal",
            "sources": [],
            "answer": "",
            "warnings": ["web_search_request_failed"],
        }
        service = VisualizationService(web_search_service=mock_search)

        with patch("services.visualization_service.requests.post", return_value=_mock_chat_response(MINIMAL_REPORT)):
            result = service.generate_webpage("用户输入", enable_web_search=True)

        self.assertEqual(result["sources"], [])
        self.assertFalse(result["metadata"]["web_search_enabled"])
        self.assertTrue(result["metadata"]["web_search_requested"])
        self.assertIn("web_search_request_failed", result["metadata"]["warnings"])

    def test_format_web_context_on_empty_search(self):
        text = VisualizationService._format_web_context_for_prompt({
            "requested": True,
            "query": "新能源",
            "sources": [],
            "answer": "",
            "warnings": ["web_search_empty"],
        })
        self.assertIn("未获得有效来源", text)
        self.assertIn("不要声称使用了 Web Search", text)


if __name__ == "__main__":
    unittest.main()
