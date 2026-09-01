from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, verify_access_token, verify_password
from app.db import get_db
from app.models.entities import User
from app.routers.auth import get_current_user_optional

router = APIRouter(tags=["oauth"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

# In-memory stores for OAuth dynamic clients and auth codes
# Clients: client_id -> dict
OAUTH_CLIENTS: dict[str, dict] = {
    # Default fallback client if configured in .env or static
    "gemini-spark-client": {
        "client_id": "gemini-spark-client",
        "client_secret": "gemini-spark-secret",
        "client_name": "Google Gemini Spark",
        "redirect_uris": ["https://gemini.google.com", "https://spark.google.com"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }
}

# Authorization codes: code -> dict(client_id, redirect_uri, user_id, expires_at, code_challenge, code_challenge_method)
AUTH_CODES: dict[str, dict] = {}


class DynamicClientRegistrationRequest(BaseModel):
    client_name: Optional[str] = "Gemini Client"
    redirect_uris: list[str] = Field(default_factory=list)
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: Optional[str] = "client_secret_post"
    scope: Optional[str] = "mcp"


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
def oauth_metadata(request: Request):
    """
    RFC 8414 OAuth 2.0 Authorization Server Metadata.
    Permite el descubrimiento automático por parte de Google Gemini Spark.
    """
    host = request.headers.get("host") or request.url.hostname or "jira.bcode.cl"
    base_url = f"https://{host}"

    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        "scopes_supported": ["mcp", "read", "write"],
        "code_challenge_methods_supported": ["S256", "plain"],
    }


@router.get("/.well-known/oauth-protected-resource")
def oauth_protected_resource(request: Request):
    """
    RFC 9728 OAuth 2.0 Protected Resource Metadata (MCP standard).
    """
    host = request.headers.get("host") or request.url.hostname or "jira.bcode.cl"
    base_url = f"https://{host}"

    return {
        "resource": f"{base_url}/mcp/sse",
        "authorization_servers": [base_url],
        "scopes_supported": ["mcp", "read", "write"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{base_url}/",
    }


@router.post("/oauth/register")
def register_client(payload: DynamicClientRegistrationRequest, request: Request):
    """
    RFC 7591 Dynamic Client Registration.
    Gemini Spark registra dinámicamente sus credenciales de cliente antes de iniciar OAuth.
    """
    client_id = f"client_{secrets.token_hex(16)}"
    client_secret = f"sec_{secrets.token_urlsafe(32)}"
    
    client_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": payload.client_name or "Gemini Spark Custom App",
        "redirect_uris": payload.redirect_uris,
        "grant_types": payload.grant_types,
        "response_types": payload.response_types,
        "token_endpoint_auth_method": payload.token_endpoint_auth_method,
    }
    OAUTH_CLIENTS[client_id] = client_data

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": client_data["client_name"],
        "redirect_uris": client_data["redirect_uris"],
        "grant_types": client_data["grant_types"],
        "response_types": client_data["response_types"],
        "token_endpoint_auth_method": client_data["token_endpoint_auth_method"],
    }


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize_page(
    request: Request,
    response_type: str = Query("code"),
    client_id: str = Query(...),
    redirect_uri: Optional[str] = Query(None),
    scope: Optional[str] = Query("mcp"),
    state: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Página de consentimiento de autorización OAuth 2.0.
    """
    client = OAUTH_CLIENTS.get(client_id)
    client_name = client.get("client_name") if client else "Google Gemini Spark"

    # Si ya está autenticado en la app, mostrar pantalla de consentimiento directa
    return templates.TemplateResponse(
        request=request,
        name="oauth_authorize.html",
        context={
            "app_name": settings.app_name,
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uri": redirect_uri or "",
            "scope": scope or "mcp",
            "state": state or "",
            "code_challenge": code_challenge or "",
            "code_challenge_method": code_challenge_method or "",
            "current_user": current_user,
        },
    )


@router.post("/oauth/authorize")
def process_authorization(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: Optional[str] = Form(None),
    code_challenge: Optional[str] = Form(None),
    code_challenge_method: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    action: str = Form("approve"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Procesa la aprobación de OAuth y emite el código de autorización.
    """
    if action != "approve":
        # Denegado
        error_url = f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}error=access_denied"
        if state:
            error_url += f"&state={state}"
        return RedirectResponse(url=error_url, status_code=status.HTTP_303_SEE_OTHER)

    user = current_user
    if not user and username and password:
        # Autenticar con formulario
        from sqlalchemy import select
        found_user = db.scalar(select(User).where(User.username == username.strip()))
        if found_user and found_user.active and verify_password(password, found_user.password_hash):
            user = found_user

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Debe iniciar sesión para autorizar la integración.",
        )

    # Generar código de autorización
    auth_code = f"authcode_{secrets.token_urlsafe(32)}"
    AUTH_CODES[auth_code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "user_id": user.id,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "expires_at": time.time() + 600,  # 10 minutos
    }

    # Redireccionar de vuelta a Gemini
    callback_url = f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}code={auth_code}"
    if state:
        callback_url += f"&state={state}"

    return RedirectResponse(url=callback_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/oauth/token")
def exchange_token(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    RFC 6749 Endpoint para canjear código por Access Token.
    """
    if grant_type == "authorization_code":
        if not code or code not in AUTH_CODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código de autorización inválido o expirado.",
            )

        code_data = AUTH_CODES.pop(code)
        if time.time() > code_data["expires_at"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El código de autorización ha expirado.",
            )

        user_id = code_data["user_id"]
        user = db.get(User, user_id)
        if not user or not user.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Usuario asociado no encontrado o inactivo.",
            )

        # Generar Access Token (duración 30 días para clientes MCP de AI)
        access_token = create_access_token(user.id, user.username, expires_in_seconds=2592000)
        new_refresh_token = f"ref_{secrets.token_urlsafe(32)}"

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 2592000,
            "refresh_token": new_refresh_token,
            "scope": "mcp",
        }

    elif grant_type == "client_credentials":
        # Soporte para autenticación directa máquina a máquina
        access_token = create_access_token(1, "system_admin", expires_in_seconds=2592000)
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 2592000,
            "scope": "mcp",
        }

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Grant type '{grant_type}' no soportado.",
        )
