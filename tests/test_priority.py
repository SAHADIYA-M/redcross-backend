import pytest
from pydantic import ValidationError

from app.ai.schemas import SeverityLevel
from app.models.report import Report
from app.priority.schemas import PriorityLevel, PriorityResult
from app.repositories import InMemoryReportRepository
from app.schemas.report import CreateReport
from app.services.priority_service import (
    InsufficientPriorityDataError,
    PriorityService,
    affected_population_factor_score,
    calculate_priority,
    evidence_verification_factor_score,
    priority_level_for_score,
    severity_factor_score,
    time_sensitivity_factor_score,
    vulnerability_factor_score,
)
from app.services.report_service import ReportNotFoundError, ReportService


def _calc(
    severity_score: float = 0.0,
    population_score: float = 0.0,
    vulnerability_score: float = 0.0,
    time_sensitivity_score: float = 0.0,
    evidence_verification_score: float = 0.0,
) -> PriorityResult:
    return calculate_priority(
        report_id="r1",
        severity_score=severity_score,
        affected_population_score=population_score,
        vulnerability_score=vulnerability_score,
        time_sensitivity_score=time_sensitivity_score,
        evidence_verification_score=evidence_verification_score,
    )


class TestWeightingAndLevels:
    def test_all_factors_zero(self) -> None:
        result = _calc()
        assert result.final_score == 0.0
        assert result.priority_level == PriorityLevel.LOW

    def test_all_factors_hundred(self) -> None:
        result = _calc(100, 100, 100, 100, 100)
        assert result.final_score == 100.0
        assert result.priority_level == PriorityLevel.CRITICAL

    def test_score_exactly_39_is_low(self) -> None:
        result = _calc(severity_score=100, population_score=36)
        assert result.final_score == 39.0
        assert result.priority_level == PriorityLevel.LOW

    def test_score_exactly_40_is_medium(self) -> None:
        result = _calc(severity_score=100, population_score=40)
        assert result.final_score == 40.0
        assert result.priority_level == PriorityLevel.MEDIUM

    def test_score_exactly_69_is_medium(self) -> None:
        result = _calc(severity_score=100, population_score=100, vulnerability_score=70)
        assert result.final_score == 69.0
        assert result.priority_level == PriorityLevel.MEDIUM

    def test_score_exactly_70_is_high(self) -> None:
        result = _calc(severity_score=100, population_score=100, vulnerability_score=75)
        assert result.final_score == 70.0
        assert result.priority_level == PriorityLevel.HIGH

    def test_score_exactly_84_is_high(self) -> None:
        result = _calc(
            severity_score=100, population_score=100, vulnerability_score=100,
            time_sensitivity_score=60,
        )
        assert result.final_score == 84.0
        assert result.priority_level == PriorityLevel.HIGH

    def test_score_exactly_85_is_critical(self) -> None:
        result = _calc(
            severity_score=100, population_score=100, vulnerability_score=100,
            evidence_verification_score=100,
        )
        assert result.final_score == 85.0
        assert result.priority_level == PriorityLevel.CRITICAL

    def test_severity_alone_weights_to_30(self) -> None:
        result = _calc(severity_score=100)
        assert result.final_score == 30.0
        # Phase 8 spec example says this case is "therefore MEDIUM", but that
        # contradicts the explicit 0-39 -> LOW mapping given in section 3
        # (39 -> LOW, 40 -> MEDIUM, 0 -> LOW). The boundary mapping wins.
        assert result.priority_level == PriorityLevel.LOW

    def test_each_weight_is_applied(self) -> None:
        assert _calc(population_score=100).final_score == 25.0
        assert _calc(vulnerability_score=100).final_score == 20.0
        assert _calc(time_sensitivity_score=100).final_score == 15.0
        assert _calc(evidence_verification_score=100).final_score == 10.0

    def test_priority_level_for_score_boundaries(self) -> None:
        assert priority_level_for_score(0) == PriorityLevel.LOW
        assert priority_level_for_score(39.99) == PriorityLevel.LOW
        assert priority_level_for_score(40) == PriorityLevel.MEDIUM
        assert priority_level_for_score(69.99) == PriorityLevel.MEDIUM
        assert priority_level_for_score(70) == PriorityLevel.HIGH
        assert priority_level_for_score(84.99) == PriorityLevel.HIGH
        assert priority_level_for_score(85) == PriorityLevel.CRITICAL
        assert priority_level_for_score(100) == PriorityLevel.CRITICAL


