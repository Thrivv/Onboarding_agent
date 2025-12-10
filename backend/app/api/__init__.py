from fastapi import APIRouter
from app.api.routes.register import router as register_router
from app.api.routes.chatupload import router as chatupload_router

api_router = APIRouter()

# Include all route modules
api_router.include_router(register_router, tags=["Registration"])
api_router.include_router(chatupload_router, tags=["Chat & Upload"])
