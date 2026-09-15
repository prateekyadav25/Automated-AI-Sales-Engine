from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AGRAYIAN Autonomous Revenue OS"
    environment: str = "development"
    secret_key: str = "dev-only-change-me"
    access_token_ttl_minutes: int = 20
    refresh_token_ttl_days: int = 14
    database_url: str = "sqlite:///./agrayian.db"
    database_admin_url: str = ""
    allow_production_seed: bool = False
    metrics_token: str = ""
    webhook_max_body_bytes: int = 262144
    auth_login_limit: int = 10
    auth_refresh_limit: int = 30
    auth_rate_window_seconds: int = 900
    app_db_password: str = "agrayian"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cookie_secure: bool = False
    cookie_domain: str = ""
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "agrayian"
    s3_secret_key: str = "agrayiansecret"
    s3_bucket: str = "agrayian"
    object_storage_provider: str = "local"
    object_storage_local_root: str = ".object-storage"
    embedding_dimensions: int = 32
    knowledge_max_bytes: int = 1_000_000
    malware_scanner: str = ""
    clamav_endpoint: str = ""
    whatsapp_provider: str = ""
    global_emergency_stop: bool = False
    llm_provider: str = "mock"
    openai_api_key: str = ""
    openai_default_model: str = ""
    openai_reasoning_model: str = ""
    openai_fast_model: str = ""
    openai_embedding_model: str = ""
    seed_demo: bool = True
    apify_api_token: str = ""
    apify_token: str = ""
    apify_actor_id: str = ""
    apify_max_items: int = 10
    apify_linkedin_process_token: str = ""
    discovery_provider: str = "mock"
    linkedin_access_token: str = ""
    linkedin_ad_account_id: str = ""
    linkedin_ads_mode: str = "mock"
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_ads_mode: str = "mock"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_twiml_url: str = ""
    voice_provider: str = "mock"
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""
    vapi_webhook_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/integrations/google/callback"
    email_provider: str = "mock"
    calendar_provider: str = "mock"
    token_encryption_key: str = ""
    integrations_webhook_secret: str = ""
    web_app_origin: str = "http://localhost:3000"
    otel_exporter_otlp_endpoint: str = ""
    approval_ttl_days: int = 7
    ml_min_rows: int = 200
    ml_min_positive: int = 40
    ml_min_negative: int = 40
    ml_min_history_days: int = 90
    ml_max_missingness: float = 0.30
    ml_allow_champion: bool = False
    public_api_base_url: str = "http://localhost:8000"
    exotel_sid: str = ""
    exotel_api_key: str = ""
    exotel_api_token: str = ""
    exotel_caller_id: str = ""
    exotel_subdomain: str = "api.exotel.com"
    exotel_ip_allowlist: str = ""
    recall_api_key: str = ""
    recall_webhook_secret: str = ""
    meeting_capture_provider: str = "mock"
    enrichment_provider: str = "mock"
    enrichment_api_key: str = ""
    enrichment_api_base: str = ""
    ndnc_provider: str = "local"
    voice_conversation_provider: str = "mock"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider == "openai":
            return "openai" if self.openai_api_key else "not_configured"
        return "mock"

    @property
    def resolved_apify_token(self) -> str:
        return self.apify_api_token or self.apify_token

    @property
    def apify_configured(self) -> bool:
        return bool(self.resolved_apify_token and self.apify_actor_id)

    @property
    def linkedin_ads_configured(self) -> bool:
        return bool(self.linkedin_access_token and self.linkedin_ad_account_id)

    @property
    def meta_ads_configured(self) -> bool:
        return bool(self.meta_access_token and self.meta_ad_account_id)

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number and self.twilio_twiml_url)

    @property
    def vapi_configured(self) -> bool:
        return bool(self.vapi_api_key)

    @property
    def exotel_configured(self) -> bool:
        return bool(self.exotel_sid and self.exotel_api_key and self.exotel_api_token and self.exotel_caller_id)

    @property
    def recall_configured(self) -> bool:
        return bool(self.recall_api_key)

    @property
    def enrichment_configured(self) -> bool:
        return bool(self.enrichment_api_key)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key and (self.openai_default_model or self.openai_fast_model))

    @property
    def webhook_inline_process(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def alembic_database_url(self) -> str:
        return self.database_admin_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
