"""Typed authentication routes, mounted only by application composition."""

from typing import Annotated, cast

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.auth import (
    AUTHENTICATION_FAILED,
    REGISTRATION_FAILED,
    REGISTRATION_UNAVAILABLE,
    AuthenticationError,
    AuthService,
    RegistrationError,
    RegistrationUnavailableError,
)
from app.schemas.auth import AccessTokenResponse, AuthenticatedUser, LoginRequest, SignupRequest

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
    """Exchange bootstrap or local credentials for a short-lived access token."""
    try:
        token = _auth_service(request).login(credentials)
    except AuthenticationError:
        raise _unauthorized() from None
    return JSONResponse(
        content=token.model_dump(mode="json"),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post(
    "/signup",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(request: Request, credentials: SignupRequest) -> JSONResponse:
    """Create an enabled durable local account and its first revocable session."""
    try:
        token = _auth_service(request).signup(credentials)
    except RegistrationUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=REGISTRATION_UNAVAILABLE,
            headers={"Cache-Control": "no-store"},
        ) from None
    except RegistrationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=REGISTRATION_FAILED,
            headers={"Cache-Control": "no-store"},
        ) from None
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=token.model_dump(mode="json"),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, authorization: Annotated[str | None, Header()] = None) -> Response:
    """Revoke one durable JWT session without affecting other browser sessions."""
    try:
        _auth_service(request).logout(authorization)
    except AuthenticationError:
        raise _unauthorized() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


def require_authenticated_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """FastAPI dependency for routes that require a valid JWT bearer token."""
    try:
        return _auth_service(request).authenticate_authorization(authorization)
    except AuthenticationError:
        raise _unauthorized() from None
