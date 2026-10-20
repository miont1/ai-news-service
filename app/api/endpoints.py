from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    KeywordCreate,
    KeywordResponse,
    KeywordUpdate,
    SourceCreate,
    SourceResponse,
    SourceUpdate,
)
from app.database import get_db
from app.models import Keyword, Source

news_router = APIRouter(
    prefix="/api",
)

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@news_router.get("/sources", response_model=list[SourceResponse],
    status_code=status.HTTP_200_OK, tags=["Sources"])
async def get_sources(
    db: SessionDep
):
    query = select(Source).order_by(Source.id)
    result = await db.execute(query)
    return result.scalars().all()

@news_router.post("/sources", response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED, tags=["Sources"])
async def create_source(
    source_in: SourceCreate,
    db: SessionDep
):
    source = Source(**source_in.model_dump())
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source

@news_router.put("/sources/{source_id}", response_model=SourceResponse,
    status_code=status.HTTP_200_OK, tags=["Sources"])
async def update_source(
    source_id: int,
    source_in: SourceUpdate,
    db: SessionDep
):
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
        detail="Source not found")
    for field, value in source_in.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return source

@news_router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Sources"])
async def delete_source(
    source_id: int,
    db: SessionDep
):
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    await db.delete(source)
    await db.commit()

@news_router.get("/keywords", response_model=list[KeywordResponse],
    status_code=status.HTTP_200_OK, tags=["Keywords"])
async def get_keywords(
    db: SessionDep
):
    query = select(Keyword).order_by(Keyword.id)
    result = await db.execute(query)
    return result.scalars().all()

@news_router.post("/keywords", response_model=KeywordResponse,
    status_code=status.HTTP_201_CREATED, tags=["Keywords"])
async def create_keyword(
    keyword_in: KeywordCreate,
    db: SessionDep
):
    keyword = Keyword(**keyword_in.model_dump())
    db.add(keyword)
    await db.commit()
    await db.refresh(keyword)
    return keyword

@news_router.put("/keywords/{keyword_id}", response_model=KeywordResponse,
    status_code=status.HTTP_200_OK, tags=["Keywords"])
async def update_keyword(
    keyword_id: int,
    keyword_in: KeywordUpdate,
    db: SessionDep
):
    keyword = await db.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
        detail="Keyword not found")
    for field, value in keyword_in.model_dump(exclude_unset=True).items():
        setattr(keyword, field, value)
    await db.commit()
    await db.refresh(keyword)
    return keyword

@news_router.delete("/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Keywords"])
async def delete_keyword(
    keyword_id: int,
    db: SessionDep
):
    keyword = await db.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")
    await db.delete(keyword)
    await db.commit()