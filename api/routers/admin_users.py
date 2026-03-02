"""
Admin user management router.
Only accessible by admin users.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.user_management import create_user, delete_user, list_users

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


@router.post("/users")
async def create_user_endpoint(request: Request, body: CreateUserRequest):
    """Create a new user (admin only)."""
    # Check if current user is admin
    if not getattr(request.state, "is_admin", False):
        # Also check from JWT payload
        user_id = getattr(request.state, "user_id", None)
        if user_id != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

    if not body.username or not body.password:
        raise HTTPException(
            status_code=400, detail="Username and password are required"
        )

    if len(body.username) < 2:
        raise HTTPException(
            status_code=400, detail="Username must be at least 2 characters"
        )

    if len(body.password) < 4:
        raise HTTPException(
            status_code=400, detail="Password must be at least 4 characters"
        )

    try:
        user = await create_user(body.username, body.password, body.is_admin)
        return {"message": f"User '{body.username}' created successfully", "user": user}
    except Exception as e:
        if "already contains" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(
                status_code=409, detail=f"User '{body.username}' already exists"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def list_users_endpoint(request: Request):
    """List all users (admin only)."""
    user_id = getattr(request.state, "user_id", None)
    if user_id != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    users = await list_users()
    return {"users": users}


@router.delete("/users/{username}")
async def delete_user_endpoint(request: Request, username: str):
    """Delete a user (admin only). Cannot delete admin."""
    user_id = getattr(request.state, "user_id", None)
    if user_id != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete admin user")

    success = await delete_user(username)
    if success:
        return {"message": f"User '{username}' deleted successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to delete user")
