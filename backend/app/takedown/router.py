from fastapi import APIRouter

router = APIRouter(prefix="/takedown", tags=["takedown"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"module": "takedown"}
