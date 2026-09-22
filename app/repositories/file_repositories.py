import os
import json
from typing import TypeVar, Generic, Type

from app.models.user import User
from app.models.report import Report
from app.verification.schemas import VerificationRecord
from app.audit.schemas import AuditRecord
from app.response_activity.schemas import ResponseActivity

from app.repositories.user_repository import UserRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.verification_repository import VerificationRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.response_repository import ResponseRepository

T = TypeVar('T')

class JsonStore(Generic[T]):
    def __init__(self, filename: str, model_class: Type[T]):
        self.filename = filename
        self.model_class = model_class
        self._data: dict[str, T] = {}
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                for k, v in raw.items():
                    self._data[k] = self.model_class.model_validate(v)
    
    def get(self, key: str, default=None):
        return self._data.get(key, default)
    
    def __getitem__(self, key: str) -> T:
        return self._data[key]
    
    def __setitem__(self, key: str, value: T):
        self._data[key] = value
        self._save()
        
    def __contains__(self, key: str) -> bool:
        return key in self._data
        
    def values(self):
        return self._data.values()
        
    def _save(self):
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump({k: v.model_dump(mode='json') for k, v in self._data.items()}, f)


class FileUserRepository(UserRepository):
    def __init__(self, data_dir: str):
        self._store = JsonStore(os.path.join(data_dir, "users.json"), User)
        self._by_username: dict[str, str] = {}
        for user in self._store.values():
            self._by_username[user.username.casefold()] = user.user_id

    def create_user(self, user: User) -> User:
        key = user.username.casefold()
        self._store[user.user_id] = user
        self._by_username[key] = user.user_id
        return user

    def get_by_id(self, user_id: str) -> User | None:
        return self._store.get(user_id)

    def get_by_username(self, username: str) -> User | None:
        user_id = self._by_username.get(username.casefold())
        return self._store.get(user_id) if user_id is not None else None

    def list_users(self) -> list[User]:
        return list(self._store.values())

    def update_user(self, user: User) -> User | None:
        if user.user_id not in self._store:
            return None
        self._store[user.user_id] = user
        self._by_username[user.username.casefold()] = user.user_id
        return user


class FileReportRepository(ReportRepository):
    def __init__(self, data_dir: str):
        self._store = JsonStore(os.path.join(data_dir, "reports.json"), Report)

    def create(self, report: Report) -> Report:
        self._store[report.id] = report
        return report

    def get_by_id(self, report_id: str) -> Report | None:
        return self._store.get(report_id)

    def get_all(self) -> list[Report]:
        return list(self._store.values())

    def get_cluster_candidates(self, location: str, need: str) -> list[Report]:
        return [
            report
            for report in self._store.values()
            if report.cluster_location == location and report.cluster_need == need
        ]

    def update(self, report_id: str, report: Report) -> Report | None:
        if report_id not in self._store:
            return None
        self._store[report_id] = report
        return report


class FileVerificationRepository(VerificationRepository):
    def __init__(self, data_dir: str):
        self._store = JsonStore(os.path.join(data_dir, "verifications.json"), VerificationRecord)

    def create(self, record: VerificationRecord) -> VerificationRecord:
        self._store[record.verification_id] = record
        return record

    def get_all(self) -> list[VerificationRecord]:
        return list(self._store.values())


class FileAuditRepository(AuditRepository):
    def __init__(self, data_dir: str):
        self._store = JsonStore(os.path.join(data_dir, "audits.json"), AuditRecord)

    def create(self, record: AuditRecord) -> AuditRecord:
        self._store[record.audit_id] = record
        return record

    def get_all(self) -> list[AuditRecord]:
        return list(self._store.values())


class FileResponseRepository(ResponseRepository):
    def __init__(self, data_dir: str):
        self._store = JsonStore(os.path.join(data_dir, "responses.json"), ResponseActivity)

    def create(self, response: ResponseActivity) -> ResponseActivity:
        self._store[response.response_id] = response
        return response

    def get_by_id(self, response_id: str) -> ResponseActivity | None:
        return self._store.get(response_id)

    def get_all(self) -> list[ResponseActivity]:
        return list(self._store.values())

    def update(self, response_id: str, response: ResponseActivity) -> ResponseActivity | None:
        if response_id not in self._store:
            return None
        self._store[response_id] = response
        return response

from app.models.fusion import FusionCandidate
from app.repositories.fusion_repository import FusionRepository

class FileFusionRepository(FusionRepository):
    def __init__(self, data_dir: str) -> None:
        import os
        self._store = JsonStore(os.path.join(data_dir, 'fusion.json'), FusionCandidate)

    def get_pending(self) -> list[FusionCandidate]:
        return [c for c in self._store.values() if c.status.value == 'PENDING']

    def get_by_id(self, candidate_id: str) -> FusionCandidate | None:
        return self._store.get(candidate_id)

    def save(self, candidate: FusionCandidate) -> None:
        self._store[candidate.id] = candidate

    def get_by_cluster(self, cluster_id: str) -> list[FusionCandidate]:
        return [
            candidate
            for candidate in self._store.values()
            if candidate.cluster_id == cluster_id
        ]

    def get_all(self) -> list[FusionCandidate]:
        return list(self._store.values())
