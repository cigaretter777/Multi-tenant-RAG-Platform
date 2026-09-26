import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "services" / "web_search_service.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "bocha_web_search_response.json"


def load_web_search_service():
    spec = importlib.util.spec_from_file_location("web_search_service_under_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WebSearchServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_web_search_service()
        cls.service = cls.module.WebSearchService()

    def test_parse_bocha_sources_and_summary(self):
        raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        result = self.service._parse_bocha_response(raw, "示例市场", "bocha_internal", [])

        self.assertEqual(result["sources"][0]["id"], "s1")
        self.assertEqual(result["sources"][0]["title"], "示例研究来源")
        self.assertIn("100亿元", result["sources"][0]["snippet"])
        self.assertIn("数字化需求", result["answer"])
        self.assertEqual(result["warnings"], [])

    def test_parse_bocha_with_top_level_answer(self):
        fixture_path = ROOT / "tests" / "fixtures" / "bocha_web_search_with_answer.json"
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        result = self.service._parse_bocha_response(raw, "示例市场", "bocha_internal", [])

        self.assertEqual(result["sources"][0]["id"], "s1")
        self.assertIn("120亿元", result["answer"])
        self.assertEqual(result["warnings"], [])

    def test_answer_only_adds_warning(self):
        result = self.service._parse_bocha_response(
            {"code": 200, "answer": "只有搜索总结。"},
            "示例市场",
            "bocha_internal",
            [],
        )

        self.assertEqual(result["sources"], [])
        self.assertEqual(result["answer"], "只有搜索总结。")
        self.assertIn("web_search_no_sources", result["warnings"])

    def test_empty_result_adds_warning(self):
        result = self.service._parse_bocha_response(
            {"code": 200, "data": []},
            "示例市场",
            "bocha_internal",
            [],
        )

        self.assertEqual(result["sources"], [])
        self.assertEqual(result["answer"], "")
        self.assertIn("web_search_empty", result["warnings"])

    def test_disabled_when_server_flag_off(self):
        with patch.object(self.module.settings, "web_search_enabled", False):
            result = self.service.search("测试主题", requested=True)
        self.assertIn("web_search_disabled", result["warnings"])
        self.assertEqual(result["sources"], [])

    def test_web_search_answer_false_payload(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"code": 200, "data": []}

        with patch.object(self.module.settings, "web_search_enabled", True), \
             patch.object(self.module.settings, "web_search_provider", "bocha_internal"), \
             patch.object(self.module.settings, "web_search_url", "http://search.example/web_search"), \
             patch.object(self.module.settings, "web_search_default_count", 3), \
             patch.object(self.module.settings, "web_search_max_count", 5), \
             patch.object(self.module.requests, "post", return_value=response) as post:
            self.service.search("新能源市场分析", count=2, answer=False)

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["count"], 2)
        self.assertFalse(payload["answer"])

    def test_mock_provider_has_no_network(self):
        with patch.object(self.module.settings, "web_search_enabled", True), \
             patch.object(self.module.settings, "web_search_provider", "mock"), \
             patch.object(self.module.requests, "post") as post:
            result = self.service.search("任意主题")

        self.assertFalse(post.called)
        self.assertEqual(result["provider"], "mock")
        self.assertEqual(result["sources"][0]["id"], "s1")

    def test_safe_count_respects_max_ten(self):
        with patch.object(self.module.settings, "web_search_default_count", 3), \
             patch.object(self.module.settings, "web_search_max_count", 10):
            self.assertEqual(self.service._safe_count(10), 10)
            self.assertEqual(self.service._safe_count(15), 10)
            self.assertEqual(self.service._safe_count(None), 3)


if __name__ == "__main__":
    unittest.main()
