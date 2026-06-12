import unittest
from unittest.mock import patch

from rag.service import run_rag_pipeline


class RagServiceTests(unittest.TestCase):
    @patch("rag.service.generate_answer")
    @patch("rag.service.hybrid_retrieve")
    @patch("rag.service.analyze_query")
    def test_pipeline_returns_intermediate_state(self, mock_analyze, mock_retrieve, mock_answer):
        mock_analyze.return_value = {"query": "锂电池 声明 文件", "filters": {"category": "dangerous_goods"}}
        mock_retrieve.return_value = [{"page_content": "doc", "metadata": {"source_file": "a.doc"}}]
        mock_answer.return_value = "answer"

        result = run_rag_pipeline("锂电池货物需要什么声明文件？")

        self.assertEqual(result["retrieval_query"], "锂电池 声明 文件")
        self.assertEqual(result["retrieval_filters"], {"category": "dangerous_goods"})
        self.assertEqual(result["rag_answer"], "answer")


if __name__ == "__main__":
    unittest.main()
