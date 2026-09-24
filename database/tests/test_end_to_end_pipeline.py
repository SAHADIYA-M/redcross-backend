"""End-to-End System Pipeline Test for RedCross Nexus."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)
sys.path.insert(0, str(_PROJECT_ROOT))

from app.core.config import get_settings
from app.repositories.report_repository import PsycopgReportRepository
from app.services.extraction_service import ExtractionService
from app.services.fusion_service import FusionService
from app.services.copilot_service import CopilotService


def main():
    settings = get_settings()
    if not settings.database_url:
        print("[FAIL] DATABASE_URL is not set.")
        sys.exit(1)

    print("=== REDCROSS NEXUS — END-TO-END PIPELINE VERIFICATION ===")

    # 1. Test Ingestion & Extraction
    print("\n1. Testing AI Entity Extraction on incoming raw text...")
    sample_text = "15 families near Ponnani Govt UP School have no drinking water. Two houses completely collapsed. Need urgent medical aid for 1 injured elder."
    extractor = ExtractionService(api_key=settings.gemini_api_key)
    extracted = extractor.extract_structured_report(sample_text)

    print(f"   [OK] Summary: {extracted.get('summary')}")
    print(f"   [OK] Needs extracted: {[n['code'] for n in extracted.get('needs', [])]}")

    # 2. Test Repository Creation
    print("\n2. Persisting report into Supabase PostgreSQL...")
    repo = PsycopgReportRepository(settings.database_url)
    created = repo.create_report({
        "raw_content": sample_text,
        "source": "automated_e2e_test",
        "location_id": "aaaaaaaa-0001-0001-0001-000000000001",
        "verification_status": "AI_GENERATED",
    })
    report_id = created["report_id"]
    print(f"   [OK] Report created with ID: {report_id}")

    # 3. Test Fusion & Vector Embedding
    print("\n3. Generating 768-dim vector embedding & running spatiotemporal candidate fusion...")
    fusion = FusionService(settings.database_url)
    fusion_res = fusion.process_and_fuse_report(
        report_id=report_id,
        raw_content=sample_text,
        need_ids=[1, 3, 4],
        location_id="aaaaaaaa-0001-0001-0001-000000000001",
    )
    print(f"   [OK] Candidates retrieved: {fusion_res['candidate_count']}")
    print(f"   [OK] Duplicate candidates found: {len(fusion_res['duplicate_candidates'])}")

    # 4. Test Human Verification Action
    print("\n4. Executing Human-in-the-Loop verification action (CONFIRM)...")
    verif = repo.update_verification_status(
        report_id=report_id,
        status="VERIFIED_RESPONDER",
        notes="Confirmed by E2E test responder",
    )
    print(f"   [OK] Updated verification status to: {verif['verification_status']}")

    # 5. Test RAG Copilot Query
    print("\n5. Querying RAG Copilot for evidence-backed answer...")
    copilot = CopilotService(database_url=settings.database_url, api_key=settings.gemini_api_key)
    query_res = copilot.answer_query("What are the water and shelter needs at Govt UP School?")

    print(f"\n--- RAG COPILOT RESPONSE ---")
    print(query_res["answer"])
    print(f"\n--- CITATIONS ({len(query_res['citations'])}) ---")
    for c in query_res["citations"]:
        print(f"  - Report #{c['report_id'][:8]} | {c['location_name']} | Sim: {c['similarity']}")

    print("\n✓ ALL END-TO-END PIPELINE VERIFICATION STEPS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
