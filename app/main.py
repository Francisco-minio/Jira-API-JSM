from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.scheduler import shutdown_scheduler, start_scheduler
from app.core.security import init_admin_user
from app.db import Base, SessionLocal, engine
from app.routers.api import router as api_router
from app.routers.auth import router as auth_router
from app.routers.oauth import router as oauth_router
from app.routers.web import router as web_router
from app.mcp_server import mcp

settings = get_settings()
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Incluir routers
app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(web_router)
app.include_router(api_router)

# Montar el servidor MCP vía SSE
# Permite conectar clientes MCP vía https://dominio/mcp/sse o https://dominio/sse
mcp_app = mcp.sse_app()
app.mount("/mcp", mcp_app)
app.mount("/sse", mcp_app)


@app.on_event("startup")
def startup() -> None:
    db_initialized = False
    for attempt in range(1, 11):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Base de datos inicializada correctamente.")
            db_initialized = True
            break
        except Exception as e:
            logger.warning(f"Fallo al conectar a la BD (intento {attempt}/10): {e}")
            time.sleep(2)

    if not db_initialized:
        logger.error("No se pudo conectar a la base de datos tras 10 intentos. Reintentando por última vez.")
        Base.metadata.create_all(bind=engine)

    # Crear/asegurar usuario administrador inicial
    try:
        with SessionLocal() as db:
            admin = init_admin_user(db)
            if admin:
                logger.info(f"Usuario administrador verificado: {admin.username}")
    except Exception as e:
        logger.error(f"Error al inicializar usuario admin: {e}")

    # Inicializar y arrancar programador
    start_scheduler(settings.sync_interval_hours)


@app.on_event("shutdown")
def shutdown() -> None:
    shutdown_scheduler()
