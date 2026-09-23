from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.core.container import get_report_repository
from app.services.cluster_service import ClusterService
from app.schemas.cluster import PaginatedClusters, NeedCluster

router = APIRouter(prefix="/api/clusters", tags=["clusters"])

def get_cluster_service() -> ClusterService:
    from app.core.container import get_report_repository
    return ClusterService(get_report_repository())

@router.get("", response_model=PaginatedClusters)
def get_clusters(
    service: Annotated[ClusterService, Depends(get_cluster_service)],
) -> PaginatedClusters:
    clusters = service.get_clusters()
    return PaginatedClusters(
        results=clusters,
        count=len(clusters),
        next=None,
        previous=None
    )

@router.get("/{cluster_id}", response_model=NeedCluster)
def get_cluster(
    cluster_id: str,
    service: Annotated[ClusterService, Depends(get_cluster_service)],
) -> NeedCluster:
    clusters = service.get_clusters()
    for c in clusters:
        if c.id == cluster_id:
            return c
    raise HTTPException(status_code=404, detail="Cluster not found")
