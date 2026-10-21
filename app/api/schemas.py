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
    name: str = Field(..., max_length=100, description="Source name")
    url: str = Field(..., max_length=255, description="Source URL",
     examples=["https://www.example.com/rss"])
    enabled: bool = Field(default=True, description="Source enabled")

class SourceCreate(SourcesBase):
    pass

class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    type: SourceType | None = Field(default=None)
    url: str | None = Field(default=None, max_length=255)
    enabled: bool | None = Field(default=None)


class SourceResponse(SourcesBase):
    id: int

    model_config = {
        "from_attributes": True
    }

class KeywordsBase(BaseModel):
    word: str = Field(..., max_length=50, description="Keyword")

class KeywordCreate(KeywordsBase):
    pass

class KeywordUpdate(BaseModel):
    word: str | None = Field(default=None, max_length=50)

class KeywordResponse(KeywordsBase):
    id: int

    model_config = {
        "from_attributes": True
    }


class NewsFetchResult(BaseModel):
    sources_checked: int = Field(..., description="Number of active sources checked")
    total_found: int = Field(..., description="Total articles found in feeds")
    relevant_matched: int = Field(..., description="Articles matching keyword filters")
    new_saved: int = Field(..., description="New non-duplicate articles saved to DB")
    message: str = Field(..., description="Execution status summary message")