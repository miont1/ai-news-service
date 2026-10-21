from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    KeywordCreate,
    KeywordResponse,
    KeywordUpdate,
    NewsFetchRequest,
    NewsFetchResult,
    NewsItemResponse,
    SourceCreate,
    SourceResponse,
    SourceUpdate,
)
from app.database import get_db
from app.models import Keyword, Source
from app.repositories import NewsRepository
from app.services import NewsService

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
    existing = await db.scalar(
        select(Source).where(Source.url == source_in.url)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Source with URL '{source_in.url}' already exists",
        )

    source = Source(**source_in.model_dump())
    db.add(source)
    try:
        await db.commit()
        await db.refresh(source)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source already exists",
        )
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

    if source_in.url is not None:
        existing = await db.scalar(
            select(Source).where(
                Source.url == source_in.url,
                Source.id != source_id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Source with URL '{source_in.url}' already exists",
            )

    for field, value in source_in.model_dump(exclude_unset=True).items():
        setattr(source, field, value)

    try:
        await db.commit()
        await db.refresh(source)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source with this URL already exists",
        )
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
    clean_word = keyword_in.word.strip()
    existing = await db.scalar(
        select(Keyword).where(func.lower(Keyword.word) == clean_word.lower())
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Keyword '{clean_word}' already exists",
        )

    keyword = Keyword(word=clean_word)
    db.add(keyword)
    try:
        await db.commit()
        await db.refresh(keyword)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Keyword '{clean_word}' already exists",
        )
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

    if keyword_in.word is not None:
        clean_word = keyword_in.word.strip()
        existing = await db.scalar(
            select(Keyword).where(
                func.lower(Keyword.word) == clean_word.lower(),
                Keyword.id != keyword_id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Keyword '{clean_word}' already exists",
            )
        keyword.word = clean_word

    for field, value in keyword_in.model_dump(exclude_unset=True).items():
        if field != "word":
            setattr(keyword, field, value)

    try:
        await db.commit()
        await db.refresh(keyword)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Keyword with this word already exists",
        )
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


@news_router.post("/news/fetch", response_model=NewsFetchResult,
    status_code=status.HTTP_200_OK, tags=["News"])
async def fetch_site_news(
    db: SessionDep,
    request: NewsFetchRequest | None = None,
):
    service = NewsService(db)
    keywords = request.keywords if request else None
    use_db_keywords = request.use_db_keywords if request else False
    return await service.fetch_and_store_site_news(
        keywords=keywords,
        use_db_keywords=use_db_keywords,
    )


@news_router.get("/news", response_model=list[NewsItemResponse],
    status_code=status.HTTP_200_OK, tags=["News"])
async def get_news(
    db: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100, description="Max news items to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip")] = 0,
):
    repo = NewsRepository(db)
    return await repo.get_news(limit=limit, offset=offset)