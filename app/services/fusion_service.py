import hashlib
import re
from itertools import combinations
from datetime import datetime, timezone
from app.models.report import Report
from app.models.fusion import FusionCandidate, FusionType, FusionStatus, FusionResolution
from app.repositories.fusion_repository import FusionRepository

def _tokenize(text: str) -> set[str]:
    # normalize case
    text = text.lower()
    # remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # tokenize consistently and ignore empty tokens
    tokens = {t for t in text.split() if t}
    return tokens

def _jaccard_similarity(text1: str, text2: str) -> float:
    t1 = _tokenize(text1)
    t2 = _tokenize(text2)
    if not t1 and not t2:
        return 0.0
    intersection = len(t1 & t2)
    union = len(t1 | t2)
    return intersection / union if union > 0 else 0.0

def _candidate_pair_key(type_: FusionType, r1: str, r2: str) -> frozenset[str]:
    """Natural identity of a candidate within a cluster: type + report pair.

    A pair of reports can be BOTH a possible duplicate and a possible conflict
    (e.g. near-identical text AND CRITICAL-vs-LOW severity), so the type is
    part of the identity: deduping by the pair alone would silently drop the
    second candidate of the same pair.
    """
    return frozenset((type_, r1, r2))


def _get_candidate_id(type_: FusionType, cluster_id: str, r1: str, r2: str) -> str:
    """Deterministic candidate id scoped to (cluster, type, report pair).

    The cluster id is part of the hash material so candidate ids are globally
    unique per (cluster, type, pair): analyzing the same pair under two
    different clusters produces two distinct ids and never clobbers the first
    cluster's candidate in id-keyed storage. The type is part of the material
    too, so a pair that is both a duplicate and a conflict yields two distinct
    candidates instead of one overwriting the other (every possible pair of
    reports shares exactly one cluster, but candidate identity must not depend
    on that invariant staying true forever).
    """
    sorted_ids = sorted([r1, r2])
    material = cluster_id + sorted_ids[0] + sorted_ids[1] + type_.value
    return f"FUS-{type_.value[:3]}-{hashlib.md5(material.encode()).hexdigest()[:8].upper()}"

