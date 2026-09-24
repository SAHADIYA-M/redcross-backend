import sys
import os
import asyncio
import uuid

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from datetime import datetime, timezone, timedelta
from app.core.container import get_report_service, get_duplicate_service, get_conflict_service, get_fusion_service, get_fusion_repository
from app.schemas.report import CreateReport
from app.ai.schemas import NeedCategory, SeverityLevel
from app.models.fusion import FusionCandidate, FusionType

def seed_reports():
    print("Seeding realistic flood emergency dataset into reports table...")
    
    report_service = get_report_service()
    
    # Base timestamp: 18th Sept 2026, 10:00 AM UTC
    base_time = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
    
    reports_data = [
        # WATER CLUSTER at Govt. UP School
        {
            "original_text": "No drinking water available near Govt. UP School. Around 40 families affected.",
            "reporter": "Anju Menon",
            "timestamp": base_time + timedelta(minutes=32),
            "location": "Govt. UP School, Ponnani",
            "needs": [NeedCategory.WATER],
            "severity": SeverityLevel.HIGH,
            "affected_population": 40
        },
        {
            "original_text": "People gathered near the school asking for drinking water.",
            "reporter": "Ravi Kumar",
            "timestamp": base_time + timedelta(minutes=41),
            "location": "Govt. UP School, Ponnani",
            "needs": [NeedCategory.WATER],
            "severity": SeverityLevel.MEDIUM
        },
        {
            "original_text": "Water tanker hasn't arrived near the school relief point yet.",
            "reporter": "Anju Menon",
            "timestamp": base_time + timedelta(minutes=55),
            "location": "Govt. UP School, Ponnani",
            "needs": [NeedCategory.WATER],
            "severity": SeverityLevel.HIGH
        },
        {
            "original_text": "Photograph showing empty water containers lined up outside the school.",
            "reporter": "Ravi Kumar",
            "timestamp": base_time + timedelta(minutes=60),
            "location": "Govt. UP School, Ponnani",
            "needs": [NeedCategory.WATER],
            "severity": SeverityLevel.MEDIUM
        },
        # Separate location but same need - Water at Relief Centre
        {
            "original_text": "Approximately 45 families need water near the relief centre.",
            "reporter": "Fathima S.",
            "timestamp": base_time + timedelta(minutes=74),
            "location": "Ponnani Relief Centre",
            "needs": [NeedCategory.WATER],
            "severity": SeverityLevel.HIGH,
            "affected_population": 45
        },
        {
            "original_text": "Tanker arrived at relief centre. Water being distributed now.",
            "reporter": "Anju Menon",
            "timestamp": base_time + timedelta(minutes=150),
            "location": "Ponnani Relief Centre",
            "needs": [NeedCategory.WATER],
            "severity": SeverityLevel.LOW
        },
        
        # HEALTHCARE CLUSTER at Hospital
        {
            "original_text": "Hospital reports shortage of basic medicines, especially for elderly patients.",
            "reporter": "Ravi Kumar",
            "timestamp": base_time - timedelta(minutes=50),
            "location": "Government Taluk Hospital, Ponnani",
            "needs": [NeedCategory.HEALTHCARE],
            "severity": SeverityLevel.CRITICAL
        },
        {
            "original_text": "Taluk hospital pharmacy running low on stock, ~60 patients affected.",
            "reporter": "Fathima S.",
            "timestamp": base_time - timedelta(minutes=35),
            "location": "Government Taluk Hospital, Ponnani",
            "needs": [NeedCategory.HEALTHCARE],
            "severity": SeverityLevel.CRITICAL,
            "affected_population": 60
        },
        
        # TRANSPORTATION CLUSTER
        {
            "original_text": "Chalissery road bridge partially submerged, vehicles cannot cross.",
            "reporter": "Anju Menon",
            "timestamp": base_time - timedelta(minutes=105),
            "location": "Chalissery Road Bridge",
            "needs": [NeedCategory.TRANSPORTATION],
            "severity": SeverityLevel.HIGH
        },
        {
            "original_text": "Bridge closure reported, approx 200 people cut off from relief centre.",
            "reporter": "Ravi Kumar",
            "timestamp": base_time - timedelta(minutes=100),
            "location": "Chalissery Road Bridge",
            "needs": [NeedCategory.TRANSPORTATION],
            "severity": SeverityLevel.CRITICAL,
            "affected_population": 200
        },
        
        # SHELTER CLUSTER
        {
            "original_text": "Relief centre at capacity, families sleeping outside under tarpaulin.",
            "reporter": "Fathima S.",
            "timestamp": base_time + timedelta(minutes=180),
            "location": "Ponnani Relief Centre",
            "needs": [NeedCategory.SHELTER],
            "severity": SeverityLevel.HIGH
        },
        {
            "original_text": "Need additional tents at Ponnani relief centre, ~30 families without shelter.",
            "reporter": "Anju Menon",
            "timestamp": base_time + timedelta(minutes=190),
            "location": "Ponnani Relief Centre",
            "needs": [NeedCategory.SHELTER],
            "severity": SeverityLevel.HIGH,
            "affected_population": 30
        },
        
        # MULTI-NEED REPORT
        {
            "original_text": "20 families need water, 5 houses are damaged, and 3 people need medical attention in Ponnani riverside ward.",
            "reporter": "Fathima S.",
            "timestamp": base_time + timedelta(minutes=240),
            "location": "Ponnani Riverside Ward",
            "needs": [NeedCategory.WATER, NeedCategory.SHELTER, NeedCategory.HEALTHCARE],
            "severity": SeverityLevel.CRITICAL,
            "affected_population": 20
        },
        
        # UNRELATED NOISE
        {
            "original_text": "Minor road debris cleared near market junction, no injuries.",
            "reporter": "Ravi Kumar",
            "timestamp": base_time - timedelta(minutes=180),
            "location": "Market Junction",
            "needs": [NeedCategory.OTHER],
            "severity": SeverityLevel.LOW
        },
    ]

    created_reports = []
    for rep in reports_data:
        create_payload = CreateReport(**rep)
        created = report_service.create(create_payload)
        created_reports.append(created)
        print(f"Created report: {created.id} - {created.location}")

    print(f"Successfully seeded {len(created_reports)} reports.")
    
    print("Seeding some fusion candidates for UI testing...")
    
    if len(created_reports) >= 4:
        fusion_repo = get_fusion_repository()
        
        c1 = FusionCandidate(
            id=uuid.uuid4().hex,
            type=FusionType.POSSIBLE_DUPLICATE,
            report_ids=[created_reports[0].id, created_reports[1].id],
            cluster_id="NEX-DEMO", 
            reason="These two reports describe the same water shortage at Govt. UP School.",
            similarity=0.92
        )
        fusion_repo.save(c1)
        
        c2 = FusionCandidate(
            id=uuid.uuid4().hex,
            type=FusionType.POSSIBLE_CONFLICT,
            report_ids=[created_reports[4].id, created_reports[5].id],
            cluster_id="NEX-DEMO2",
            reason="Report 1 says 45 families need water. Report 2 says tanker has arrived and water is being distributed.",
            similarity=0.88
        )
        fusion_repo.save(c2)
        
        print("Successfully seeded fusion candidates.")

if __name__ == "__main__":
    seed_reports()
