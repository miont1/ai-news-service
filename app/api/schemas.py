import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import SourceType, StatusType


class NewsItemBase(BaseModel):
    title: str = Field(..., max_length=255, description="News title")
    url: str | None = Field(default=None, max_length=1024, description="Source URL")
    summary: str = Field(..., description="News summary")
    source: str = Field(..., max_length=100, description="Source name")
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Published time"
    )
    parsed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Time when the news was parsed/collected"
    )
    raw_text: str | None = Field(default=None, description="Full text of article")
    ai_score: float | None = Field(default=None, description="AI relevance score (1.0 to 10.0)")
    ai_reason: str | None = Field(default=None, description="AI ranking reason/justification")

class NewsItemCreate(NewsItemBase):
    id: str | None = Field(default=None, description="News ID")

    @field_validator("title", "summary", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            return " ".join(v.strip().split())
        return v

    @model_validator(mode="after")
    def generate_id_if_missing(self) -> NewsItemCreate:
        if self.id is None:
            combined = f"{self.title}:{self.summary}:{self.url}".encode()
            self.id = hashlib.sha256(combined).hexdigest()
        return self


class NewsItemResponse(NewsItemBase):
    id: str

    model_config = {
        "from_attributes": True
    }

class SourcesBase(BaseModel):
    type: SourceType = Field(..., description="Source type")
    name: str = Field(..., min_length=1, max_length=100, description="Source name")
    url: str = Field(..., min_length=1, max_length=255, description="Source URL",
     examples=["https://www.example.com/rss"])
    enabled: bool = Field(default=True, description="Source enabled")


class SourceCreate(SourcesBase):
    @field_validator("name", "url", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Field cannot be empty or whitespace only")
            return cleaned
        return v


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: SourceType | None = Field(default=None)
    url: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = Field(default=None)

    @field_validator("name", "url", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Field cannot be empty or whitespace only")
            return cleaned
        return v


class SourceResponse(SourcesBase):
    id: int

    model_config = {
        "from_attributes": True
    }


class KeywordsBase(BaseModel):
    word: str = Field(..., min_length=1, max_length=50, description="Keyword")


class KeywordCreate(KeywordsBase):
    @field_validator("word", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            cleaned = " ".join(v.strip().split())
            if not cleaned:
                raise ValueError("Keyword cannot be empty or whitespace only")
            return cleaned
        return v


class KeywordUpdate(BaseModel):
    word: str | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("word", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            cleaned = " ".join(v.strip().split())
            if not cleaned:
                raise ValueError("Keyword cannot be empty or whitespace only")
            return cleaned
        return v

class KeywordResponse(KeywordsBase):
    id: int

    model_config = {
        "from_attributes": True
    }


class NewsFetchRequest(BaseModel):
    use_db_keywords: bool = Field(
        default=False,
        description="If True, takes precedence and filters exclusively by keywords stored in the database.",
    )
    keywords: list[str] | None = Field(
        default=None,
        description="List of keywords to filter by when use_db_keywords is False. If omitted and use_db_keywords is False, all news are fetched without keyword filtering.",
    )
    source_type: SourceType | None = Field(
        default=None,
        description="Optional source type filter ('site' or 'tg'). If omitted, defaults to site for /news/fetch.",
    )
    limit_per_channel: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max messages to fetch per Telegram channel.",
    )
    min_text_length: int = Field(
        default=200,
        ge=0,
        description="Minimum text length in characters (excluding URLs) for Telegram news items.",
    )
    use_ai_filter: bool | None = Field(
        default=None,
        description="Optional override to enable/disable AI ranking of breaking news. Defaults to settings.AI_FILTER_ENABLED.",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Number of top AI-ranked news items to keep and save. Defaults to settings.AI_FILTER_TOP_K (3).",
    )


class FailedSourceInfo(BaseModel):
    source_name: str = Field(..., description="Name of the failed source")
    url: str = Field(..., description="URL of the failed source")
    error: str = Field(..., description="Failure reason or error description")


class NewsFetchResult(BaseModel):
    sources_checked: int = Field(..., description="Number of active sources checked")
    sources_failed: int = Field(default=0, description="Number of sources that failed to fetch")
    total_found: int = Field(..., description="Total articles found in feeds")
    relevant_matched: int = Field(..., description="Articles matching keyword filters")
    new_saved: int = Field(..., description="New non-duplicate articles saved to DB")
    failed_sources: list[FailedSourceInfo] = Field(
        default_factory=list,
        description="List of sources that encountered errors during fetch",
    )
    message: str = Field(..., description="Execution status summary message")



class PostResponse(BaseModel):
    id: int
    news_id: str
    generated_text: str
    published_at: datetime | None = None
    status: StatusType

    model_config = {
        "from_attributes": True
    }


class PostPublishRequest(BaseModel):
    target_channel: str | None = Field(
        default=None,
        description="Optional target Telegram channel username (@channel) or numeric ID (-100...). If omitted, uses TG_TARGET_CHANNEL from settings.",
        examples=["@my_news_channel"],
    )

    @field_validator("target_channel", mode="before")
    @classmethod
    def clean_target_channel(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            cleaned = v.strip()
            return cleaned if cleaned else None
        return v


class GenerateFromNewsRequest(BaseModel):
    news_id: str = Field(
        ...,
        min_length=1,
        description="ID of existing news item in database to generate post for.",
    )
    custom_prompt: str | None = Field(
        default=None,
        description="Optional custom system prompt to override default prompt.",
    )
    regenerate: bool = Field(
        default=False,
        description="If True, allows regenerating and updating an existing unpublished post.",
    )



class GenerateCustomRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Title of the news or message.",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Content or summary to generate post from.",
    )
    source_url: str | None = Field(
        default=None,
        max_length=1024,
        description="Optional source URL.",
    )
    custom_prompt: str | None = Field(
        default=None,
        description="Optional custom system prompt to override default prompt.",
    )


class GenerateCustomResponse(BaseModel):
    generated_text: str = Field(
        ...,
        description="AI-generated post content.",
    )
