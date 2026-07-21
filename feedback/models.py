"""聊天反馈接口与落盘数据使用的 Pydantic 模型。"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DissatisfactionType(str, Enum):
    INCORRECT_ANSWER = "incorrect_answer"
    INCOMPLETE_ANSWER = "incomplete_answer"
    MISUNDERSTOOD_QUESTION = "misunderstood_question"
    QUOTE_RESULT_ISSUE = "quote_result_issue"
    CLARIFICATION_ISSUE = "clarification_issue"
    KNOWLEDGE_ISSUE = "knowledge_issue"
    SLOW_RESPONSE = "slow_response"
    DISPLAY_ISSUE = "display_issue"
    OTHER = "other"


class BusinessDomain(str, Enum):
    RATE_QUERY = "rate_query"
    RAG = "rag"
    SUPPORT_INFO = "support_info"
    UNKNOWN = "unknown"
    MIXED = "mixed"


class PipelineStage(str, Enum):
    INTENT_CLASSIFICATION = "intent_classification"
    SLOT_EXTRACTION = "slot_extraction"
    CLARIFICATION = "clarification"
    FREIGHT_TOOL = "freight_tool"
    RESULT_GENERATION = "result_generation"
    RAG_RETRIEVAL = "rag_retrieval"
    RAG_GENERATION = "rag_generation"
    FRONTEND_DISPLAY = "frontend_display"
    UNKNOWN = "unknown"


class QualityTag(str, Enum):
    WRONG_ANSWER = "wrong_answer"
    MISSING_INFORMATION = "missing_information"
    MISUNDERSTANDING = "misunderstanding"
    TOOL_OR_DATA_ISSUE = "tool_or_data_issue"
    KNOWLEDGE_GAP = "knowledge_gap"
    LATENCY = "latency"
    DISPLAY_ISSUE = "display_issue"
    POLICY_OR_PROMPT_GAP = "policy_or_prompt_gap"
    NOT_REPRODUCIBLE = "not_reproducible"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChatFeedbackRequest(BaseModel):
    """前端提交的最小反馈数据；禁止接收未约定字段。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    feedback_text: str = Field(min_length=5, max_length=1000)
    dissatisfaction_types: list[DissatisfactionType] = Field(min_length=1, max_length=9)
    user_question: str = Field(min_length=1, max_length=2000)
    assistant_answer: str = Field(min_length=1, max_length=6000)
    conversation_excerpt: list[str] | None = Field(default=None, max_length=3)
    allow_context_for_review: bool = True

    @field_validator("session_id", "request_id", "feedback_text", "user_question", "assistant_answer")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("conversation_excerpt")
    @classmethod
    def validate_excerpt(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item and item.strip()]
        if sum(len(item) for item in cleaned) > 6000:
            raise ValueError("conversation_excerpt 总长度不能超过 6000 字符")
        return cleaned

    @model_validator(mode="after")
    def deduplicate_types(self) -> "ChatFeedbackRequest":
        # 多选值重复没有业务意义，服务端统一去重以稳定后续统计口径。
        self.dissatisfaction_types = list(dict.fromkeys(self.dissatisfaction_types))
        return self


class FeedbackAiAnalysis(BaseModel):
    """模型成功归因时允许写入的严格结构。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    quality_tags: list[QualityTag] = Field(min_length=1, max_length=3)
    business_domain: BusinessDomain
    pipeline_stage: PipelineStage
    root_cause_hypothesis: str = Field(min_length=1, max_length=500)
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    recommended_action: str = Field(min_length=1, max_length=500)
    needs_human_review: bool


class ChatFeedbackResponse(BaseModel):
    feedback_id: str
    status: str = "accepted"
    ai_analysis_status: str
