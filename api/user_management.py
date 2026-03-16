"""
Admin user management API.

Stores user records in a dedicated 'admin' database within SurrealDB.
Users table schema:
    - username (string, unique)
    - password_hash (string, PBKDF2)
    - db_name (string, the SurrealDB database for this user's data)
    - created (datetime)
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from surrealdb import AsyncSurreal

from api.user_auth import create_jwt, hash_password, verify_password
from open_notebook.database.repository import (
    get_database_password,
    get_database_url,
    parse_record_ids,
)

ADMIN_DB_NAME = "admin"


@asynccontextmanager
async def admin_db_connection():
    """Connect to the admin database (user accounts)."""
    db = AsyncSurreal(get_database_url())
    await db.signin(
        {
            "username": os.environ.get("SURREAL_USER"),
            "password": get_database_password(),
        }
    )
    await db.use(os.environ.get("SURREAL_NAMESPACE", "open_notebook"), ADMIN_DB_NAME)
    try:
        yield db
    finally:
        await db.close()


async def init_admin_db():
    """Initialize the admin database with users table and default admin user."""
    async with admin_db_connection() as db:
        # Create users table
        await db.query(
            """
            DEFINE TABLE IF NOT EXISTS users SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS username ON TABLE users TYPE string;
            DEFINE FIELD IF NOT EXISTS password_hash ON TABLE users TYPE string;
            DEFINE FIELD IF NOT EXISTS db_name ON TABLE users TYPE string;
            DEFINE FIELD IF NOT EXISTS is_admin ON TABLE users TYPE bool DEFAULT false;
            DEFINE FIELD IF NOT EXISTS created ON TABLE users TYPE datetime
                DEFAULT time::now() VALUE $before OR time::now();
            DEFINE INDEX IF NOT EXISTS idx_users_username ON TABLE users
                COLUMNS username UNIQUE;
            """
        )

        # Check if admin user exists
        result = parse_record_ids(
            await db.query(
                "SELECT * FROM users WHERE username = $username",
                {"username": "admin"},
            )
        )

        # result is a list of query results; first result is the SELECT
        admin_exists = False
        if result and isinstance(result, list):
            for r in result:
                if isinstance(r, list) and len(r) > 0:
                    admin_exists = True
                elif isinstance(r, dict) and r.get("username"):
                    admin_exists = True

        if not admin_exists:
            # Get the current database name from env — this is where existing data lives
            existing_db = os.environ.get("SURREAL_DATABASE", "open_notebook")
            admin_password = os.getenv("ADMIN_PASSWORD", "admin")

            await db.query(
                """
                CREATE users SET
                    username = $username,
                    password_hash = $password_hash,
                    db_name = $db_name,
                    is_admin = true,
                    created = time::now()
                """,
                {
                    "username": "admin",
                    "password_hash": hash_password(admin_password),
                    "db_name": existing_db,
                    "is_admin": True,
                },
            )
            logger.info(
                f"Created default admin user (db_name={existing_db}). "
                f"Password: from ADMIN_PASSWORD env or 'admin'"
            )


async def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """
    Authenticate a user by username and password.
    Returns user dict on success, None on failure.
    """
    async with admin_db_connection() as db:
        result = parse_record_ids(
            await db.query(
                "SELECT * FROM users WHERE username = $username",
                {"username": username},
            )
        )

        user = None
        if result and isinstance(result, list):
            for r in result:
                if isinstance(r, list) and len(r) > 0:
                    user = r[0]
                    break
                elif isinstance(r, dict) and r.get("username"):
                    user = r
                    break

        if not user:
            return None

        if not verify_password(password, user.get("password_hash", "")):
            return None

        return user


async def change_password(username: str, current_password: str, new_password: str) -> bool:
    """
    Change a user's password after verifying their current credentials.
    Returns True on success, False if authentication fails.
    """
    # First authenticate with current credentials
    user = await authenticate_user(username, current_password)
    if not user:
        return False

    # Update password
    new_hash = hash_password(new_password)
    async with admin_db_connection() as db:
        await db.query(
            "UPDATE users SET password_hash = $hash WHERE username = $username",
            {"hash": new_hash, "username": username},
        )

    logger.info(f"Password changed for user '{username}'")
    return True


async def create_user(
    username: str, password: str, is_admin: bool = False
) -> Dict[str, Any]:
    """Create a new user. Returns the created user dict."""
    db_name = f"user_{username}"

    async with admin_db_connection() as db:
        result = parse_record_ids(
            await db.query(
                """
                CREATE users SET
                    username = $username,
                    password_hash = $password_hash,
                    db_name = $db_name,
                    is_admin = $is_admin,
                    created = time::now()
                """,
                {
                    "username": username,
                    "password_hash": hash_password(password),
                    "db_name": db_name,
                    "is_admin": is_admin,
                },
            )
        )

        logger.info(f"Created user '{username}' with db_name='{db_name}'")

    # Run database migrations for the new user's database
    # This creates the schema, tables, and functions (like fn::vector_search)
    await _init_user_database(db_name)

    # Return simplified user info
    return {
        "username": username,
        "db_name": db_name,
        "is_admin": is_admin,
    }


async def _init_user_database(db_name: str) -> None:
    """Run all migrations for a new user's database.

    This ensures the user's database has all required schema, tables,
    and functions (like fn::vector_search, fn::text_search).
    """
    from open_notebook.database.repository import set_current_user_db

    logger.info(f"Initializing database '{db_name}' with migrations...")

    # Temporarily set user DB context so db_connection() routes to this database
    previous_db = None
    try:
        from api.user_auth import current_user_db
        previous_db = current_user_db.get()
    except Exception:
        pass

    try:
        set_current_user_db(db_name)

        from open_notebook.database.async_migrate import AsyncMigrationManager
        manager = AsyncMigrationManager()
        await manager.run_migration_up()
        logger.info(f"Successfully initialized database '{db_name}'")
    except Exception as e:
        logger.error(f"Failed to initialize database '{db_name}': {e}")
        raise
    finally:
        # Restore previous context
        set_current_user_db(previous_db)


async def init_all_user_databases() -> None:
    """Run pending migrations for all existing user databases.

    Called at startup to ensure all user databases have the required
    schema, tables, and functions (e.g., fn::vector_search).
    Skips the admin/default database since it's already migrated by the
    main migration manager.
    """
    default_db = os.environ.get("SURREAL_DATABASE", "open_notebook")

    async with admin_db_connection() as db:
        result = parse_record_ids(
            await db.query("SELECT db_name FROM users")
        )

        user_dbs: set[str] = set()
        if result and isinstance(result, list):
            for r in result:
                if isinstance(r, list):
                    for item in r:
                        if isinstance(item, dict) and item.get("db_name"):
                            user_dbs.add(item["db_name"])
                elif isinstance(r, dict) and r.get("db_name"):
                    user_dbs.add(r["db_name"])

    for db_name in user_dbs:
        # Skip the default database (already migrated by main migration manager)
        if db_name == default_db:
            continue
        try:
            await _init_user_database(db_name)
        except Exception as e:
            logger.error(f"Failed to initialize user database '{db_name}': {e}")


async def list_users() -> List[Dict[str, Any]]:
    """List all users (without password hashes), including source/note counts."""
    async with admin_db_connection() as db:
        result = parse_record_ids(
            await db.query(
                "SELECT username, db_name, is_admin, created FROM users ORDER BY created"
            )
        )

        users = []
        if result and isinstance(result, list):
            for r in result:
                if isinstance(r, list):
                    users.extend(r)
                elif isinstance(r, dict):
                    users.append(r)

    # Query each user's database for source/note counts
    namespace = os.environ.get("SURREAL_NAMESPACE", "open_notebook")
    for user in users:
        db_name = user.get("db_name")
        if not db_name:
            user["source_count"] = 0
            user["note_count"] = 0
            continue
        try:
            user_db = AsyncSurreal(get_database_url())
            await user_db.signin(
                {
                    "username": os.environ.get("SURREAL_USER"),
                    "password": get_database_password(),
                }
            )
            await user_db.use(namespace, db_name)

            # Query source count
            source_result = parse_record_ids(
                await user_db.query("SELECT count() FROM source GROUP ALL")
            )
            # Query note count
            note_result = parse_record_ids(
                await user_db.query("SELECT count() FROM note GROUP ALL")
            )
            await user_db.close()

            def extract_count(result):
                if not result:
                    return 0
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, list) and len(item) > 0:
                            return item[0].get("count", 0)
                        elif isinstance(item, dict):
                            return item.get("count", 0)
                return 0

            user["source_count"] = extract_count(source_result)
            user["note_count"] = extract_count(note_result)
        except Exception as e:
            logger.warning(f"Failed to get stats for user '{user.get('username')}': {e}")
            user["source_count"] = 0
            user["note_count"] = 0

    return users


async def delete_user(username: str) -> bool:
    """Delete a user by username. Cannot delete admin."""
    if username == "admin":
        return False

    async with admin_db_connection() as db:
        await db.query(
            "DELETE FROM users WHERE username = $username",
            {"username": username},
        )
        logger.info(f"Deleted user '{username}'")
        return True


def generate_login_token(user: Dict[str, Any]) -> str:
    """Generate a JWT token for authenticated user."""
    return create_jwt(
        {
            "user_id": user["username"],
            "db_name": user["db_name"],
            "is_admin": user.get("is_admin", False),
        }
    )
