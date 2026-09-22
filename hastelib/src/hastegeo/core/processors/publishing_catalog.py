import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TypedDict

from ..models.publishing import PublishStatus, PublishTarget
from ..publishing.repository import PublishingRepository
from ..utils.async_cache import AsyncTTLCache


@dataclass(frozen=True)
class CatalogQuery:
    page: int = 1
    page_size: int = 20
    project_id: str | None = None
    target: PublishTarget | None = None
    status: PublishStatus | None = None
    search: str = ""
    sort_key: str = "publishedDate"
    sort_direction: str = "desc"

    def cache_key(self, caller_id: str) -> tuple:
        return (
            caller_id.lower(),
            self.page,
            self.page_size,
            self.project_id or "",
            self.target.value if self.target else "",
            self.status.value if self.status else "",
            self.search.lower(),
            self.sort_key,
            self.sort_direction,
        )


class CatalogRepresentation(TypedDict):
    payload: str
    etag: str


class PublishingCatalogProcessor:
    def __init__(
        self,
        repository_factory: Callable[[], PublishingRepository],
        cache: AsyncTTLCache[tuple, CatalogRepresentation],
    ) -> None:
        self.repository_factory = repository_factory
        self.cache = cache

    async def load(
        self,
        caller_id: str,
        query: CatalogQuery,
        refresh: bool = False,
    ) -> tuple[CatalogRepresentation, bool]:
        async def load_response() -> CatalogRepresentation:
            records, total_count = await asyncio.to_thread(
                self.repository_factory().list_page, **asdict(query)
            )
            payload = json.dumps(
                {
                    "publishedDatasets": [
                        record.model_dump(mode="json") for record in records
                    ],
                    "pagination": {
                        "page": query.page,
                        "pageSize": query.page_size,
                        "totalCount": total_count,
                    },
                }
            )
            return {
                "payload": payload,
                "etag": '"'
                + hashlib.sha256(payload.encode()).hexdigest()[:32]
                + '"',
            }

        return await self.cache.get_or_create(
            query.cache_key(caller_id),
            load_response,
            refresh=refresh,
        )
