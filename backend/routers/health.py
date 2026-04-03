from fastapi import APIRouter

from backend.config import get_backend_settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    settings = get_backend_settings()
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "providers": {
            "greenhouse": {
                "configured": settings.greenhouse_board_count > 0,
                "board_count": settings.greenhouse_board_count,
            },
            "lever": {
                "configured": settings.lever_site_count > 0,
                "site_count": settings.lever_site_count,
            },
        },
    }
