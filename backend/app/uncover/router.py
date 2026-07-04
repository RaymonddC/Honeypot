from fastapi import APIRouter

router = APIRouter(prefix="/uncover", tags=["uncover"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"module": "uncover"}
