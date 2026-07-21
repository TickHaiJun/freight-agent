from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    freight_api_base: str = "https://erp.wecanintl.com/proxy/rewrite"
    no_proxy: str | None = None
    dashscope_api_key: str | None = None
    embedding_model: str = "qwen3-vl-embedding"
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "freight_knowledge"
    rag_enable_vector_search: bool = False
    rag_top_k_vector: int = 8
    rag_top_k_bm25: int = 8
    rag_top_k_final: int = 4
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 100
    rag_enable_rerank: bool = False
    rag_vector_search_timeout_seconds: float = 8.0
    rag_docs_dir: str = "./data/docs"
    # app_log_dir: str = "./docs/history"
    app_log_dir: str = "/data/logs/freight-agent"
    app_log_level: str = "INFO"
    app_log_file_prefix: str = "freight-agent"
    app_log_backup_days: int = 30
    app_log_json_enabled: bool = True
    app_log_debug_state: bool = False
    app_log_service_name: str = "freight-agent"
    chat_feedback_enabled: bool = True
    chat_feedback_dir: str = "./data/feedback"
    chat_feedback_file_prefix: str = "chat-feedback"
    chat_feedback_max_text_length: int = 1000
    chat_feedback_max_answer_length: int = 6000
    chat_feedback_ai_enabled: bool = True
    chat_feedback_ai_timeout_seconds: float = 8.0
    chat_feedback_retention_days: int = 180

    class Config:
        env_file = ".env"


settings = Settings()
