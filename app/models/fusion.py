from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

class FusionType(str, Enum):
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    POSSIBLE_CONFLICT = "POSSIBLE_CONFLICT"

class FusionStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"

class FusionResolution(str, Enum):
    MERGED = "MERGED"
    KEPT_SEPARATE = "KEPT_SEPARATE"
    DISMISSED = "DISMISSED"

class FusionCandidate(BaseModel):
    id: str
    type: FusionType
    report_ids: list[str]
    cluster_id: str
    reason: str
    similarity: Optional[float] = None
    status: FusionStatus = FusionStatus.PENDING
    resolution: Optional[FusionResolution] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
