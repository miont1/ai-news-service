from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import NewsItemCreate
from app.models import NewsItem


class NewsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_existing_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        query = select(NewsItem.id).where(NewsItem.id.in_(ids))
        result = await self.session.execute(query)
        return set(result.scalars().all())

    async def save_news_items(self, items: list[NewsItemCreate]) -> list[NewsItem]:
        if not items:
            return []
        db_items = [NewsItem(**item.model_dump()) for item in items]
        self.session.add_all(db_items)
        await self.session.commit()
        return db_items

    async def get_news(self, limit: int = 50, offset: int = 0) -> list[NewsItem]:
        query = (
            select(NewsItem)
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
