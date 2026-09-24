from app.services.report_service import ReportService
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.container import get_report_service
from app.schemas.lengths import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.schemas.report import CreateReport, ReportResponse, UpdateReport
from app.services.report_service import ReportNotFoundError

router = APIRouter(prefix="/api/reports", tags=["reports"])


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
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[ReportResponse]:
    return [
        ReportResponse.model_validate(report)
        for report in service.get_all()[offset : offset + limit]
    ]


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