"""
Deep Research API Router.

Provides background deep research execution with polling for status.
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.database.repository import repo_query, ensure_record_id, get_current_user_db, set_current_user_db, admin_repo_query
from open_notebook.exceptions import OpenNotebookError
from open_notebook.graphs.deep_research import graph as deep_research_graph
from open_notebook.utils.error_classifier import classify_error

router = APIRouter()

# Track running background tasks by job_id for cancellation
_running_tasks: Dict[str, asyncio.Task] = {}


async def _get_max_concurrent_tasks() -> int:
    """Read per-user max concurrent tasks setting from admin DB."""
    try:
        result = await admin_repo_query(
            "SELECT deep_research_max_concurrent_tasks FROM open_notebook:content_settings"
        )
        logger.info(f"_get_max_concurrent_tasks: raw result={result}")
        if result and result[0]:
            val = result[0].get("deep_research_max_concurrent_tasks") or 5
            logger.info(f"_get_max_concurrent_tasks: returning {val}")
            return val
    except Exception as e:
        logger.error(f"_get_max_concurrent_tasks failed: {e}")
    logger.warning("_get_max_concurrent_tasks: falling back to default 5")
    return 5


# ──────────────────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────────────────


class DeepResearchRequest(BaseModel):
    question: str = Field(..., description="Research question")
    notebook_id: Optional[str] = Field(None, description="Notebook ID to scope search")
    session_id: Optional[str] = Field(None, description="Chat session ID to associate with")
    model_id: Optional[str] = Field(None, description="Optional model override")
    research_type: str = Field("deep", description="Research type: 'deep' or 'quick'")


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


class DeepResearchJobListItem(BaseModel):
    job_id: str
    question: str
    status: str
    notebook_name: Optional[str] = None
    notebook_id: Optional[str] = None
    created: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# Background execution
# ──────────────────────────────────────────────────────────────────────


async def _save_report_to_chat_history(
    session_id: str, question: str, report: str, research_type: str = "deep"
) -> bool:
    """Save Deep Research query+report as chat messages in LangGraph session state.

    Returns True if saved successfully, False otherwise.
    """
    try:
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain_core.runnables import RunnableConfig
        from open_notebook.graphs.chat import graph as chat_graph

        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        thread_config = RunnableConfig(
            configurable={"thread_id": full_session_id}
        )

        # Add the user question as a HumanMessage
        await asyncio.to_thread(
            chat_graph.update_state,
            thread_config,
            {"messages": [HumanMessage(content=question)]},
        )

        # Add the report as an AIMessage (prefixed to distinguish from regular chat)
        report_content = f"[{'Quick' if research_type == 'quick' else 'Deep'} Research]\n\n{report}"
        await asyncio.to_thread(
            chat_graph.update_state,
            thread_config,
            {"messages": [AIMessage(content=report_content)]},
        )

        logger.info(
            f"Saved Deep Research report to chat history for session {session_id}"
        )
        return True
    except Exception as e:
        # Non-fatal: log but don't fail the job
        logger.warning(
            f"Failed to save Deep Research report to chat history: {e}"
        )
        return False


async def _run_deep_research_background(
    job_id: str, question: str, notebook_id: Optional[str], model_id: Optional[str], user_db: Optional[str],
    session_id: Optional[str] = None, research_type: str = "deep",
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
                "research_type": research_type,
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
            # Save query + report as chat messages in LangGraph session state
            if session_id:
                saved = await _save_report_to_chat_history(session_id, question, final_report, research_type)
                if saved:
                    # Mark as saved so getActiveDeepResearch won't reload it as a card
                    await repo_query(
                        "UPDATE $job_id SET status = 'saved_to_chat', updated = time::now()",
                        {"job_id": ensure_record_id(job_id)},
                    )
        else:
            await repo_query(
                "UPDATE $job_id SET status = 'completed', updated = time::now()",
                {"job_id": ensure_record_id(job_id)},
            )

        logger.info(f"{research_type.capitalize()} Research job {job_id} completed successfully")

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

    # Per-user concurrent task limit
    max_tasks = await _get_max_concurrent_tasks()
    running_result = await repo_query(
        "SELECT count() FROM deep_research_job WHERE status NOT IN ['completed', 'failed', 'cancelled', 'saved_to_chat'] GROUP ALL"
    )
    logger.info(f"Deep Research limit check: raw_result={running_result}, max_tasks={max_tasks}")
    running_count = running_result[0].get("count", 0) if running_result else 0
    logger.info(f"Deep Research limit check: running_count={running_count}, max_tasks={max_tasks}")
    if running_count >= max_tasks:
        raise HTTPException(
            status_code=429,
            detail=f"您当前已有 {running_count} 个 Deep Research 任务正在进行中（上限 {max_tasks}），请等待完成后再试",
        )

    try:
        # Create job record in user's DB
        result = await repo_query(
            """
            CREATE deep_research_job SET
                question = $question,
                notebook_id = $notebook_id,
                session_id = $session_id,
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
                "session_id": request.session_id,
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
                job_id, request.question, request.notebook_id, request.model_id, user_db,
                session_id=request.session_id, research_type=request.research_type,
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


@router.get("/deep-research/jobs", response_model=List[DeepResearchJobListItem])
async def list_deep_research_jobs():
    """List all in-progress deep research jobs for the current user."""
    try:
        jobs = await repo_query(
            """
            SELECT
                id,
                question,
                status,
                notebook_id,
                created
            FROM deep_research_job
            WHERE status NOT IN ['completed', 'failed', 'cancelled', 'saved_to_chat']
            ORDER BY created DESC
            """
        )

        result = []
        for job in jobs:
            # Resolve notebook name
            notebook_name = None
            nb_id = job.get("notebook_id")
            if nb_id:
                try:
                    nb_result = await repo_query(
                        "SELECT name FROM $nb_id",
                        {"nb_id": ensure_record_id(nb_id)},
                    )
                    if nb_result and nb_result[0]:
                        notebook_name = nb_result[0].get("name")
                except Exception:
                    pass

            result.append(DeepResearchJobListItem(
                job_id=str(job["id"]),
                question=job.get("question", ""),
                status=job.get("status", "unknown"),
                notebook_name=notebook_name,
                notebook_id=nb_id,
                created=str(job["created"]) if job.get("created") else None,
            ))

        return result

    except Exception as e:
        logger.error(f"Failed to list deep research jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")


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
async def get_active_deep_research(notebook_id: str, session_id: Optional[str] = None):
    """Get the most recent running or completed deep research job for a notebook+session."""
    try:
        logger.info(f"Checking active deep research for notebook: {notebook_id}, session: {session_id}")

        if session_id:
            result = await repo_query(
                """
                SELECT * FROM deep_research_job
                WHERE notebook_id = $notebook_id AND session_id = $session_id
                ORDER BY created DESC
                LIMIT 1
                """,
                {"notebook_id": notebook_id, "session_id": session_id},
            )
        else:
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
            logger.info(f"No active deep research found for notebook: {notebook_id}, session: {session_id}")
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
