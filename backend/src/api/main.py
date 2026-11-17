from fastapi import APIRouter

from src.api.routes import chat, companies, filings, qa, root

api_router = APIRouter()
api_router.include_router(root.router)
api_router.include_router(chat.router)
api_router.include_router(qa.router)
api_router.include_router(companies.router)
api_router.include_router(filings.router)
