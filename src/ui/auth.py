from src.auth_service import AuthService
from src.ui.state import get_state, set_state


AUTH_SERVICE = "_auth_service"


def get_auth_service(auth_service_factory=AuthService) -> AuthService:
    auth_service = get_state(AUTH_SERVICE)
    if auth_service is None:
        auth_service = auth_service_factory()
        set_state(AUTH_SERVICE, auth_service)
    return auth_service