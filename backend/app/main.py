from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import get_settings
from app.core.migrations import upgrade_database
from app.services.mcp import get_mcp_manager

settings = get_settings()
app = FastAPI(title="KNOWNEST Python", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Filename"])
app.include_router(router, prefix=settings.api_prefix)


@app.on_event("startup")
def startup() -> None:
    settings.validate_runtime_configuration()
    upgrade_database()


@app.on_event("shutdown")
async def shutdown() -> None:
    await get_mcp_manager().close_all()
