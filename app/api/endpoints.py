from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.exceptions import (
    AIAuthenticationError,
    AIGenerationError,
    AIRateLimitError,
    AIServiceUnavailableError,
)
from app.ai.generator import PostGenerator
from app.api.schemas import (
    GenerateCustomRequest,
    GenerateCustomResponse,
    GenerateFromNewsRequest,
    KeywordCreate,
    KeywordResponse,
    KeywordUpdate,
    NewsFetchRequest,
    NewsFetchResult,
    NewsItemResponse,
    PostPublishRequest,
    PostResponse,
    SourceCreate,
    SourceResponse,
    SourceUpdate,
)
from app.database import get_db
from app.models import Keyword, Source, SourceType, StatusType
from app.repositories import NewsRepository, PostRepository
from app.services import NewsService
from app.telegram.exceptions import (
    PostAlreadyPublishedError,
    PostNotFoundError,
    PostPublishingInProgressError,
    TelegramChannelValidationError,
    TelegramPublishChannelError,
    TelegramPublishError,
    TelegramPublishFloodWaitError,
    TelegramPublishForbiddenError,
    TelegramPublishNetworkError,
    TelegramPublishUnauthorizedError,
)
from app.telegram.publisher import TelegramPublisher

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
    source_type = request.source_type if request else None
    use_ai_filter = request.use_ai_filter if request else None
    top_k = request.top_k if request else None

    if source_type == SourceType.TG:
        limit = request.limit_per_channel if request else 20
        min_length = request.min_text_length if request else 200
        return await service.fetch_and_store_telegram_news(
            limit_per_channel=limit,
            min_text_length=min_length,
            keywords=keywords,
            use_db_keywords=use_db_keywords,
            use_ai_filter=use_ai_filter,
            top_k=top_k,
        )

    return await service.fetch_and_store_site_news(
        keywords=keywords,
        use_db_keywords=use_db_keywords,
        use_ai_filter=use_ai_filter,
        top_k=top_k,
    )


@news_router.post(
    "/news/fetch/telegram",
    response_model=NewsFetchResult,
    status_code=status.HTTP_200_OK,
    tags=["News"],
)
async def fetch_telegram_news(
    db: SessionDep,
    request: NewsFetchRequest | None = None,
):
    service = NewsService(db)
    keywords = request.keywords if request else None
    use_db_keywords = request.use_db_keywords if request else False
    limit = request.limit_per_channel if request else 20
    min_length = request.min_text_length if request else 200
    use_ai_filter = request.use_ai_filter if request else None
    top_k = request.top_k if request else None
    return await service.fetch_and_store_telegram_news(
        limit_per_channel=limit,
        min_text_length=min_length,
        keywords=keywords,
        use_db_keywords=use_db_keywords,
        use_ai_filter=use_ai_filter,
        top_k=top_k,
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


async def _generate_ai_post(
    generator: PostGenerator,
    title: str,
    content: str | None = None,
    summary: str | None = None,
    raw_text: str | None = None,
    source_url: str | None = None,
    custom_prompt: str | None = None,
) -> str:
    try:
        return await generator.generate_post(
            title=title,
            content=content,
            summary=summary,
            raw_text=raw_text,
            source_url=source_url,
            custom_prompt=custom_prompt,
        )
    except AIAuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI Authentication failed: {e}",
        )
    except AIRateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"AI Rate limit reached: {e}",
        )
    except AIServiceUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI Service unavailable: {e}",
        )
    except AIGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI Generation error: {e}",
        )


@news_router.post(
    "/generate/news",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["AI Generation"],
)
async def generate_post_from_news(
    request: GenerateFromNewsRequest,
    db: SessionDep,
):
    news_repo = NewsRepository(db)
    post_repo = PostRepository(db)
    generator = PostGenerator()

    news_item = await news_repo.get_by_id(request.news_id)
    if not news_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NewsItem with id '{request.news_id}' not found",
        )

    # Check if a post for this news item already exists
    existing_post = await post_repo.get_by_news_id(request.news_id)
    if existing_post:
        if existing_post.status == StatusType.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Post for news_id '{request.news_id}' has already been published (post_id={existing_post.id}). Cannot overwrite.",
            )
        if not request.regenerate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Post for news_id '{request.news_id}' already exists "
                    f"(post_id={existing_post.id}, status='{existing_post.status}'). "
                    "Pass regenerate=true to overwrite."
                ),
            )

    generated_text = await _generate_ai_post(
        generator=generator,
        title=news_item.title,
        summary=news_item.summary,
        raw_text=news_item.raw_text,
        source_url=news_item.url,
        custom_prompt=request.custom_prompt,
    )

    if existing_post and request.regenerate:
        return await post_repo.update_generated_text(
            post_id=existing_post.id,
            generated_text=generated_text,
        )

    return await post_repo.create_post(
        news_id=news_item.id,
        generated_text=generated_text,
        status=StatusType.GENERATED,
    )


@news_router.post(
    "/generate/custom",
    response_model=GenerateCustomResponse,
    status_code=status.HTTP_200_OK,
    tags=["AI Generation"],
)
async def generate_post_from_custom(
    request: GenerateCustomRequest,
):
    generator = PostGenerator()
    generated_text = await _generate_ai_post(
        generator=generator,
        title=request.title,
        content=request.content,
        source_url=request.source_url,
        custom_prompt=request.custom_prompt,
    )
    return GenerateCustomResponse(generated_text=generated_text)


@news_router.post(
    "/generate",
    response_model=GenerateCustomResponse,
    status_code=status.HTTP_200_OK,
    tags=["AI Generation"],
    summary="Generate custom Telegram post",
)
async def generate_post(
    request: GenerateCustomRequest,
):
    return await generate_post_from_custom(request)


@news_router.get(
    "/posts",
    response_model=list[PostResponse],
    status_code=status.HTTP_200_OK,
    tags=["Posts"],
)
async def get_posts(
    db: SessionDep,
    post_status: Annotated[StatusType | None, Query(alias="status", description="Filter by status")] = None,
    news_id: Annotated[str | None, Query(description="Filter by news item ID")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Max posts to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip")] = 0,
):
    repo = PostRepository(db)
    return await repo.get_posts(status=post_status, news_id=news_id, limit=limit, offset=offset)


@news_router.get(
    "/posts/{post_id}",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
    tags=["Posts"],
)
async def get_post_by_id(
    post_id: int,
    db: SessionDep,
):
    repo = PostRepository(db)
    post = await repo.get_by_id(post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Post with id {post_id} not found",
        )
    return post


@news_router.post(
    "/posts/{post_id}/publish",
    response_model=PostResponse,
    status_code=status.HTTP_200_OK,
    tags=["Posts"],
    summary="Publish post to Telegram channel",
)
async def publish_post_endpoint(
    post_id: int,
    db: SessionDep,
    request: PostPublishRequest | None = Body(default=None),
):
    publisher = TelegramPublisher(db)
    target_channel = request.target_channel if request else None

    try:
        return await publisher.publish_post(post_id=post_id, target_channel=target_channel)
    except PostNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except (PostAlreadyPublishedError, PostPublishingInProgressError) as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except TelegramChannelValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except TelegramPublishForbiddenError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except TelegramPublishFloodWaitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
        )
    except (
        TelegramPublishChannelError,
        TelegramPublishUnauthorizedError,
        TelegramPublishNetworkError,
        TelegramPublishError,
    ) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )


