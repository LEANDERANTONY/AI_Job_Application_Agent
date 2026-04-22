from typing import Optional

from fastapi import Header


def get_optional_auth_tokens(
    x_auth_access_token: Optional[str] = Header(default=None, alias="X-Auth-Access-Token"),
    x_auth_refresh_token: Optional[str] = Header(default=None, alias="X-Auth-Refresh-Token"),
):
    access_token = str(x_auth_access_token or "").strip() or None
    refresh_token = str(x_auth_refresh_token or "").strip() or None
    return access_token, refresh_token
