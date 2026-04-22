import base64
import json
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from src.config import (
    SUPABASE_ANON_KEY,
    SUPABASE_AUTH_REDIRECT_URL,
    SUPABASE_URL,
)
from src.errors import AppError
from src.ui.state import (
    get_auth_pkce_code_verifier,
    get_request_cookie,
    set_auth_pkce_code_verifier,
)

try:
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions as ClientOptions
except ImportError:
    create_client = None
    ClientOptions = None


@dataclass
class AuthUser:
    user_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


@dataclass
class AuthSession:
    access_token: str
    refresh_token: str
    user: AuthUser


@dataclass
class AuthSignInRequest:
    url: str
    auth_flow: str
    cookie_name: str
    cookie_value: str
    cookie_max_age_seconds: int


class StreamlitSessionStorage:
    def get_item(self, key: str):
        if key.endswith("-code-verifier"):
            return get_auth_pkce_code_verifier()
        return None

    def set_item(self, key: str, value: str):
        if key.endswith("-code-verifier"):
            set_auth_pkce_code_verifier(value)

    def remove_item(self, key: str):
        if key.endswith("-code-verifier"):
            set_auth_pkce_code_verifier(None)


_PKCE_CODE_VERIFIER_CACHE: dict[str, str] = {}
_PKCE_COOKIE_NAME = "auth_pkce_flow"
_PKCE_COOKIE_MAX_AGE_SECONDS = 600
_PKCE_FLOW_STORE_PATH = Path(tempfile.gettempdir()) / "ai_job_application_agent_auth.sqlite3"
_PKCE_FLOW_TTL_SECONDS = 900


