"""Authentication endpoints: /api/v1/auth/*"""

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentAuth, CurrentUser, DbSession
from app.repositories.users import UserRepository
from app.schemas.auth import (
    LoginRequest,
    MembershipSummary,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_ERRORS = {401: {"description": "Missing, invalid, expired or revoked token"}}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Email already registered"}},
)
def register(payload: RegisterRequest, db: DbSession) -> UserResponse:
    """Create a platform user account. The new user belongs to no organization yet."""
    user = AuthService(db).register(
        email=payload.email,
        password=payload.password.get_secret_value(),
        full_name=payload.full_name,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"description": "Invalid email or password"}},
)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    """Exchange email and password for a bearer access token."""
    token = AuthService(db).login(email=payload.email, password=payload.password.get_secret_value())
    return TokenResponse(access_token=token.token, expires_in=token.expires_in)


@router.get("/me", response_model=MeResponse, responses=_AUTH_ERRORS)
def me(user: CurrentUser, db: DbSession) -> MeResponse:
    """The authenticated user and the organizations they belong to."""
    memberships = [
        MembershipSummary(
            organization_id=m.organization_id,
            organization_name=m.organization.name,
            organization_slug=m.organization.slug,
            role=m.role,
        )
        for m in UserRepository(db).list_memberships(user.id)
    ]
    return MeResponse(**UserResponse.model_validate(user).model_dump(), memberships=memberships)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses=_AUTH_ERRORS)
def logout(auth: CurrentAuth, db: DbSession) -> Response:
    """Revoke the current access token. Any later request using it gets 401."""
    AuthService(db).logout(auth.claims)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
