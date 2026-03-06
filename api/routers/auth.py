"""
Authentication router for Open Notebook API.
Provides login endpoint and auth status check.
"""

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.user_management import authenticate_user, generate_login_token, change_password, create_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    username: str
    current_password: str
    new_password: str


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


@router.post("/change-password")
async def change_password_endpoint(request: ChangePasswordRequest):
    """
    Change a user's password. Requires current username and password for verification.
    """
    if not request.new_password.strip():
        raise HTTPException(status_code=400, detail="New password cannot be empty")

    success = await change_password(
        request.username, request.current_password, request.new_password
    )

    if not success:
        raise HTTPException(status_code=401, detail="Invalid username or current password")

    logger.info(f"Password changed for user '{request.username}'")
    return {"message": "Password changed successfully"}


class RegisterRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(request: RegisterRequest):
    """
    Register a new normal user (non-admin). Public endpoint.
    """
    if not request.username or not request.username.strip():
        raise HTTPException(status_code=400, detail="Username is required")

    if len(request.username.strip()) < 2:
        raise HTTPException(
            status_code=400, detail="Username must be at least 2 characters"
        )

    if not request.password or len(request.password) < 4:
        raise HTTPException(
            status_code=400, detail="Password must be at least 4 characters"
        )

    try:
        user = await create_user(request.username.strip(), request.password, is_admin=False)
        logger.info(f"New user '{request.username}' registered via self-registration")
        return {"message": f"User '{request.username}' registered successfully", "user": user}
    except Exception as e:
        if "already contains" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(
                status_code=409, detail=f"User '{request.username}' already exists"
            )
        raise HTTPException(status_code=500, detail=str(e))