import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import SourceType


class NewsItemBase(BaseModel):
    title: str = Field(..., max_length=255, description="News title")
    url: str | None = Field(default=None, max_length=1024, description="Source URL")
    summary: str = Field(..., description="News summary")
    source: str = Field(..., max_length=100, description="Source name")
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Published time"
    )
    raw_text: str | None = Field(default=None, description="Full text of article")

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


class NewsFetchResult(BaseModel):
    sources_checked: int = Field(..., description="Number of active sources checked")
    total_found: int = Field(..., description="Total articles found in feeds")
    relevant_matched: int = Field(..., description="Articles matching keyword filters")
    new_saved: int = Field(..., description="New non-duplicate articles saved to DB")
    message: str = Field(..., description="Execution status summary message")
