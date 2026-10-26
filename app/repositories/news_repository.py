from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import NewsItemCreate
from app.models import NewsItem, Post


class NewsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_existing_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        query = select(NewsItem.id).where(NewsItem.id.in_(ids))
        result = await self.session.execute(query)
        return set(result.scalars().all())

    async def get_existing_urls(self, urls: list[str]) -> set[str]:
        cleaned_urls = [u for u in urls if u and u.strip()]
        if not cleaned_urls:
            return set()
        query = select(NewsItem.url).where(NewsItem.url.in_(cleaned_urls))
        result = await self.session.execute(query)
        return set(result.scalars().all())


    async def save_news_items(self, items: list[NewsItemCreate]) -> list[NewsItem]:
        if not items:
            return []
        try:
            db_items = [NewsItem(**item.model_dump()) for item in items]
            self.session.add_all(db_items)
            await self.session.commit()
            return db_items
        except IntegrityError:
            await self.session.rollback()
            saved: list[NewsItem] = []
            for item in items:
                try:
                    db_item = NewsItem(**item.model_dump())
                    self.session.add(db_item)
                    await self.session.commit()
                    saved.append(db_item)
                except IntegrityError:
                    await self.session.rollback()
            return saved

    async def get_by_id(self, news_id: str) -> NewsItem | None:
        return await self.session.get(NewsItem, news_id)

    async def get_news(self, limit: int = 50, offset: int = 0) -> list[NewsItem]:
        query = (
            select(NewsItem)
            .order_by(NewsItem.parsed_at.desc(), NewsItem.published_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_unposted_top_news(
        self,
        limit: int = 10,
        exclude_ids: list[str] | set[str] | None = None,
    ) -> list[NewsItem]:
        """Fetch top news from DB that have no corresponding Post, ordered by ai_score descending."""
        query = (
            select(NewsItem)
            .outerjoin(Post, NewsItem.id == Post.news_id)
            .where(Post.id.is_(None))
        )
        if exclude_ids:
            clean_exclude = [eid for eid in exclude_ids if eid]
            if clean_exclude:
                query = query.where(NewsItem.id.not_in(clean_exclude))

        query = (
            query
            .order_by(NewsItem.ai_score.desc().nullslast(), NewsItem.parsed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

