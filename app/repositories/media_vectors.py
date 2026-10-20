from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, insert

from app.db.models import Document, MediaVector
from app.repositories.base import Repository


class MediaVectorRepository(Repository[MediaVector]):
    async def replace_for_document(
        self,
        document: Document,
        rows: Sequence[dict[str, Any]],
    ) -> None:
        await self.session.execute(
            delete(MediaVector).where(MediaVector.document_id == document.id),
        )
        if rows:
            await self.session.execute(insert(MediaVector), list(rows))
