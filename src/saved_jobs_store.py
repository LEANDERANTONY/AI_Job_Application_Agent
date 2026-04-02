from datetime import datetime, timezone
from typing import Any

from src.auth_service import AuthService
from src.config import SUPABASE_SAVED_JOBS_TABLE
from src.errors import AppError
from src.schemas import SavedJobRecord


class SavedJobsStore:
    def __init__(
        self,
        auth_service: AuthService,
        table_name: str = SUPABASE_SAVED_JOBS_TABLE,
    ):
        self.auth_service = auth_service
        self.table_name = table_name

    def is_configured(self):
        return self.auth_service.is_configured() and bool(self.table_name)

    def save_job(self, access_token: str, refresh_token: str, payload: dict):
        if not self.is_configured():
            raise AppError("Saved jobs are not configured.")

        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        timestamp = datetime.now(timezone.utc).isoformat()
        normalized = self._normalize_payload(payload, timestamp=timestamp)
        if not normalized["user_id"]:
            raise AppError("Saving a job requires an authenticated user id.")
        if not normalized["job_id"]:
            raise AppError("Saving a job requires a normalized job id.")
        try:
            response = (
                client.table(self.table_name)
                .upsert(normalized, on_conflict="user_id,job_id")
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not save this job to your shortlist.",
                details=str(exc),
            ) from exc
        rows = self._extract_rows(response)
        if not rows:
            return self._to_record(normalized)
        return self._to_record(rows[0], fallback=normalized)

    def list_jobs(self, access_token: str, refresh_token: str, user_id: str, limit: int = 20):
        if not self.is_configured():
            raise AppError("Saved jobs are not configured.")
        if not user_id:
            raise AppError("Loading saved jobs requires an authenticated user id.")
        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        try:
            response = (
                client.table(self.table_name)
                .select(
                    "user_id,job_id,source,title,company,location,employment_type,url,summary,description_text,posted_at,scraped_at,metadata,saved_at,updated_at"
                )
                .eq("user_id", user_id)
                .order("saved_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not load your saved jobs.",
                details=str(exc),
            ) from exc
        return [self._to_record(row) for row in self._extract_rows(response)]

    def delete_job(self, access_token: str, refresh_token: str, user_id: str, job_id: str):
        if not self.is_configured():
            raise AppError("Saved jobs are not configured.")
        if not user_id or not job_id:
            raise AppError("Removing a saved job requires a user id and job id.")
        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        try:
            (
                client.table(self.table_name)
                .delete()
                .eq("user_id", user_id)
                .eq("job_id", job_id)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not remove this saved job.",
                details=str(exc),
            ) from exc

    @staticmethod
    def _extract_rows(response: Any):
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get("data") or []
        return getattr(response, "data", None) or []

    @staticmethod
    def _normalize_payload(payload: dict, *, timestamp: str):
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "user_id": str(payload.get("user_id", "") or ""),
            "job_id": str(payload.get("job_id", payload.get("id", "")) or ""),
            "source": str(payload.get("source", "") or ""),
            "title": str(payload.get("title", "") or ""),
            "company": str(payload.get("company", "") or ""),
            "location": str(payload.get("location", "") or ""),
            "employment_type": str(payload.get("employment_type", "") or ""),
            "url": str(payload.get("url", "") or ""),
            "summary": str(payload.get("summary", "") or ""),
            "description_text": str(payload.get("description_text", "") or ""),
            "posted_at": str(payload.get("posted_at", "") or ""),
            "scraped_at": str(payload.get("scraped_at", "") or ""),
            "metadata": metadata,
            "saved_at": str(payload.get("saved_at") or timestamp),
            "updated_at": str(payload.get("updated_at") or timestamp),
        }

    @staticmethod
    def _to_record(payload: dict, fallback: dict | None = None):
        fallback = fallback or {}
        metadata = payload.get("metadata", fallback.get("metadata", {}))
        if not isinstance(metadata, dict):
            metadata = {}
        return SavedJobRecord(
            user_id=str(payload.get("user_id", fallback.get("user_id", "")) or ""),
            job_id=str(payload.get("job_id", fallback.get("job_id", "")) or ""),
            source=str(payload.get("source", fallback.get("source", "")) or ""),
            title=str(payload.get("title", fallback.get("title", "")) or ""),
            company=str(payload.get("company", fallback.get("company", "")) or ""),
            location=str(payload.get("location", fallback.get("location", "")) or ""),
            employment_type=str(payload.get("employment_type", fallback.get("employment_type", "")) or ""),
            url=str(payload.get("url", fallback.get("url", "")) or ""),
            summary=str(payload.get("summary", fallback.get("summary", "")) or ""),
            description_text=str(payload.get("description_text", fallback.get("description_text", "")) or ""),
            posted_at=str(payload.get("posted_at", fallback.get("posted_at", "")) or ""),
            scraped_at=str(payload.get("scraped_at", fallback.get("scraped_at", "")) or ""),
            metadata=metadata,
            saved_at=str(payload.get("saved_at", fallback.get("saved_at", "")) or ""),
            updated_at=str(payload.get("updated_at", fallback.get("updated_at", "")) or ""),
        )
