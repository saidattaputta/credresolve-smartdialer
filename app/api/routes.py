from fastapi import APIRouter

router = APIRouter()


@router.get("/status", tags=["system"])
async def status():
    return {
        "application": "CredResolve SmartDialer",
        "version": "0.1.0",
        "dialing_modes": ["progressive", "predictive"],
        "status": "foundation",
    }
