from fastapi import APIRouter

router = APIRouter(tags=["root"])


@router.get("/")
def root():
    return {"message": "Hello FastAPI"}
