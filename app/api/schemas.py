import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


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