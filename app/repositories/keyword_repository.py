from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword


class KeywordRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_words(self) -> list[str]:
        query = select(Keyword.word)
        result = await self.session.execute(query)
        return [word.strip() for word in result.scalars().all() if word.strip()]
