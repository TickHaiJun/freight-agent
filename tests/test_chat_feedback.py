import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import settings
from feedback.models import (
    BusinessDomain,
    ChatFeedbackRequest,
    FeedbackAiAnalysis,
    PipelineStage,
    QualityTag,
    Severity,
)
from feedback.service import submit_feedback
from feedback.store import FeedbackStore
from pydantic import ValidationError


def build_request(**overrides) -> ChatFeedbackRequest:
    data = {
        "session_id": "session_test",
        "request_id": "req_test",
        "feedback_text": "回答没有说明含电池货物的处理方式。",
        "dissatisfaction_types": ["incomplete_answer"],
        "user_question": "锂电池货物怎么订舱？",
        "assistant_answer": "请按普货流程处理。",
        "conversation_excerpt": ["上一轮：货物含锂电池"],
        "allow_context_for_review": True,
    }
    data.update(overrides)
    return ChatFeedbackRequest.model_validate(data)


def build_analysis() -> FeedbackAiAnalysis:
    return FeedbackAiAnalysis(
        summary="回答遗漏了含电池货物的处理说明。",
        quality_tags=[QualityTag.MISSING_INFORMATION],
        business_domain=BusinessDomain.RATE_QUERY,
        pipeline_stage=PipelineStage.RESULT_GENERATION,
        root_cause_hypothesis="可能需要复核结果生成提示词覆盖范围。",
        severity=Severity.MEDIUM,
        confidence=0.8,
        recommended_action="需复核关联请求与结果生成提示词。",
        needs_human_review=True,
    )


class ChatFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_app_log_dir = settings.app_log_dir
        self.original_feedback_dir = settings.chat_feedback_dir
        self.original_ai_enabled = settings.chat_feedback_ai_enabled
        settings.app_log_dir = self.temp_dir.name
        settings.chat_feedback_dir = self.temp_dir.name
        settings.chat_feedback_ai_enabled = True

    def tearDown(self):
        settings.app_log_dir = self.original_app_log_dir
        settings.chat_feedback_dir = self.original_feedback_dir
        settings.chat_feedback_ai_enabled = self.original_ai_enabled
        self.temp_dir.cleanup()

    def test_submit_saves_raw_and_enrichment_events(self):
        store = FeedbackStore(self.temp_dir.name)
        with patch("feedback.service.analyze_feedback", return_value=build_analysis()):
            response = asyncio.run(submit_feedback(build_request(), store))

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.ai_analysis_status, "completed")
        events = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["record_type"] for event in events], ["feedback", "feedback_enrichment"])
        self.assertEqual(events[0]["feedback_id"], response.feedback_id)
        self.assertEqual(events[1]["ai_analysis"]["severity"], "medium")

    def test_ai_failure_keeps_original_feedback(self):
        store = FeedbackStore(self.temp_dir.name)
        with patch("feedback.service.analyze_feedback", side_effect=TimeoutError("model timeout")):
            response = asyncio.run(submit_feedback(build_request(), store))

        self.assertEqual(response.ai_analysis_status, "failed")
        events = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[0]["record_type"], "feedback")
        self.assertEqual(events[1]["ai_analysis"]["status"], "failed")

    def test_context_is_not_saved_without_authorization(self):
        store = FeedbackStore(self.temp_dir.name)
        with patch("feedback.service.analyze_feedback", return_value=build_analysis()):
            asyncio.run(submit_feedback(build_request(allow_context_for_review=False), store))

        event = json.loads(store.path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(event["conversation_snapshot"], {"context_available_for_review": False})

    def test_request_rejects_removed_or_unknown_fields(self):
        with self.assertRaises(ValidationError):
            build_request(page_url="https://example.test")

    def test_trace_summary_reads_existing_application_jsonl(self):
        log_path = Path(self.temp_dir.name) / f"{settings.app_log_file_prefix}-app.jsonl"
        log_path.write_text(
            json.dumps({"event": "agent_finished", "request_id": "req_trace", "intent": "rag", "query_ready": True})
            + "\n"
            + json.dumps({"event": "request_completed", "request_id": "req_trace", "total_elapsed_ms": 123.4})
            + "\n",
            encoding="utf-8",
        )
        trace = FeedbackStore(self.temp_dir.name).find_request_trace("req_trace")

        self.assertTrue(trace["trace_found"])
        self.assertEqual(trace["intent"], "rag")
        self.assertEqual(trace["total_elapsed_ms"], 123.4)


if __name__ == "__main__":
    unittest.main()
