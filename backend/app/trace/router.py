from fastapi import APIRouter

router = APIRouter(prefix="/trace", tags=["trace"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"module": "trace"}
