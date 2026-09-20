from collections import defaultdict
from app.repositories.report_repository import ReportRepository
from app.schemas.cluster import NeedCluster, EvidenceItem, TimelineItem, ConflictInfo
import hashlib

class ClusterService:
    def __init__(self, report_repository: ReportRepository):
        self.report_repository = report_repository

    def get_clusters(self) -> list[NeedCluster]:
        reports = self.report_repository.get_all()
        
        # Group by location and primary need
        groups = defaultdict(list)
        for report in reports:
            location = report.location or "Unknown Location"
            need = report.needs[0].value if report.needs else "General Request"
            key = f"{location}::{need}"
            groups[key].append(report)
            
        clusters = []
        for key, group in groups.items():
            location, need = key.split("::")
            
            # Aggregate stats
            observations = len(group)
            sources = len(set(r.reporter for r in group))
            
            photos = sum(1 for r in group if any(
                e.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')) for e in r.evidence
            ))
            
            # Simple priority based on severity presence
            severities = [r.severity for r in group if r.severity]
            if any(s.value == "CRITICAL" for s in severities):
                priority = "HIGH"
            elif any(s.value == "HIGH" for s in severities):
                priority = "HIGH"
            elif any(s.value == "MEDIUM" for s in severities):
                priority = "MEDIUM"
            else:
                priority = "LOW"
                
            affected = sum(r.affected_population for r in group if r.affected_population)
            
            # Construct a deterministic ID based on the grouping key
            cluster_id = f"NEX-{hashlib.md5(key.encode()).hexdigest()[:6].upper()}"
            
            # Sort by timestamp to build timeline
            sorted_group = sorted(group, key=lambda r: r.timestamp)
            first_seen = sorted_group[0].timestamp.strftime("%I:%M %p") if sorted_group else "Unknown"
            last_update = sorted_group[-1].timestamp.strftime("%I:%M %p") if sorted_group else "Unknown"
            
            evidence_items = []
            timeline_items = []
            
            for i, r in enumerate(sorted_group):
                time_str = r.timestamp.strftime("%I:%M %p")
                evidence_items.append(
                    EvidenceItem(
                        id=f"REPORT #{r.id[:4].upper()}",
                        role="supports",
                        author=r.reporter,
                        time=time_str,
                        text=f'"{r.original_text}"'
                    )
                )
                timeline_items.append(
                    TimelineItem(
                        time=time_str,
                        id=f"Report #{r.id[:4].upper()}",
                        text=r.original_text[:40] + ("..." if len(r.original_text) > 40 else ""),
                        level="high" if r.severity and r.severity.value in ["CRITICAL", "HIGH"] else "mid"
                    )
                )

            status = "REVIEW"
            if any(r.verification_status.value == "VERIFIED" for r in group):
                status = "VERIFIED"
            
            # Base confidence on number of sources and observations
            confidence = min(100, 50 + (sources * 10) + (observations * 5))
            
            clusters.append(
                NeedCluster(
                    id=cluster_id,
                    need=need.replace("_", " ").title(),
                    location=location,
                    status=status,
                    priority=priority,
                    affected=f"{affected} people" if affected else "Unknown",
                    observations=observations,
                    sources=sources,
                    photos=photos,
                    conflicts=0, # Simplifying conflicts for now
                    firstSeen=first_seen,
                    lastUpdate=last_update,
                    consistent=True,
                    summary=f"Multiple field observations indicate an issue with {need.replace('_', ' ').lower()} around {location}.",
                    fusionReasons=["Same need type", "Same geographic area", f"{observations} observations"],
                    confidence=confidence,
                    evidence=evidence_items,
                    timeline=timeline_items,
                    conflict=None
                )
            )
            
        return clusters
