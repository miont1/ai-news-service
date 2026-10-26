from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Post, StatusType


class PostRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_post(
        self,
        news_id: str,
        generated_text: str,
        status: StatusType = StatusType.GENERATED,
    ) -> Post:
        post = Post(
            news_id=news_id,
            generated_text=generated_text,
            status=status,
            published_at=None,
        )
        self.session.add(post)
        await self.session.commit()
        await self.session.refresh(post)
        return post

    async def acquire_publishing_lock(
        self,
        post_id: int,
        allowed_statuses: tuple[StatusType, ...] = (
            StatusType.NEW,
            StatusType.GENERATED,
            StatusType.FAILED,
        ),
    ) -> Post | None:
        """Atomically transition a post to PUBLISHING status if it is in an allowed status.

        Uses atomic `UPDATE ... WHERE id = :post_id AND status IN (...) RETURNING *`.
        Returns the updated Post instance if the lock was acquired, or None if the post
        was not found or was in an incompatible status (e.g. PUBLISHED or PUBLISHING).
        """
        stmt = (
            update(Post)
            .where(Post.id == post_id, Post.status.in_(allowed_statuses))
            .values(status=StatusType.PUBLISHING)
            .returning(Post)
        )
        result = await self.session.execute(stmt)
        post = result.scalar_one_or_none()
        if post:
            await self.session.commit()
            return post
        return None

    async def get_by_id(self, post_id: int) -> Post | None:
        return await self.session.get(Post, post_id)

    async def get_by_news_id(self, news_id: str) -> Post | None:
        query = (
            select(Post)
            .where(Post.news_id == news_id)
            .order_by(Post.id.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def update_generated_text(
        self,
        post_id: int,
        generated_text: str,
    ) -> Post | None:
        post = await self.get_by_id(post_id)
        if not post:
            return None
        post.generated_text = generated_text
        post.status = StatusType.GENERATED
        await self.session.commit()
        await self.session.refresh(post)
        return post

    async def get_posts(
        self,
        status: StatusType | None = None,
        news_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Post]:
        query = select(Post).order_by(Post.id.desc()).limit(limit).offset(offset)
        if status is not None:
            query = query.where(Post.status == status)
        if news_id is not None:
            query = query.where(Post.news_id == news_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_status(
        self,
        post_id: int,
        status: StatusType,
        published_at: datetime | None = None,
    ) -> Post | None:
        post = await self.get_by_id(post_id)
        if not post:
            return None
        post.status = status
        if status == StatusType.PUBLISHED and published_at is None:
            post.published_at = datetime.now(UTC)
        elif published_at is not None:
            post.published_at = published_at
        await self.session.commit()
        await self.session.refresh(post)
        return post
