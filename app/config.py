from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-5-nano"

    # Telegram
    TG_API_ID: int | None = None
    TG_API_HASH: str | None = None
    TG_SESSION_NAME: str = "aibot_session"
    TG_SESSION_STRING: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
    


settings = Settings()