def _open_pkce_flow_store():
    connection = sqlite3.connect(_PKCE_FLOW_STORE_PATH, timeout=5)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pkce_flows (
            flow_id TEXT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    return connection


def _store_pkce_flow(flow_id: str, code_verifier: str):
    now = int(time.time())
    expires_before = now - _PKCE_FLOW_TTL_SECONDS
    with _open_pkce_flow_store() as connection:
        connection.execute(
            """
            INSERT INTO pkce_flows (flow_id, code_verifier, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(flow_id) DO UPDATE SET
                code_verifier = excluded.code_verifier,
                created_at = excluded.created_at
            """,
            (flow_id, code_verifier, now),
        )
        connection.execute("DELETE FROM pkce_flows WHERE created_at < ?", (expires_before,))


def _consume_pkce_flow(flow_id: str):
    expires_before = int(time.time()) - _PKCE_FLOW_TTL_SECONDS
    with _open_pkce_flow_store() as connection:
        connection.execute("DELETE FROM pkce_flows WHERE created_at < ?", (expires_before,))
        row = connection.execute(
            "SELECT code_verifier FROM pkce_flows WHERE flow_id = ?",
            (flow_id,),
        ).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM pkce_flows WHERE flow_id = ?", (flow_id,))
        return str(row[0])


def _consume_latest_pkce_flow():
    expires_before = int(time.time()) - _PKCE_FLOW_TTL_SECONDS
    with _open_pkce_flow_store() as connection:
        connection.execute("DELETE FROM pkce_flows WHERE created_at < ?", (expires_before,))
        row = connection.execute(
            """
            SELECT flow_id, code_verifier
            FROM pkce_flows
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM pkce_flows WHERE flow_id = ?", (str(row[0]),))
        return {
            "auth_flow": str(row[0]),
            "code_verifier": str(row[1]),
        }


def _serialize_pkce_cookie_payload(auth_flow: str, code_verifier: str):
    payload = json.dumps(
        {
            "auth_flow": auth_flow,
            "code_verifier": code_verifier,
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _deserialize_pkce_cookie_payload(cookie_value: Optional[str]):
    if not cookie_value:
        return None

    padding = "=" * (-len(cookie_value) % 4)
    try:
        payload = base64.urlsafe_b64decode(f"{cookie_value}{padding}").decode("utf-8")
        parsed = json.loads(payload)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(parsed, dict):
        return None

    auth_flow = parsed.get("auth_flow")
    code_verifier = parsed.get("code_verifier")
    if not auth_flow or not code_verifier:
        return None

    return {
        "auth_flow": str(auth_flow),
        "code_verifier": str(code_verifier),
    }


def _with_query_params(url: str, **params: str):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: value for key, value in params.items() if value is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class AuthService:
    def __init__(
        self,
        supabase_url: str = SUPABASE_URL,
        supabase_anon_key: str = SUPABASE_ANON_KEY,
        redirect_url: str = SUPABASE_AUTH_REDIRECT_URL,
        storage: Any | None = None,
    ):
        self.supabase_url = (supabase_url or "").strip()
        self.supabase_anon_key = (supabase_anon_key or "").strip()
        self.redirect_url = (redirect_url or "").strip()
        self.storage = storage

    def is_configured(self):
        return bool(self.supabase_url and self.supabase_anon_key)

    def get_google_sign_in_request(self):
        client = self._create_client()
        flow_id = uuid4().hex
        response = client.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {"redirect_to": _with_query_params(self.redirect_url, auth_flow=flow_id)},
            }
        )
        code_verifier = self._get_pkce_code_verifier()
        if not code_verifier:
            raise AppError("Unable to start Google sign-in right now.")
        _PKCE_CODE_VERIFIER_CACHE[flow_id] = code_verifier
        _store_pkce_flow(flow_id, code_verifier)
        url = self._extract_oauth_url(response)
        if not url:
            raise AppError("Unable to start Google sign-in right now.")
        return AuthSignInRequest(
            url=url,
            auth_flow=flow_id,
            cookie_name=_PKCE_COOKIE_NAME,
            cookie_value=_serialize_pkce_cookie_payload(flow_id, code_verifier),
            cookie_max_age_seconds=_PKCE_COOKIE_MAX_AGE_SECONDS,
        )

    def get_google_sign_in_url(self):
        return self.get_google_sign_in_request().url

    def exchange_code_for_session(self, auth_code: str, auth_flow: Optional[str] = None):
        redirect_to = self.redirect_url
        code_verifier = None
        cookie_payload = self._get_pkce_cookie_payload(auth_flow)
        if auth_flow:
            auth_flow = str(auth_flow)
            redirect_to = _with_query_params(self.redirect_url, auth_flow=auth_flow)
            code_verifier = _PKCE_CODE_VERIFIER_CACHE.pop(auth_flow, None)
            if not code_verifier:
                code_verifier = _consume_pkce_flow(auth_flow)
        if not code_verifier:
            code_verifier = self._get_pkce_code_verifier()
        if not code_verifier and cookie_payload:
            code_verifier = cookie_payload.get("code_verifier")
            if not auth_flow:
                auth_flow = cookie_payload.get("auth_flow")
                if auth_flow:
                    redirect_to = _with_query_params(self.redirect_url, auth_flow=auth_flow)
        if not code_verifier and not auth_flow:
            latest_flow = _consume_latest_pkce_flow()
            if latest_flow:
                auth_flow = latest_flow.get("auth_flow")
                code_verifier = latest_flow.get("code_verifier")
                if auth_flow:
                    redirect_to = _with_query_params(self.redirect_url, auth_flow=auth_flow)
        if not code_verifier:
            raise AppError("Google sign-in session expired. Start the sign-in flow again.")
        client = self._create_client()
        try:
            response = client.auth.exchange_code_for_session(
                {
                    "auth_code": auth_code,
                    "code_verifier": code_verifier,
                    "redirect_to": redirect_to,
                }
            )
        except TypeError:
            response = client.auth.exchange_code_for_session(auth_code)
        finally:
            self._clear_pkce_code_verifier()
        return self._build_auth_session(response)

    def restore_session(self, access_token: str, refresh_token: str):
        client = self.create_authenticated_client(access_token, refresh_token)
        response = client.auth.get_session()
        return self._build_auth_session(response)

    def sign_out(self, access_token: str, refresh_token: str):
        client = self.create_authenticated_client(access_token, refresh_token)
        client.auth.sign_out()

    def create_authenticated_client(self, access_token: str, refresh_token: str):
        client = self._create_client()
        try:
            client.auth.set_session(access_token, refresh_token)
        except TypeError:
            client.auth.set_session(
                {"access_token": access_token, "refresh_token": refresh_token}
            )
        return client

    def _create_client(self):
        if not self.is_configured():
            raise AppError(
                "Google sign-in is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY first."
            )
        if create_client is None or ClientOptions is None:
            raise AppError(
                "Supabase support is not installed. Add the supabase package to enable Google sign-in."
            )
        return create_client(
            self.supabase_url,
            self.supabase_anon_key,
            options=ClientOptions(
                flow_type="pkce",
                auto_refresh_token=False,
                persist_session=False,
                storage=self.storage if self.storage is not None else StreamlitSessionStorage(),
            ),
        )

    def _get_pkce_code_verifier(self):
        if self.storage is not None:
            try:
                return self.storage.get_item("auth-code-verifier")
            except Exception:
                return None
        return get_auth_pkce_code_verifier()

    def _clear_pkce_code_verifier(self):
        if self.storage is not None:
            try:
                self.storage.remove_item("auth-code-verifier")
            except Exception:
                return None
            return None
        return set_auth_pkce_code_verifier(None)

    @staticmethod
    def _get_pkce_cookie_payload(auth_flow: Optional[str] = None):
        payload = _deserialize_pkce_cookie_payload(get_request_cookie(_PKCE_COOKIE_NAME))
        if payload is None:
            return None
        if auth_flow and payload.get("auth_flow") != auth_flow:
            return None
        return payload

    @staticmethod
    def _extract_oauth_url(response: Any):
        candidates = [
            response,
            getattr(response, "data", None),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            if isinstance(candidate, dict) and candidate.get("url"):
                return candidate["url"]
            url = getattr(candidate, "url", None)
            if url:
                return url
        return None

    def _build_auth_session(self, response: Any):
        session = self._extract_session(response)
        user = self._extract_user(response, session)

        access_token = getattr(session, "access_token", None)
        refresh_token = getattr(session, "refresh_token", None)
        if not access_token or not refresh_token or user is None:
            raise AppError("Unable to complete Google sign-in right now.")

        return AuthSession(
            access_token=access_token,
            refresh_token=refresh_token,
            user=AuthUser(
                user_id=str(getattr(user, "id", "") or self._get_mapping_value(user, "id", "")),
                email=getattr(user, "email", None) or self._get_mapping_value(user, "email"),
                display_name=self._extract_display_name(user),
                avatar_url=self._extract_avatar_url(user),
            ),
        )

    @staticmethod
    def _extract_session(response: Any):
        candidates = [
            response if getattr(response, "access_token", None) else None,
            getattr(response, "session", None),
            getattr(getattr(response, "data", None), "session", None),
            AuthService._get_mapping_value(response, "session"),
            AuthService._get_mapping_value(getattr(response, "data", None), "session"),
        ]
        for candidate in candidates:
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _extract_user(response: Any, session: Any):
        candidates = [
            getattr(response, "user", None),
            getattr(getattr(response, "data", None), "user", None),
            getattr(session, "user", None),
            AuthService._get_mapping_value(response, "user"),
            AuthService._get_mapping_value(getattr(response, "data", None), "user"),
            AuthService._get_mapping_value(session, "user"),
        ]
        for candidate in candidates:
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _extract_display_name(user: Any):
        metadata = getattr(user, "user_metadata", None) or AuthService._get_mapping_value(
            user, "user_metadata", {}
        )
        if not isinstance(metadata, dict):
            return None
        return metadata.get("full_name") or metadata.get("name")

    @staticmethod
    def _extract_avatar_url(user: Any):
        metadata = getattr(user, "user_metadata", None) or AuthService._get_mapping_value(
            user, "user_metadata", {}
        )
        if not isinstance(metadata, dict):
            return None
        return metadata.get("avatar_url") or metadata.get("picture")

    @staticmethod
    def _get_mapping_value(value: Any, key: str, default=None):
        if isinstance(value, dict):
            return value.get(key, default)
        return default
