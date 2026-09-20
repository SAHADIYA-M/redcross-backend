from pydantic import BaseModel
from typing import List, Optional

class EvidenceItem(BaseModel):
    id: str
    role: str
    author: str
    time: str
    text: str

class TimelineItem(BaseModel):
    time: str
    id: str
    text: str
    level: str

class ConflictInfo(BaseModel):
    prev: str
    latest: str

class NeedCluster(BaseModel):
    id: str
    need: str
    location: str
    status: str
    priority: str
    affected: str
    observations: int
    sources: int
    photos: int
    conflicts: int
    firstSeen: str
    lastUpdate: str
    consistent: bool
    summary: str
    fusionReasons: list[str]
    confidence: int
    evidence: list[EvidenceItem]
    timeline: list[TimelineItem]
    conflict: Optional[ConflictInfo] = None

class PaginatedClusters(BaseModel):
    results: list[NeedCluster]
    count: int
    next: Optional[str] = None
    previous: Optional[str] = None
