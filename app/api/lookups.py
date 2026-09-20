from fastapi import APIRouter
from app.schemas.lookups import Need, Priority

needs_router = APIRouter(prefix="/api/needs", tags=["lookups"])
priorities_router = APIRouter(prefix="/api/priorities", tags=["lookups"])

@needs_router.get("", response_model=list[Need])
def get_needs() -> list[Need]:
    return [
        Need(id=1, code="WATER_SANITATION_AND_HYGIENE", name="Water, Sanitation and Hygiene"),
        Need(id=2, code="HEALTH", name="Health"),
        Need(id=3, code="SHELTER", name="Shelter"),
        Need(id=4, code="FOOD", name="Food"),
        Need(id=5, code="PROTECTION", name="Protection"),
    ]

@priorities_router.get("", response_model=list[Priority])
def get_priorities() -> list[Priority]:
    return [
        Priority(id=1, code="CRITICAL", name="Critical"),
        Priority(id=2, code="HIGH", name="High"),
        Priority(id=3, code="MEDIUM", name="Medium"),
        Priority(id=4, code="LOW", name="Low"),
    ]
