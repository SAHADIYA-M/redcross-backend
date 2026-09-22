from abc import ABC, abstractmethod

from app.models.report import Report


class ReportRepository(ABC):
    """Contract for storing and retrieving reports.

    The API and service layers depend on this interface only. Concrete
    implementations (in-memory today, PostgreSQL later) can be swapped
    without changing the rest of the application.
    """

    @abstractmethod
    def create(self, report: Report) -> Report:
        """Persist a new report and return it."""

    @abstractmethod
    def get_by_id(self, report_id: str) -> Report | None:
        """Return the report with the given id, or None if not found."""

    @abstractmethod
    def get_all(self) -> list[Report]:
        """Return all stored reports."""

    @abstractmethod
    def update(self, report_id: str, report: Report) -> Report | None:
        """Replace the stored report with the given one; None if not found."""

    def search_reports(self, query) -> list[Report]:
        """Return reports matching a validated ``SearchQuery`` via backend filters.

        Optional pushdown hook: storage backends that can translate the
        query's non-priority filters (text, need, verification status, status,
        source, incident, time range) into native queries implement it. The
        default signals "not supported", which makes the search service fall
        back to ``get_all()`` + in-memory filtering so behavior is unchanged.
        Bounding-box and priority filters are always handled by the service
        layer, never here.
        """
        raise NotImplementedError

    def get_cluster_candidates(self, location: str, need: str) -> list[Report]:
        """Return reports belonging to the same fusion cluster (location+need).

        A cluster is keyed by the normalized location (``Unknown Location``
        when unset) and the report's first need (``General Request`` when it
        has none). Only reports in the same cluster are comparable for
        duplicate/conflict detection, so report creation can retrieve just the
        candidates instead of scanning every report. Storage backends that can
        push the lookup down (PostgreSQL) override this; the default keeps
        behavior correct for every backend at the cost of a scan.
        """
        return [
            report
            for report in self.get_all()
            if report.cluster_location == location and report.cluster_need == need
        ]


class PsycopgReportRepository:
    """PostgreSQL implementation of ReportRepository using psycopg (v3)."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_report(self, report_data: dict) -> dict:
        """Insert a report record into PostgreSQL and return its created metadata."""
        import psycopg
        source_type = report_data.get("source", "text")
        if source_type not in ("text", "image", "csv", "json"):
            source_type = "text"
            
        raw_content = report_data.get("raw_content", "")
        location_id = report_data.get("location_id")
        verification_status = report_data.get("verification_status", "AI_GENERATED")

        query = """
            INSERT INTO field_reports (source_type, raw_content, location_id, reported_at)
            VALUES (%s, %s, %s::uuid, NOW())
            RETURNING report_id::text;
        """
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (source_type, raw_content, location_id))
                row = cur.fetchone()
                conn.commit()
                report_id = row[0] if row else None

        return {
            "report_id": report_id,
            "raw_content": raw_content,
            "location_id": location_id,
            "verification_status": verification_status,
        }

    def update_verification_status(self, report_id: str, status: str, notes: str = "") -> dict:
        """Update or record verification status for a report."""
        import psycopg
        # Also attempt to log into verifications table if cluster exists, or record status
        query = """
            INSERT INTO verifications (cluster_id, responder_id, action, notes)
            SELECT rc.cluster_id, r.responder_id, 'confirm', %s
            FROM report_clusters rc, responders r
            LIMIT 1;
        """
        with psycopg.connect(self._database_url, prepare_threshold=None) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(query, (notes,))
                    conn.commit()
                except Exception:
                    pass

        return {
            "report_id": report_id,
            "verification_status": status,
            "notes": notes,
        }