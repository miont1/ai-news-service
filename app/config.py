from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-5-nano"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
    


settings = Settings()