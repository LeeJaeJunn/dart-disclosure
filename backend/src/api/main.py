from fastapi import APIRouter

from src.api.routes import chat, qa, root

api_router = APIRouter()
api_router.include_router(root.router)
api_router.include_router(chat.router)
api_router.include_router(qa.router)
