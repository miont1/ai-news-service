from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-5-nano"
    AI_FILTER_ENABLED: bool = True
    AI_FILTER_TOP_K: int = 3

    # Telegram
    TG_API_ID: int | None = None
    TG_API_HASH: str | None = None
    TG_SESSION_NAME: str = "aibot_session"
    TG_SESSION_STRING: str | None = None
    TG_TARGET_CHANNEL: str | None = None

    # Celery & RabbitMQ
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    CELERY_RESULT_BACKEND: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
    


settings = Settings()