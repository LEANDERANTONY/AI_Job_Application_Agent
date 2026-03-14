from datetime import datetime, timezone

from src.auth_service import AuthService
from src.config import SUPABASE_ARTIFACTS_TABLE, SUPABASE_WORKFLOW_RUNS_TABLE
from src.errors import AppError
from src.schemas import ArtifactRecord, WorkflowRunRecord


class HistoryStore:
    def __init__(
        self,
        auth_service: AuthService,
        workflow_runs_table: str = SUPABASE_WORKFLOW_RUNS_TABLE,
        artifacts_table: str = SUPABASE_ARTIFACTS_TABLE,
    ):
        self.auth_service = auth_service
        self.workflow_runs_table = workflow_runs_table
        self.artifacts_table = artifacts_table

    def is_configured(self):
        return (
            self.auth_service.is_configured()
            and bool(self.workflow_runs_table)
            and bool(self.artifacts_table)
        )

    def create_workflow_run(self, access_token: str, refresh_token: str, payload: dict):
        client = self._client(access_token, refresh_token)
        normalized = {
            "user_id": str(payload.get("user_id", "") or ""),
            "job_title": str(payload.get("job_title", "") or ""),
            "fit_score": int(payload.get("fit_score", 0) or 0),
            "review_approved": bool(payload.get("review_approved", False)),
            "model_policy": str(payload.get("model_policy", "") or ""),
            "workflow_signature": str(payload.get("workflow_signature", "") or ""),
            "workflow_snapshot_json": str(payload.get("workflow_snapshot_json", "") or ""),
            "report_payload_json": str(payload.get("report_payload_json", "") or ""),
            "tailored_resume_payload_json": str(payload.get("tailored_resume_payload_json", "") or ""),
            "created_at": str(payload.get("created_at") or datetime.now(timezone.utc).isoformat()),
        }
        if not normalized["user_id"]:
            raise AppError("Workflow history requires an authenticated user id.")
        try:
            response = client.table(self.workflow_runs_table).insert(normalized).execute()
        except Exception as exc:
            raise AppError(
                "The app could not persist the workflow run.",
                details=str(exc),
            ) from exc
        rows = getattr(response, "data", None) or []
        if not rows:
            return WorkflowRunRecord(id="", **normalized)
        row = rows[0]
        return WorkflowRunRecord(
            id=str(row.get("id", "")),
            user_id=str(row.get("user_id", normalized["user_id"])),
            job_title=str(row.get("job_title", normalized["job_title"])),
            fit_score=int(row.get("fit_score", normalized["fit_score"])),
            review_approved=bool(row.get("review_approved", normalized["review_approved"])),
            model_policy=str(row.get("model_policy", normalized["model_policy"])),
            workflow_signature=str(row.get("workflow_signature", normalized["workflow_signature"])),
            workflow_snapshot_json=str(row.get("workflow_snapshot_json", normalized["workflow_snapshot_json"])),
            report_payload_json=str(row.get("report_payload_json", normalized["report_payload_json"])),
            tailored_resume_payload_json=str(row.get("tailored_resume_payload_json", normalized["tailored_resume_payload_json"])),
            created_at=str(row.get("created_at", normalized["created_at"])),
        )

    def list_recent_workflow_runs(self, access_token: str, refresh_token: str, user_id: str, limit: int = 5):
        client = self._client(access_token, refresh_token)
        try:
            response = (
                client.table(self.workflow_runs_table)
                .select("id,user_id,job_title,fit_score,review_approved,model_policy,workflow_signature,workflow_snapshot_json,report_payload_json,tailored_resume_payload_json,created_at")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not load recent workflow history.",
                details=str(exc),
            ) from exc
        return [
            WorkflowRunRecord(
                id=str(row.get("id", "")),
                user_id=str(row.get("user_id", user_id)),
                job_title=str(row.get("job_title", "")),
                fit_score=int(row.get("fit_score", 0) or 0),
                review_approved=bool(row.get("review_approved", False)),
                model_policy=str(row.get("model_policy", "")),
                workflow_signature=str(row.get("workflow_signature", "")),
                workflow_snapshot_json=str(row.get("workflow_snapshot_json", "") or ""),
                report_payload_json=str(row.get("report_payload_json", "") or ""),
                tailored_resume_payload_json=str(row.get("tailored_resume_payload_json", "") or ""),
                created_at=str(row.get("created_at", "")),
            )
            for row in (getattr(response, "data", None) or [])
        ]

    def create_artifact_record(self, access_token: str, refresh_token: str, payload: dict):
        client = self._client(access_token, refresh_token)
        normalized = {
            "workflow_run_id": str(payload.get("workflow_run_id", "") or ""),
            "artifact_type": str(payload.get("artifact_type", "") or ""),
            "filename_stem": str(payload.get("filename_stem", "") or ""),
            "storage_path": str(payload.get("storage_path", "") or ""),
            "created_at": str(payload.get("created_at") or datetime.now(timezone.utc).isoformat()),
        }
        if not normalized["workflow_run_id"]:
            raise AppError("Artifact history requires an active workflow run id.")
        try:
            response = client.table(self.artifacts_table).insert(normalized).execute()
        except Exception as exc:
            raise AppError(
                "The app could not persist the artifact record.",
                details=str(exc),
            ) from exc
        rows = getattr(response, "data", None) or []
        if not rows:
            return ArtifactRecord(id="", **normalized)
        row = rows[0]
        return ArtifactRecord(
            id=str(row.get("id", "")),
            workflow_run_id=str(row.get("workflow_run_id", normalized["workflow_run_id"])),
            artifact_type=str(row.get("artifact_type", normalized["artifact_type"])),
            filename_stem=str(row.get("filename_stem", normalized["filename_stem"])),
            storage_path=str(row.get("storage_path", normalized["storage_path"])),
            created_at=str(row.get("created_at", normalized["created_at"])),
        )

    def list_recent_artifacts(self, access_token: str, refresh_token: str, workflow_run_id: str, limit: int = 10):
        client = self._client(access_token, refresh_token)
        try:
            response = (
                client.table(self.artifacts_table)
                .select("id,workflow_run_id,artifact_type,filename_stem,storage_path,created_at")
                .eq("workflow_run_id", workflow_run_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not load recent artifact history.",
                details=str(exc),
            ) from exc
        return [
            ArtifactRecord(
                id=str(row.get("id", "")),
                workflow_run_id=str(row.get("workflow_run_id", workflow_run_id)),
                artifact_type=str(row.get("artifact_type", "")),
                filename_stem=str(row.get("filename_stem", "")),
                storage_path=str(row.get("storage_path", "")),
                created_at=str(row.get("created_at", "")),
            )
            for row in (getattr(response, "data", None) or [])
        ]

    def _client(self, access_token: str, refresh_token: str):
        if not self.is_configured():
            raise AppError("History persistence is not configured.")
        return self.auth_service.create_authenticated_client(access_token, refresh_token)