class FusionService:
    def __init__(self, repository_or_db_url: FusionRepository | str | None = None):
        if isinstance(repository_or_db_url, str):
            self._database_url = repository_or_db_url
            self._repository = None
        else:
            self._repository = repository_or_db_url
            self._database_url = None

    def process_and_fuse_report(
        self,
        report_id: str,
        raw_content: str,
        need_ids: list[int] | None = None,
        location_id: str | None = None,
    ) -> dict:
        """Embed report text, update database, and query candidate duplicate/conflict reports."""
        import psycopg
        from pgvector.psycopg import register_vector
        from database.scripts.embedding_utils import embed_text

        db_url = getattr(self, "_database_url", None)
        if not db_url:
            import os
            db_url = os.environ.get("DATABASE_URL")

        # Generate 768-dim vector embedding
        vector = embed_text(raw_content)

        # Store vector embedding in PostgreSQL if db_url is set
        candidates = []
        if db_url:
            with psycopg.connect(db_url, prepare_threshold=None) as conn:
                register_vector(conn)
                with conn.cursor() as cur:
                    # Update report embedding
                    cur.execute(
                        "UPDATE field_reports SET embedding = %s WHERE report_id = %s::uuid",
                        (vector, report_id),
                    )
                    conn.commit()

                    # Query similar candidates by cosine distance
                    query = """
                        SELECT fr.report_id::text, fr.raw_content, 1 - (fr.embedding <=> %s::vector) AS similarity
                        FROM field_reports fr
                        WHERE fr.report_id <> %s::uuid AND fr.embedding IS NOT NULL
                        ORDER BY fr.embedding <=> %s::vector ASC
                        LIMIT 5;
                    """
                    cur.execute(query, (vector, report_id, vector))
                    for row in cur.fetchall():
                        candidates.append({
                            "report_id": row[0],
                            "snippet": row[1][:80] if row[1] else "",
                            "similarity": float(row[2]) if row[2] is not None else 0.0,
                        })

        duplicate_candidates = [c for c in candidates if c.get("similarity", 0.0) >= 0.60]

        return {
            "report_id": report_id,
            "candidate_count": len(candidates),
            "duplicate_candidates": duplicate_candidates,
            "candidates": candidates,
        }


    def analyze_cluster(self, cluster_id: str, reports: list[Report]) -> None:
        if len(reports) < 2:
            return

        # Only this cluster's existing candidates can collide with a candidate
        # we might create. Loading the whole table here would turn every report
        # creation into a full-table scan of the (potentially quadratic)
        # fusion_candidates table.
        existing = self._repository.get_by_cluster(cluster_id)
        existing_ids = {candidate.id for candidate in existing}
        existing_keys = {
            _candidate_pair_key(candidate.type, *sorted(candidate.report_ids))
            for candidate in existing
            if len(candidate.report_ids) == 2
        }

        for r1, r2 in combinations(reports, 2):
            # Duplicate checks
            similarity = _jaccard_similarity(r1.original_text, r2.original_text)
            
            duplicate_reasons = []
            if similarity >= 0.60:
                duplicate_reasons.append(f"text similarity {similarity:.2f} exceeds the 0.60 threshold")
                
            if r1.reporter == r2.reporter:
                diff_seconds = abs((r1.timestamp - r2.timestamp).total_seconds())
                if diff_seconds <= 3600:
                    duplicate_reasons.append("same reporter submitted both reports within 1 hour")

            if duplicate_reasons:
                cand_id = _get_candidate_id(FusionType.POSSIBLE_DUPLICATE, cluster_id, r1.id, r2.id)
                pair_key = _candidate_pair_key(FusionType.POSSIBLE_DUPLICATE, r1.id, r2.id)
                if cand_id not in existing_ids and pair_key not in existing_keys:
                    cand = FusionCandidate(
                        id=cand_id,
                        type=FusionType.POSSIBLE_DUPLICATE,
                        report_ids=[r1.id, r2.id],
                        cluster_id=cluster_id,
                        reason="Possible duplicate: " + " AND ".join(duplicate_reasons),
                        similarity=similarity
                    )
                    self._repository.save(cand)
                    existing_ids.add(cand_id)
                    existing_keys.add(pair_key)

            # Conflict checks
            conflict_reasons = []
            if r1.severity and r2.severity:
                if (r1.severity.value == "CRITICAL" and r2.severity.value == "LOW") or \
                   (r1.severity.value == "LOW" and r2.severity.value == "CRITICAL"):
                    conflict_reasons.append("One report states CRITICAL severity while another states LOW severity")
            
            if r1.affected_population is not None and r2.affected_population is not None:
                max_pop = max(r1.affected_population, r2.affected_population)
                min_pop = min(r1.affected_population, r2.affected_population)
                if max_pop > 100 and min_pop < 10:
                    conflict_reasons.append("One report states affected population > 100 while another states < 10")

            if conflict_reasons:
                cand_id = _get_candidate_id(FusionType.POSSIBLE_CONFLICT, cluster_id, r1.id, r2.id)
                pair_key = _candidate_pair_key(FusionType.POSSIBLE_CONFLICT, r1.id, r2.id)
                if cand_id not in existing_ids and pair_key not in existing_keys:
                    cand = FusionCandidate(
                        id=cand_id,
                        type=FusionType.POSSIBLE_CONFLICT,
                        report_ids=[r1.id, r2.id],
                        cluster_id=cluster_id,
                        reason="Possible conflict: " + " AND ".join(conflict_reasons)
                    )
                    self._repository.save(cand)
                    existing_ids.add(cand_id)
                    existing_keys.add(pair_key)

    def resolve(
        self,
        candidate_id: str,
        resolution: FusionResolution,
        user_id: str | None = None,
    ) -> FusionCandidate | None:
        candidate = self._repository.get_by_id(candidate_id)
        if not candidate:
            return None
        
        candidate.status = FusionStatus.RESOLVED
        candidate.resolution = resolution
        candidate.reviewed_by = user_id
        candidate.reviewed_at = datetime.now(timezone.utc)
        
        self._repository.save(candidate)
        return candidate
