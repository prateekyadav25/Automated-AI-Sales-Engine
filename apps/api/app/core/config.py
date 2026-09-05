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
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cookie_secure: bool = False
    cookie_domain: str = ""
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "agrayian"
    s3_secret_key: str = "agrayiansecret"
    s3_bucket: str = "agrayian"
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
    linkedin_access_token: str = ""
    linkedin_ad_account_id: str = ""
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_twiml_url: str = ""
    vapi_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def resolved_llm_provider(self) -> str:
        if self.llm_provider == "openai" and self.openai_api_key:
            return "openai"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