class TestFactorMappings:
    def test_severity_mapping(self) -> None:
        assert severity_factor_score(SeverityLevel.CRITICAL)[0] == 100.0
        assert severity_factor_score(SeverityLevel.HIGH)[0] == 75.0
        assert severity_factor_score(SeverityLevel.MEDIUM)[0] == 50.0
        assert severity_factor_score(SeverityLevel.LOW)[0] == 25.0

    def test_missing_severity_is_neutral(self) -> None:
        score, reason = severity_factor_score(None)
        assert score == 50.0
        assert "neutral" in reason

    def test_affected_population_bands(self) -> None:
        assert affected_population_factor_score(0)[0] == 0.0
        assert affected_population_factor_score(50)[0] == 25.0
        assert affected_population_factor_score(100)[0] == 50.0
        assert affected_population_factor_score(500)[0] == 75.0
        assert affected_population_factor_score(1000)[0] == 100.0
        assert affected_population_factor_score(50000)[0] == 100.0

    def test_missing_population_is_neutral(self) -> None:
        score, reason = affected_population_factor_score(None)
        assert score == 50.0
        assert "neutral" in reason

    def test_vulnerability_count_mapping(self) -> None:
        assert vulnerability_factor_score([])[0] == 50.0
        assert vulnerability_factor_score(["children"])[0] == 60.0
        assert vulnerability_factor_score(["children", "elderly"])[0] == 80.0
        assert vulnerability_factor_score(
            ["children", "elderly", "disabled"]
        )[0] == 100.0
        assert vulnerability_factor_score(
            ["children", "elderly", "disabled", "pregnant"]
        )[0] == 100.0

    def test_time_sensitivity_keywords(self) -> None:
        assert time_sensitivity_factor_score("critical situation")[0] == 100.0
        assert time_sensitivity_factor_score("within 24 hours")[0] == 85.0
        assert time_sensitivity_factor_score("arrive tomorrow")[0] == 85.0
        assert time_sensitivity_factor_score("urgent")[0] == 70.0
        assert time_sensitivity_factor_score("within a week")[0] == 40.0
        assert time_sensitivity_factor_score("not urgent")[0] == 20.0
        assert time_sensitivity_factor_score("call next month")[0] == 20.0

    def test_time_sensitivity_missing_or_unknown_is_neutral(self) -> None:
        score, reason = time_sensitivity_factor_score(None)
        assert score == 50.0
        score, reason = time_sensitivity_factor_score("")
        assert score == 50.0
        score, reason = time_sensitivity_factor_score("hard to say")
        assert score == 50.0
        assert "neutral" in reason

    def test_evidence_mapping(self) -> None:
        assert evidence_verification_factor_score([])[0] == 10.0
        assert evidence_verification_factor_score(["quote one"])[0] == 40.0
        assert evidence_verification_factor_score(["one", "two"])[0] == 50.0
        assert evidence_verification_factor_score(["one", "two", "three"])[0] == 60.0
        assert evidence_verification_factor_score(
            ["one", "two", "three", "four"]
        )[0] == 60.0


class TestValidation:
    def test_invalid_factor_value_above_100(self) -> None:
        with pytest.raises(ValidationError):
            _calc(severity_score=101)

    def test_invalid_final_score_value(self) -> None:
        with pytest.raises(ValidationError):
            PriorityResult(
                report_id="r",
                severity_score=50,
                affected_population_score=50,
                vulnerability_score=50,
                time_sensitivity_score=50,
                evidence_verification_score=50,
                final_score=150,
                priority_level=PriorityLevel.MEDIUM,
            )

    def test_invalid_enum_level(self) -> None:
        with pytest.raises(ValueError):
            PriorityLevel("URGENT")


class TestServiceWithRepository:
    def _service(self) -> tuple[PriorityService, InMemoryReportRepository]:
        repository = InMemoryReportRepository()
        return PriorityService(repository), repository

    def test_missing_report_raises_not_found(self) -> None:
        service, _repository = self._service()
        with pytest.raises(ReportNotFoundError):
            service.calculate_for_report("missing")

    def test_report_without_signals_is_refused(self) -> None:
        service, repository = self._service()
        repository.create(
            Report(
                id="flat",
                original_text="hello",
                reporter="team",
                timestamp="2026-09-20T10:00:00Z",
            )
        )
        with pytest.raises(InsufficientPriorityDataError):
            service.calculate_for_report("flat")

    def test_missing_factors_use_neutral_defaults(self) -> None:
        service, repository = self._service()
        report_service = ReportService(repository)
        created = report_service.create(
            CreateReport(
                original_text="Flooding in the camp",
                reporter="team",
                severity=SeverityLevel.LOW,
            )
        )
        result = service.calculate_for_report(created.id)
        assert result.severity_score == 25.0
        assert result.affected_population_score == 50.0
        assert result.vulnerability_score == 50.0
        assert result.time_sensitivity_score == 50.0
        assert result.evidence_verification_score == 10.0
        assert result.final_score == 38.5
        assert result.priority_level == PriorityLevel.LOW

    def test_result_carries_explanations_and_source_values(self) -> None:
        service, repository = self._service()
        report_service = ReportService(repository)
        created = report_service.create(
            CreateReport(
                original_text="Flooding in the camp",
                reporter="team",
                severity=SeverityLevel.HIGH,
                affected_population=500,
                vulnerability=["children"],
                time_sensitivity="within 24 hours",
                evidence=["no clean water"],
            )
        )
        result = service.calculate_for_report(created.id)
        assert result.final_score == 70.0
        assert result.priority_level == PriorityLevel.HIGH
        assert result.explanations["severity"]
        assert result.source_values["affected_population"] == 500
        assert result.source_values["severity"] == "HIGH"

    def test_calculation_is_deterministic(self) -> None:
        service, repository = self._service()
        report_service = ReportService(repository)
        created = report_service.create(
            CreateReport(
                original_text="Flooding in the camp",
                reporter="team",
                severity=SeverityLevel.HIGH,
                affected_population=500,
            )
        )
        first = service.calculate_for_report(created.id)
        second = service.calculate_for_report(created.id)
        assert first.final_score == second.final_score
        assert first.priority_level == second.priority_level