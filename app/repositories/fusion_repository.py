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
    def get_by_cluster(self, cluster_id: str) -> list[FusionCandidate]:
        """Return the candidates belonging to one fusion cluster.

        Fusion candidate ids are derived from the report pair only, so the
        dedup set for a cluster never needs the whole table: a pair of reports
        always belongs to the single cluster of their shared cluster key, and
        ``analyze_cluster`` only ever compares reports inside one cluster.
        Cluster-scoped retrieval keeps the create path from loading the entire
        ``fusion_candidates`` table (which in a large incident can grow
        quadratically with the number of reports).
        """
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

    def get_by_cluster(self, cluster_id: str) -> list[FusionCandidate]:
        return [
            candidate
            for candidate in self._candidates.values()
            if candidate.cluster_id == cluster_id
        ]

    def get_all(self) -> list[FusionCandidate]:
        return list(self._candidates.values())
