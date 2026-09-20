import abc
from app.models.fusion import FusionCandidate

class FusionRepository(abc.ABC):
    @abc.abstractmethod
    def get_pending(self) -> list[FusionCandidate]:
        pass

    @abc.abstractmethod
    def get_by_id(self, candidate_id: str) -> FusionCandidate | None:
        pass

    @abc.abstractmethod
    def save(self, candidate: FusionCandidate) -> None:
        pass

    @abc.abstractmethod
    def get_all(self) -> list[FusionCandidate]:
        pass

class InMemoryFusionRepository(FusionRepository):
    def __init__(self) -> None:
        self._candidates: dict[str, FusionCandidate] = {}

    def get_pending(self) -> list[FusionCandidate]:
        return [c for c in self._candidates.values() if c.status.value == "PENDING"]

    def get_by_id(self, candidate_id: str) -> FusionCandidate | None:
        return self._candidates.get(candidate_id)

    def save(self, candidate: FusionCandidate) -> None:
        self._candidates[candidate.id] = candidate

    def get_all(self) -> list[FusionCandidate]:
        return list(self._candidates.values())
