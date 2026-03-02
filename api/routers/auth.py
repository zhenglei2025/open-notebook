"""
Authentication router for Open Notebook API.
Provides login endpoint and auth status check.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.user_management import authenticate_user, generate_login_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    is_admin: bool


@router.post("/login")
async def login(request: LoginRequest) -> LoginResponse:
    """
    Authenticate user with username and password.
    Returns a JWT token on success.
    """
    user = await authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = generate_login_token(user)

    logger.info(f"User '{request.username}' logged in successfully")

    return LoginResponse(
        token=token,
        username=user["username"],
        is_admin=user.get("is_admin", False),
    )


@router.get("/status")
async def get_auth_status():
    """
    Check authentication status.
    Multi-user mode is always enabled.
    """
    return {
        "auth_enabled": True,
        "multi_user": True,
        "message": "Multi-user authentication is enabled",
    }