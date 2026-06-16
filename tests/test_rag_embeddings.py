import types
import unittest
from unittest.mock import patch

from rag import embeddings


class RagEmbeddingsTests(unittest.TestCase):
    def test_multimodal_model_uses_native_multimodal_api(self):
        captured = {}

        class FakeMultiModalEmbedding:
            @staticmethod
            def call(model, input):
                captured["model"] = model
                captured["input"] = input
                return {
                    "status_code": 200,
                    "output": {
                        "embeddings": [
                            {"embedding": [0.1, 0.2], "text_index": 0},
                            {"embedding": [0.3, 0.4], "text_index": 1},
                        ]
                    },
                }

        fake_dashscope = types.SimpleNamespace(
            api_key=None,
            MultiModalEmbedding=FakeMultiModalEmbedding,
            TextEmbedding=None,
        )

        with patch.object(embeddings.settings, "dashscope_api_key", "test-key"):
            with patch.object(embeddings.settings, "embedding_model", "qwen3-vl-embedding"):
                with patch("rag.embeddings.importlib.import_module", return_value=fake_dashscope):
                    vectors = embeddings.embed_documents(["第一段", "第二段"])

        self.assertEqual(captured["model"], "qwen3-vl-embedding")
        self.assertEqual(captured["input"], [{"text": "第一段"}, {"text": "第二段"}])
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])

    def test_text_model_uses_native_text_embedding_api(self):
        captured = {}

        class FakeTextEmbedding:
            @staticmethod
            def call(model, input):
                captured["model"] = model
                captured["input"] = input
                return {
                    "status_code": 200,
                    "output": {
                        "embeddings": [
                            {"embedding": [1.0, 2.0], "text_index": 0},
                        ]
                    },
                }

        fake_dashscope = types.SimpleNamespace(
            api_key=None,
            MultiModalEmbedding=None,
            TextEmbedding=FakeTextEmbedding,
        )

        with patch.object(embeddings.settings, "dashscope_api_key", "test-key"):
            with patch.object(embeddings.settings, "embedding_model", "text-embedding-v4"):
                with patch("rag.embeddings.importlib.import_module", return_value=fake_dashscope):
                    vector = embeddings.embed_query("测试问题")

        self.assertEqual(captured["model"], "text-embedding-v4")
        self.assertEqual(captured["input"], ["测试问题"])
        self.assertEqual(vector, [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
