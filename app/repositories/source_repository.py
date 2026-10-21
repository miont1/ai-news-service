from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceType


class SourceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_sources(self, source_type: SourceType | None = None) -> list[Source]:
        query = select(Source).where(Source.enabled == True)
        if source_type is not None:
            query = query.where(Source.type == source_type)
        result = await self.session.execute(query)
        return list(result.scalars().all())
