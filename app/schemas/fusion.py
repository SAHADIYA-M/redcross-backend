from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from app.models.fusion import FusionType, FusionStatus, FusionResolution

class FusionCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    type: FusionType
    report_ids: list[str]
    cluster_id: str
    reason: str
    similarity: Optional[float] = None
    status: FusionStatus
    resolution: Optional[FusionResolution] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None

class ResolveFusionRequest(BaseModel):
    action: FusionResolution
