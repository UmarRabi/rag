from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, insert

from app.db.models import Chunk, Document
from app.repositories.base import Repository


class ChunkRepository(Repository[Chunk]):
    async def replace_for_document(
        self,
        document: Document,
        rows: Sequence[dict[str, Any]],
    ) -> None:
        await self.session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        if rows:
            await self.session.execute(insert(Chunk), list(rows))
