from fastapi import APIRouter

router = APIRouter(prefix="/infiltrate", tags=["infiltrate"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"module": "infiltrate"}
