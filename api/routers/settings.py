from fastapi import APIRouter, HTTPException
from loguru import logger

from api.models import SettingsResponse, SettingsUpdate
from open_notebook.database.repository import admin_repo_query

router = APIRouter()

# Default values for settings fields
_DEFAULTS = {
    "default_content_processing_engine_doc": "auto",
    "default_content_processing_engine_url": "auto",
    "default_embedding_option": "ask",
    "embedding_batch_size": 32,
    "embedding_chunk_size": 500,
    "auto_delete_files": "yes",
    "youtube_preferred_languages": ["en", "pt", "es", "de", "nl", "en-GB", "fr", "de", "hi", "ja"],
    "deep_research_max_search_rounds": 3,
    "deep_research_enable_context_expansion": True,
}


async def _get_admin_settings() -> dict:
    """Read settings from the shared admin DB."""
    try:
        result = await admin_repo_query(
            "SELECT * FROM ONLY open_notebook:content_settings"
        )
        if result:
            row = result[0] if isinstance(result, list) else result
            if isinstance(row, dict):
                return row
    except Exception as e:
        logger.warning(f"Failed to read settings from admin DB: {e}")
    return {}


async def _update_admin_settings(updates: dict) -> dict:
    """Write settings to the shared admin DB."""
    set_clauses = []
    params = {}
    for key, value in updates.items():
        set_clauses.append(f"{key} = ${key}")
        params[key] = value
    set_clauses.append("updated = time::now()")
    query = f"UPSERT open_notebook:content_settings SET {', '.join(set_clauses)}"
    result = await admin_repo_query(query, params)
    if result:
        row = result[0] if isinstance(result, list) else result
        if isinstance(row, dict):
            return row
    return {}


def _build_response(data: dict) -> SettingsResponse:
    """Build a SettingsResponse from raw DB data, applying defaults."""
    return SettingsResponse(
        default_content_processing_engine_doc=data.get(
            "default_content_processing_engine_doc",
            _DEFAULTS["default_content_processing_engine_doc"],
        ),
        default_content_processing_engine_url=data.get(
            "default_content_processing_engine_url",
            _DEFAULTS["default_content_processing_engine_url"],
        ),
        default_embedding_option=data.get(
            "default_embedding_option",
            _DEFAULTS["default_embedding_option"],
        ),
        embedding_batch_size=data.get(
            "embedding_batch_size",
            _DEFAULTS["embedding_batch_size"],
        ),
        embedding_chunk_size=data.get(
            "embedding_chunk_size",
            _DEFAULTS["embedding_chunk_size"],
        ),
        auto_delete_files=data.get(
            "auto_delete_files",
            _DEFAULTS["auto_delete_files"],
        ),
        youtube_preferred_languages=data.get(
            "youtube_preferred_languages",
            _DEFAULTS["youtube_preferred_languages"],
        ),
        deep_research_max_search_rounds=data.get(
            "deep_research_max_search_rounds",
            _DEFAULTS["deep_research_max_search_rounds"],
        ),
        deep_research_enable_context_expansion=data.get(
            "deep_research_enable_context_expansion",
            _DEFAULTS["deep_research_enable_context_expansion"],
        ),
    )


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Get all application settings (from shared admin DB)."""
    try:
        data = await _get_admin_settings()
        return _build_response(data)
    except Exception as e:
        logger.error(f"Error fetching settings: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Error fetching settings"
        )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(settings_update: SettingsUpdate):
    """Update application settings (in shared admin DB)."""
    try:
        # Build updates from provided fields only
        updates = {}
        if settings_update.default_content_processing_engine_doc is not None:
            updates["default_content_processing_engine_doc"] = settings_update.default_content_processing_engine_doc
        if settings_update.default_content_processing_engine_url is not None:
            updates["default_content_processing_engine_url"] = settings_update.default_content_processing_engine_url
        if settings_update.default_embedding_option is not None:
            updates["default_embedding_option"] = settings_update.default_embedding_option
        if settings_update.embedding_batch_size is not None:
            updates["embedding_batch_size"] = settings_update.embedding_batch_size
        if settings_update.embedding_chunk_size is not None:
            updates["embedding_chunk_size"] = settings_update.embedding_chunk_size
        if settings_update.auto_delete_files is not None:
            updates["auto_delete_files"] = settings_update.auto_delete_files
        if settings_update.youtube_preferred_languages is not None:
            updates["youtube_preferred_languages"] = settings_update.youtube_preferred_languages
        if settings_update.deep_research_max_search_rounds is not None:
            updates["deep_research_max_search_rounds"] = settings_update.deep_research_max_search_rounds
        if settings_update.deep_research_enable_context_expansion is not None:
            updates["deep_research_enable_context_expansion"] = settings_update.deep_research_enable_context_expansion

        if not updates:
            data = await _get_admin_settings()
            return _build_response(data)

        data = await _update_admin_settings(updates)
        return _build_response(data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Error updating settings"
        )
