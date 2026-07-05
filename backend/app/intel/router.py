from fastapi import APIRouter

router = APIRouter(prefix="/intel", tags=["intel"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"module": "intel"}
