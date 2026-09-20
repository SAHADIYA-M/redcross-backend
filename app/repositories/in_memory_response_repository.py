from app.repositories.response_repository import ResponseRepository
from app.response_activity.schemas import ResponseActivity


class InMemoryResponseRepository(ResponseRepository):
    """Temporary repository backed by an in-memory dictionary.

    Replaced by a PostgreSQL-backed repository in a later phase; the interface
    (create/get_by_id/get_all/update) maps directly onto table operations.
    """

    def __init__(self) -> None:
        self._store: dict[str, ResponseActivity] = {}

    def create(self, response: ResponseActivity) -> ResponseActivity:
        self._store[response.response_id] = response
        return response

    def get_by_id(self, response_id: str) -> ResponseActivity | None:
        return self._store.get(response_id)

    def get_all(self) -> list[ResponseActivity]:
        return list(self._store.values())

    def update(
        self, response_id: str, response: ResponseActivity
    ) -> ResponseActivity | None:
        if response_id not in self._store:
            return None
        self._store[response_id] = response
        return response