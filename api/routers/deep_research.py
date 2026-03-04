"""
Deep Research API Router.

Provides background deep research execution with polling for status.
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.database.repository import repo_query, ensure_record_id, get_current_user_db, set_current_user_db
from open_notebook.exceptions import OpenNotebookError
from open_notebook.graphs.deep_research import graph as deep_research_graph
from open_notebook.utils.error_classifier import classify_error

router = APIRouter()

# Track running background tasks by job_id for cancellation
_running_tasks: Dict[str, asyncio.Task] = {}


# ──────────────────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────────────────


class DeepResearchRequest(BaseModel):
    question: str = Field(..., description="Research question")
    notebook_id: Optional[str] = Field(None, description="Notebook ID to scope search")
    model_id: Optional[str] = Field(None, description="Optional model override")


class DeepResearchJobResponse(BaseModel):
    job_id: str
    status: str
    question: str


class DeepResearchStatusResponse(BaseModel):
    job_id: str
    status: str
    question: str
    events: List[Dict[str, Any]] = []
    final_report: Optional[str] = None
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# Background execution
# ──────────────────────────────────────────────────────────────────────


async def _run_deep_research_background(
    job_id: str, question: str, notebook_id: Optional[str], model_id: Optional[str], user_db: Optional[str]
) -> None:
    """Run deep research graph in background, persisting results to DB."""
    # Explicitly restore user database context for the background task
    if user_db:
        set_current_user_db(user_db)
    try:
        config = {}
        if model_id:
            config = {"configurable": {"model_id": model_id}}

        result = await deep_research_graph.ainvoke(
            input={
                "question": question,
                "notebook_id": notebook_id,
                "job_id": job_id,
                "outline": None,
                "current_section_index": 0,
                "section_search_count": 0,
                "section_search_results": [],
                "current_queries": [],
                "is_material_sufficient": False,
                "section_drafts": [],
                "section_summaries": [],
                "final_report": "",
                "status": "",
                "events": [],
            },
            config=config,
        )

        # Final update (compile_report already persists, but ensure completion)
        final_report = result.get("final_report", "")
        if final_report:
            await repo_query(
                "UPDATE $job_id SET status = 'completed', final_report = $report, updated = time::now()",
                {"job_id": ensure_record_id(job_id), "report": final_report},
            )
        else:
            await repo_query(
                "UPDATE $job_id SET status = 'completed', updated = time::now()",
                {"job_id": ensure_record_id(job_id)},
            )

        logger.info(f"Deep Research job {job_id} completed successfully")

    except asyncio.CancelledError:
        logger.info(f"Deep Research job {job_id} was cancelled")
        await repo_query(
            "UPDATE $job_id SET status = 'cancelled', updated = time::now()",
            {"job_id": ensure_record_id(job_id)},
        )
    except OpenNotebookError as e:
        logger.error(f"Deep Research job {job_id} failed: {e}")
        await repo_query(
            "UPDATE $job_id SET status = 'failed', error = $error, updated = time::now()",
            {"job_id": ensure_record_id(job_id), "error": str(e)},
        )
    except Exception as e:
        _, user_message = classify_error(e)
        logger.error(f"Deep Research job {job_id} unexpected error: {e}")
        await repo_query(
            "UPDATE $job_id SET status = 'failed', error = $error, updated = time::now()",
            {"job_id": ensure_record_id(job_id), "error": user_message},
        )
    finally:
        _running_tasks.pop(job_id, None)


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/deep-research", response_model=DeepResearchJobResponse)
async def start_deep_research(request: DeepResearchRequest):
    """Start a deep research job in the background. Returns job_id immediately."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        # Create job record in user's DB
        result = await repo_query(
            """
            CREATE deep_research_job SET
                question = $question,
                notebook_id = $notebook_id,
                model_id = $model_id,
                status = 'running',
                events = [],
                final_report = NONE,
                error = NONE,
                created = time::now(),
                updated = time::now()
            """,
            {
                "question": request.question,
                "notebook_id": request.notebook_id,
                "model_id": request.model_id,
            },
        )

        if not result or not result[0].get("id"):
            raise HTTPException(status_code=500, detail="Failed to create research job")

        job_id = str(result[0]["id"])
        logger.info(f"Created deep research job: {job_id}")

        # Fire-and-forget background task — capture user DB context
        user_db = get_current_user_db()
        task = asyncio.create_task(
            _run_deep_research_background(
                job_id, request.question, request.notebook_id, request.model_id, user_db
            )
        )
        _running_tasks[job_id] = task

        return DeepResearchJobResponse(
            job_id=job_id,
            status="running",
            question=request.question,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start deep research: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start research: {str(e)}")


@router.post("/deep-research/{job_id}/cancel")
async def cancel_deep_research(job_id: str):
    """Cancel a running deep research job."""
    try:
        # Cancel the asyncio task if it's still running
        task = _running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled background task for job {job_id}")

        # Update DB status
        await repo_query(
            "UPDATE $job_id SET status = 'cancelled', updated = time::now()",
            {"job_id": ensure_record_id(job_id)},
        )

        return {"job_id": job_id, "status": "cancelled"}

    except Exception as e:
        logger.error(f"Failed to cancel deep research job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel: {str(e)}")


@router.get("/deep-research/active/{notebook_id}", response_model=Optional[DeepResearchStatusResponse])
async def get_active_deep_research(notebook_id: str):
    """Get the most recent running or completed deep research job for a notebook."""
    try:
        logger.info(f"Checking active deep research for notebook: {notebook_id}")
        result = await repo_query(
            """
            SELECT * FROM deep_research_job
            WHERE notebook_id = $notebook_id
            ORDER BY created DESC
            LIMIT 1
            """,
            {"notebook_id": notebook_id},
        )

        if not result:
            logger.info(f"No active deep research found for notebook: {notebook_id}")
            return None

        job = result[0]
        logger.info(f"Found active deep research job: {job.get('id')}, status: {job.get('status')}")
        return DeepResearchStatusResponse(
            job_id=str(job["id"]),
            status=job.get("status", "unknown"),
            question=job.get("question", ""),
            events=job.get("events") or [],
            final_report=job.get("final_report"),
            error=job.get("error"),
        )

    except Exception as e:
        logger.error(f"Failed to get active deep research: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get active research: {str(e)}")


@router.get("/deep-research/{job_id}", response_model=DeepResearchStatusResponse)
async def get_deep_research_status(job_id: str, events_after: int = 0):
    """Get status, events, and report for a deep research job.

    Args:
        job_id: The job record ID
        events_after: Only return events after this index (cursor-based pagination)
    """
    try:
        result = await repo_query(
            "SELECT * FROM $job_id",
            {"job_id": ensure_record_id(job_id)},
        )

        if not result:
            raise HTTPException(status_code=404, detail="Research job not found")

        job = result[0]
        all_events = job.get("events") or []

        # Return only new events if cursor provided
        events = all_events[events_after:] if events_after > 0 else all_events

        return DeepResearchStatusResponse(
            job_id=str(job["id"]),
            status=job.get("status", "unknown"),
            question=job.get("question", ""),
            events=events,
            final_report=job.get("final_report"),
            error=job.get("error"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deep research status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")
