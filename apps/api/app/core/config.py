import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = os.environ.get("AGRAYIAN_ENV_FILE", ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

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
    gemini_api_key: str = ""
    gemini_default_model: str = ""
    gemini_reasoning_model: str = ""
    gemini_fast_model: str = ""
    gemini_embedding_model: str = ""
    gemini_stt_model: str = ""
    seed_demo: bool = True
    apify_api_token: str = ""
    apify_token: str = ""
    apify_actor_id: str = ""
    apify_max_items: int = 30
    apify_linkedin_process_token: str = ""
    channel_search_provider: str = "auto"
    channel_search_background: bool = False
    google_cse_api_key: str = ""
    google_cse_cx: str = ""
    channel_search_apify_actor: str = "apify/google-search-scraper"
    discovery_provider: str = "mock"
    linkedin_access_token: str = ""
    linkedin_ad_account_id: str = ""
    linkedin_ads_mode: str = "mock"
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_sandbox_ad_account_id: str = ""
    meta_ads_mode: str = "mock"
    linkedin_posting_mode: str = "mock"
    linkedin_post_access_token: str = ""
    linkedin_organization_id: str = ""
    meta_posting_mode: str = "mock"
    meta_page_id: str = ""
    meta_page_access_token: str = ""
    meta_app_secret: str = ""
    meta_webhook_verify_token: str = ""
    meta_lead_access_token: str = ""
    instagram_business_account_id: str = ""
    meta_app_id: str = ""
    meta_graph_api_version: str = "v26.0"
    social_growth_publish_mode: str = "disabled"
    social_growth_insights_mode: str = "disabled"
    social_growth_brand_fetch_mode: str = "live"
    social_growth_max_pages: int = 12
    social_growth_reel_max_seconds: int = 90
    social_growth_carousel_max: int = 10
    social_growth_instagram_daily_limit: int = 50
    ga4_mode: str = "disabled"
    gemini_image_model: str = ""
    creative_font_path: str = ""
    creative_font_bold_path: str = ""
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    youtube_api_key: str = ""
    youtube_channel_id: str = ""
    x_api_key: str = ""
    x_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    google_ads_developer_token: str = ""
    google_ads_customer_id: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_twiml_url: str = ""
    voice_provider: str = "mock"
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""
    vapi_webhook_secret: str = ""
    dograh_api_base: str = ""
    dograh_api_key: str = ""
    dograh_agent_uuid: str = ""
    dograh_ui_base: str = ""
    dograh_embed_token: str = ""
    dograh_chat_embed_token: str = ""
    dograh_widget_environment: str = ""
    dograh_voice_widget_src: str = ""
    dograh_chat_widget_src: str = ""
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
        name = (self.llm_provider or "").strip().lower()
        if name == "gemini":
            return "gemini" if self.gemini_api_key else "not_configured"
        if name == "mock":
            return "mock"
        return "not_configured"

    @property
    def resolved_apify_token(self) -> str:
        return self.apify_api_token or self.apify_token

    @property
    def apify_configured(self) -> bool:
        return bool(self.resolved_apify_token and self.apify_actor_id)

    @property
    def resolved_channel_search_provider(self) -> str:
        choice = (self.channel_search_provider or "auto").strip().lower()
        cse_ready = bool(self.google_cse_api_key.strip() and self.google_cse_cx.strip())
        apify_ready = bool(self.resolved_apify_token.strip())
        if choice == "google_cse":
            return "google_cse" if cse_ready else "not_configured"
        if choice == "apify":
            return "apify" if apify_ready else "not_configured"
        if choice == "gemini":
            return "gemini" if self.gemini_configured else "not_configured"
        if choice == "auto":
            if cse_ready:
                return "google_cse"
            if apify_ready:
                return "apify"
            if self.gemini_configured:
                return "gemini"
        return "not_configured"

    @property
    def linkedin_ads_configured(self) -> bool:
        return bool(self.linkedin_access_token and self.linkedin_ad_account_id)

    @property
    def meta_ads_token(self) -> str:
        return self.meta_access_token.strip()

    @property
    def resolved_meta_ad_account_id(self) -> str:
        sandbox = self.meta_sandbox_ad_account_id.strip()
        primary = self.meta_ad_account_id.strip()
        if (self.meta_ads_mode or "").strip().lower() == "sandbox" and sandbox:
            return sandbox
        return primary or sandbox

    @property
    def meta_ads_configured(self) -> bool:
        return bool(self.meta_ads_token and self.resolved_meta_ad_account_id)

    @property
    def linkedin_posting_configured(self) -> bool:
        return bool(self.linkedin_post_access_token and self.linkedin_organization_id)

    @property
    def meta_page_posting_configured(self) -> bool:
        return bool(self.meta_page_id and self.meta_page_access_token)

    @property
    def instagram_posting_configured(self) -> bool:
        return bool(self.meta_page_posting_configured and self.instagram_business_account_id)

    @property
    def youtube_configured(self) -> bool:
        return bool(self.youtube_api_key.strip() and self.youtube_channel_id.strip())

    @property
    def x_configured(self) -> bool:
        return bool(self.x_api_key.strip() and self.x_access_token.strip())

    @property
    def whatsapp_configured(self) -> bool:
        return bool(self.whatsapp_phone_number_id.strip() and self.whatsapp_access_token.strip())

    @property
    def google_ads_configured(self) -> bool:
        return bool(self.google_ads_developer_token.strip() and self.google_ads_customer_id.strip())

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number and self.twilio_twiml_url)

    @property
    def vapi_configured(self) -> bool:
        return bool(self.vapi_api_key)

    @property
    def dograh_configured(self) -> bool:
        return bool(self.dograh_api_base.strip() and self.dograh_api_key.strip() and self.dograh_agent_uuid.strip())

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
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key and (self.gemini_default_model or self.gemini_fast_model))

    @property
    def gemini_stt_configured(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_stt_model)

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
