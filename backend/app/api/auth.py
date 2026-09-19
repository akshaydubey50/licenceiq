"""Typed authentication routes, mounted only by application composition."""

from typing import Annotated, cast

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.auth import AUTHENTICATION_FAILED, AuthenticationError, AuthService
from app.schemas.auth import AccessTokenResponse, AuthenticatedUser, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth_service)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AUTHENTICATION_FAILED,
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=AccessTokenResponse)
def login(request: Request, credentials: LoginRequest) -> JSONResponse:
    """Exchange configured bootstrap credentials for a short-lived access token."""
    try:
        token = _auth_service(request).login(credentials)
    except AuthenticationError:
        raise _unauthorized() from None
    return JSONResponse(
        content=token.model_dump(mode="json"),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def require_authenticated_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """FastAPI dependency for routes that require a valid JWT bearer token."""
    try:
        return _auth_service(request).authenticate_authorization(authorization)
    except AuthenticationError:
        raise _unauthorized() from None
