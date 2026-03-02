"""
Multi-user JWT authentication middleware and utilities.

Replaces the single-password PasswordAuthMiddleware with per-user
JWT-based authentication. Uses Python stdlib only (no PyJWT/bcrypt).
"""

import base64
import contextvars
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# ──────────────────────────────────────────────────────────────
# Context variables — available to db_connection() downstream
# ──────────────────────────────────────────────────────────────
current_user_db = contextvars.ContextVar("current_user_db", default=None)
current_user_id = contextvars.ContextVar("current_user_id", default=None)

# ──────────────────────────────────────────────────────────────
# JWT helpers (stdlib-only, HS256)
# ──────────────────────────────────────────────────────────────
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 86400 * 7  # 7 days


def _get_jwt_secret() -> str:
    """Use OPEN_NOTEBOOK_ENCRYPTION_KEY as the JWT signing secret."""
    secret = os.getenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "")
    if not secret:
        secret = "open-notebook-default-jwt-secret"
    return secret


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_jwt(payload: dict) -> str:
    """Create a minimal HS256 JWT token."""
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload = {**payload, "exp": int(time.time()) + JWT_EXPIRY_SECONDS}

    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = f"{segments[0]}.{segments[1]}".encode()
    signature = hmac.new(
        _get_jwt_secret().encode(), signing_input, hashlib.sha256
    ).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


def decode_jwt(token: str) -> Optional[dict]:
    """Decode and verify a JWT token. Returns None on failure."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        signing_input = f"{parts[0]}.{parts[1]}".encode()
        expected_sig = hmac.new(
            _get_jwt_secret().encode(), signing_input, hashlib.sha256
        ).digest()
        actual_sig = _b64url_decode(parts[2])

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(parts[1]))

        # Check expiry
        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# Password hashing (stdlib PBKDF2)
# ──────────────────────────────────────────────────────────────
_HASH_ITERATIONS = 260_000
_SALT_LENGTH = 16


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256. Returns 'salt:hash' hex string."""
    salt = os.urandom(_SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _HASH_ITERATIONS)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored 'salt:hash' string."""
    try:
        salt_hex, hash_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _HASH_ITERATIONS)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Multi-user JWT auth middleware
# ──────────────────────────────────────────────────────────────
class MultiUserAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for multi-user JWT authentication.

    On each request:
    1. Extracts Bearer token from Authorization header
    2. Decodes JWT to get user_id and db_name
    3. Sets contextvars so db_connection() routes to the correct database
    """

    def __init__(self, app, excluded_paths: Optional[list] = None):
        super().__init__(app)
        self.excluded_paths = excluded_paths or [
            "/",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(self, request: Request, call_next):
        # Skip for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # Skip CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            scheme, token = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                raise ValueError("Invalid scheme")
        except ValueError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authorization header format"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Decode JWT
        payload = decode_jwt(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload.get("user_id")
        db_name = payload.get("db_name")

        if not user_id or not db_name:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token payload"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Set context variables for downstream db_connection()
        token_user_db = current_user_db.set(db_name)
        token_user_id = current_user_id.set(user_id)

        # Also set on request.state for router access
        request.state.user_id = user_id
        request.state.db_name = db_name

        try:
            response = await call_next(request)
            return response
        finally:
            # Reset context variables
            current_user_db.reset(token_user_db)
            current_user_id.reset(token_user_id)
