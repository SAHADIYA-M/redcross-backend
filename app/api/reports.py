from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.repositories import InMemoryReportRepository
from app.repositories.report_repository import ReportRepository
from app.schemas.report import CreateReport, ReportResponse, UpdateReport
from app.services.report_service import ReportNotFoundError, ReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])

_repository = InMemoryReportRepository()
_report_service = ReportService(_repository)


def get_report_repository() -> ReportRepository:
    """Return the shared in-memory report repository.

    Exposed so other features (e.g. duplicate detection) operate on exactly
    the same reports as the reports API. Swap the storage backend here without
    touching the routers.
    """
    return _repository


def get_report_service() -> ReportService:
    """Return the shared report service.

    A single in-memory repository instance is created once at import time so
    report data persists across requests. The storage backend is swapped here
    (e.g. for a database-backed repository) without changing the router.
    """
    return _report_service


@router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    data: CreateReport,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    return ReportResponse.model_validate(service.create(data))


@router.get("", response_model=list[ReportResponse])
def list_reports(
    service: Annotated[ReportService, Depends(get_report_service)],
) -> list[ReportResponse]:
    return [ReportResponse.model_validate(report) for report in service.get_all()]


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: str,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    try:
        report = service.get_by_id(report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ReportResponse.model_validate(report)


@router.patch("/{report_id}", response_model=ReportResponse)
def update_report(
    report_id: str,
    data: UpdateReport,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportResponse:
    try:
        report = service.update(report_id, data)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ReportResponse.model_validate(report)