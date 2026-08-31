from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_access_token, verify_password
from app.db import get_db
from app.models.entities import User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


class LoginPayload(BaseModel):
    username: str
    password: str


class UserProfileResponse(BaseModel):
    id: int
    username: str
    full_name: str
    email: Optional[str] = None
    is_admin: bool


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Obtiene el usuario actual a partir de la cookie de sesión, o None si no está autenticado."""
    cookie_token = request.cookies.get(settings.session_cookie_name)
    if not cookie_token:
        # Alternativa: Header Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            cookie_token = auth_header.split(" ", 1)[1]

    if not cookie_token:
        return None

    payload = verify_access_token(cookie_token)
    if not payload or "user_id" not in payload:
        return None

    user = db.get(User, payload["user_id"])
    if not user or not user.active:
        return None
    return user


def require_authenticated_user(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Exige que el usuario esté autenticado. Lanza HTTP 401 si no lo está."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión no válida o expirada. Inicie sesión para continuar.",
        )
    return current_user


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    """Página de inicio de sesión. Si ya está autenticado, redirige al dashboard."""
    if current_user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"app_name": settings.app_name},
    )


@router.post("/api/auth/login")
def login_api(payload: LoginPayload, response: Response, db: Session = Depends(get_db)):
    """Endpoint de autenticación por usuario y contraseña."""
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas o usuario inactivo.",
        )

    token = create_access_token(user.id, user.username)

    # Configurar cookie segura de sesión
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=False,  # En HTTPS se delega o adapta al entorno
        path="/",
    )

    return {
        "status": "ok",
        "message": "Autenticación exitosa",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
        },
        "token": token,
    }


@router.get("/logout")
@router.post("/api/auth/logout")
def logout(response: Response):
    """Cierra la sesión activa eliminando la cookie."""
    redirect = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(settings.session_cookie_name, path="/")
    return redirect


@router.get("/api/auth/me", response_model=UserProfileResponse)
def me(current_user: User = Depends(require_authenticated_user)):
    """Retorna los datos del usuario autenticado."""
    return UserProfileResponse(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        email=current_user.email,
        is_admin=current_user.is_admin,
    )
