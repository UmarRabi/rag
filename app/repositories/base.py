from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class Repository[ModelT: Base]:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity
