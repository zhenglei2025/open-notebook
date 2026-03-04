"""
Deep Research API Router.

Provides SSE streaming endpoint for the deep research agent.
Kept in a separate file to avoid merge conflicts with other changes.
"""

import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.exceptions import OpenNotebookError
from open_notebook.graphs.deep_research import graph as deep_research_graph

router = APIRouter()


class DeepResearchRequest(BaseModel):
    question: str = Field(..., description="Research question")
    notebook_id: Optional[str] = Field(None, description="Notebook ID to scope search")
    model_id: Optional[str] = Field(None, description="Optional model override")


class DeepResearchResponse(BaseModel):
    report: str = Field(..., description="Final research report")
    question: str = Field(..., description="Original question")


async def stream_deep_research(question: str, notebook_id: Optional[str] = None, model_id: Optional[str] = None) -> AsyncGenerator[str, None]:
    """Stream deep research progress as Server-Sent Events."""
    try:
        config = {}
        if model_id:
            config = {"configurable": {"model_id": model_id}}

        seen_events = 0

        async for chunk in deep_research_graph.astream(
            input={
                "question": question,
                "notebook_id": notebook_id,
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
            stream_mode="updates",
        ):
            # Extract events from each node's output
            for node_name, node_output in chunk.items():
                if "events" in node_output:
                    events = node_output["events"]
                    # Only send new events
                    new_events = events[seen_events:]
                    seen_events = len(events)
                    for event in new_events:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                # If this is the final report, send it
                if "final_report" in node_output and node_output["final_report"]:
                    yield f"data: {json.dumps({'type': 'report', 'content': node_output['final_report']}, ensure_ascii=False)}\n\n"

        # Send completion signal
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except OpenNotebookError as e:
        logger.error(f"Deep research error: {str(e)}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    except Exception as e:
        from open_notebook.utils.error_classifier import classify_error
        _, user_message = classify_error(e)
        logger.error(f"Deep research unexpected error: {str(e)}")
        yield f"data: {json.dumps({'type': 'error', 'message': user_message}, ensure_ascii=False)}\n\n"


@router.post("/deep-research")
async def deep_research(request: DeepResearchRequest):
    """Start a deep research session with SSE streaming."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    return StreamingResponse(
        stream_deep_research(request.question, request.notebook_id, request.model_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/deep-research/simple", response_model=DeepResearchResponse)
async def deep_research_simple(request: DeepResearchRequest):
    """Run deep research and return the final report (non-streaming)."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        config = {}
        if request.model_id:
            config = {"configurable": {"model_id": request.model_id}}

        result = await deep_research_graph.ainvoke(
            input={
                "question": request.question,
                "notebook_id": request.notebook_id,
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

        report = result.get("final_report", "")
        if not report:
            raise HTTPException(status_code=500, detail="No report generated")

        return DeepResearchResponse(report=report, question=request.question)

    except OpenNotebookError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Deep research error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Deep research failed: {str(e)}")
