"""
Deep Research Agent - LangGraph implementation.

A multi-step research agent that generates comprehensive reports by:
1. Planning an outline (agent decides section count)
2. For each section: search → evaluate (filter + sufficiency check, max 5 rounds) → write
3. Summarize each section for cross-section consistency
4. Compile all sections into a final report
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.notebook import vector_search
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content

# ──────────────────────────────────────────────────────────────────────
# Pydantic models for structured LLM output
# ──────────────────────────────────────────────────────────────────────


class Section(BaseModel):
    title: str = Field(description="Section title")
    description: str = Field(description="What this section should cover")
    search_queries: List[str] = Field(
        description="1-3 search queries to find relevant information"
    )


class Outline(BaseModel):
    reasoning: str = Field(description="Why this outline structure was chosen")
    sections: List[Section] = Field(description="List of sections for the report")


class RelevanceItem(BaseModel):
    result_index: int = Field(description="Index of the result item")
    relevant: bool = Field(description="Whether this result is relevant")


class EvaluationResult(BaseModel):
    relevance: List[RelevanceItem] = Field(
        description="Relevance assessment for each result"
    )
    is_sufficient: bool = Field(
        description="Whether the relevant materials are sufficient"
    )
    reason: str = Field(description="Explanation for the sufficiency judgment")
    new_queries: List[str] = Field(
        default_factory=list,
        description="New search queries if materials are insufficient (max 2)",
    )


# ──────────────────────────────────────────────────────────────────────
# Agent State
# ──────────────────────────────────────────────────────────────────────


class DeepResearchState(TypedDict):
    question: str
    outline: Optional[List[Dict[str, Any]]]  # List of section dicts
    current_section_index: int
    section_search_count: int
    section_search_results: List[Dict[str, Any]]  # Accumulated results for current section
    current_queries: List[str]  # Current search queries to execute
    is_material_sufficient: bool
    section_drafts: List[str]  # Completed section drafts
    section_summaries: List[str]  # Summaries of completed sections
    final_report: str
    status: str  # Current status for SSE streaming
    events: List[Dict[str, Any]]  # SSE events log


# ──────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────


def _get_model_id(config: RunnableConfig) -> Optional[str]:
    """Extract model_id from RunnableConfig."""
    return config.get("configurable", {}).get("model_id")


async def _provision_model(prompt: str, config: RunnableConfig, max_tokens: int = 4096, structured: Optional[dict] = None):
    """Provision a LangChain model with proper async handling."""
    model_id = _get_model_id(config)
    kwargs: Dict[str, Any] = {"max_tokens": max_tokens}
    if structured:
        kwargs["structured"] = structured
    return await provision_langchain_model(prompt, model_id, "tools", **kwargs)


def _format_outline(outline: List[Dict[str, Any]]) -> str:
    """Format outline for prompt inclusion."""
    lines = []
    for i, section in enumerate(outline, 1):
        lines.append(f"{i}. **{section['title']}**: {section['description']}")
    return "\n".join(lines)


def _format_previous_summaries(
    outline: List[Dict[str, Any]], summaries: List[str]
) -> str:
    """Format previously written section summaries."""
    if not summaries:
        return ""
    lines = []
    for i, summary in enumerate(summaries):
        lines.append(f"- **{outline[i]['title']}**: {summary}")
    return "\n".join(lines)


def _format_results_summary(results: List[Dict[str, Any]]) -> str:
    """Format search results as summaries (title + first 200 chars) for evaluation."""
    lines = []
    for i, r in enumerate(results):
        content = r.get("content", "")
        title = r.get("title", r.get("id", f"Result {i}"))
        snippet = content[:200] + "..." if len(content) > 200 else content
        lines.append(f"[{i}] ID: {r.get('id', 'unknown')} | {title}\n{snippet}\n")
    return "\n".join(lines)


def _format_full_materials(results: List[Dict[str, Any]]) -> str:
    """Format search results with full content for writing."""
    lines = []
    for r in results:
        rid = r.get("id", "unknown")
        title = r.get("title", "")
        content = r.get("content", "")
        lines.append(f"### [{rid}] {title}\n\n{content}\n")
    return "\n".join(lines)


def _emit_event(state: DeepResearchState, event_type: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create an SSE event and append to events list."""
    event = {"type": event_type, **data}
    return state.get("events", []) + [event]


# ──────────────────────────────────────────────────────────────────────
# Node 1: Plan Outline
# ──────────────────────────────────────────────────────────────────────


async def plan_outline(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Agent autonomously decides the number of sections and search plan."""
    try:
        parser = PydanticOutputParser(pydantic_object=Outline)
        prompt = Prompter(prompt_template="deep_research/outline", parser=parser).render(
            data={"question": state["question"]}
        )

        model = await _provision_model(prompt, config, max_tokens=4096, structured=dict(type="json"))
        ai_message = await model.ainvoke(prompt)

        content = extract_text_content(ai_message.content)
        cleaned = clean_thinking_content(content)
        outline = parser.parse(cleaned)

        sections = [s.model_dump() for s in outline.sections]

        logger.info(f"Deep Research: planned {len(sections)} sections")

        return {
            "outline": sections,
            "current_section_index": 0,
            "section_search_count": 0,
            "section_search_results": [],
            "current_queries": sections[0]["search_queries"] if sections else [],
            "is_material_sufficient": False,
            "status": f"Outlined {len(sections)} sections",
            "events": _emit_event(state, "outline", {
                "sections": [{"title": s["title"], "description": s["description"]} for s in sections],
                "reasoning": outline.reasoning,
            }),
        }
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Node 2: Search Section
# ──────────────────────────────────────────────────────────────────────


async def search_section(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Execute vector searches for current section's queries."""
    try:
        outline = state["outline"]
        idx = state["current_section_index"]
        section = outline[idx]
        queries = state.get("current_queries", section["search_queries"])
        search_count = state["section_search_count"]

        all_results = list(state.get("section_search_results", []))
        existing_ids = {r.get("id") for r in all_results}

        new_result_count = 0
        for query in queries:
            try:
                results = await vector_search(query, 10, True, True)
                for r in results:
                    if r.get("id") not in existing_ids:
                        all_results.append(r)
                        existing_ids.add(r.get("id"))
                        new_result_count += 1
            except Exception as e:
                logger.warning(f"Search failed for query '{query}': {e}")

        logger.info(
            f"Deep Research: section '{section['title']}' search #{search_count + 1}, "
            f"found {new_result_count} new results, total {len(all_results)}"
        )

        return {
            "section_search_results": all_results,
            "section_search_count": search_count + 1,
            "status": f"Searching: {section['title']} (attempt {search_count + 1})",
            "events": _emit_event(state, "search_done", {
                "section": section["title"],
                "section_index": idx,
                "attempt": search_count + 1,
                "new_results": new_result_count,
                "total_results": len(all_results),
            }),
        }
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Node 3: Evaluate Material
# ──────────────────────────────────────────────────────────────────────


async def evaluate_material(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Evaluate relevance and sufficiency of collected materials."""
    try:
        outline = state["outline"]
        idx = state["current_section_index"]
        section = outline[idx]
        results = state["section_search_results"]
        search_count = state["section_search_count"]

        # If no results found, mark as sufficient to avoid infinite loop
        if not results:
            logger.info(f"Deep Research: no results for '{section['title']}', moving to write")
            return {
                "is_material_sufficient": True,
                "status": f"No materials found for: {section['title']}",
                "events": _emit_event(state, "evaluate", {
                    "section": section["title"],
                    "section_index": idx,
                    "sufficient": True,
                    "reason": "No search results available",
                }),
            }

        parser = PydanticOutputParser(pydantic_object=EvaluationResult)
        prompt = Prompter(prompt_template="deep_research/evaluate", parser=parser).render(
            data={
                "section_title": section["title"],
                "section_description": section["description"],
                "result_count": len(results),
                "search_count": search_count,
                "results_summary": _format_results_summary(results),
            }
        )

        model = await _provision_model(prompt, config, max_tokens=2048, structured=dict(type="json"))
        ai_message = await model.ainvoke(prompt)

        content = extract_text_content(ai_message.content)
        cleaned = clean_thinking_content(content)
        evaluation = parser.parse(cleaned)

        # Filter results based on relevance
        relevant_indices = {
            item.result_index for item in evaluation.relevance if item.relevant
        }
        filtered_results = [
            r for i, r in enumerate(results) if i in relevant_indices
        ]

        is_sufficient = evaluation.is_sufficient or search_count >= 5
        new_queries = evaluation.new_queries if not is_sufficient else []

        logger.info(
            f"Deep Research: evaluate '{section['title']}' - "
            f"{len(filtered_results)}/{len(results)} relevant, "
            f"sufficient={is_sufficient}, reason={evaluation.reason}"
        )

        return {
            "section_search_results": filtered_results,
            "is_material_sufficient": is_sufficient,
            "current_queries": new_queries,
            "status": f"Evaluated: {section['title']} ({'sufficient' if is_sufficient else 'need more'})",
            "events": _emit_event(state, "evaluate", {
                "section": section["title"],
                "section_index": idx,
                "sufficient": is_sufficient,
                "reason": evaluation.reason,
                "relevant_count": len(filtered_results),
                "total_count": len(results),
                "new_queries": new_queries,
            }),
        }
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Node 4: Write Section
# ──────────────────────────────────────────────────────────────────────


async def write_section(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Write the current section based on filtered relevant materials."""
    try:
        outline = state["outline"]
        idx = state["current_section_index"]
        section = outline[idx]
        results = state["section_search_results"]
        previous_summaries = state.get("section_summaries", [])

        prompt = Prompter(prompt_template="deep_research/write").render(
            data={
                "outline": _format_outline(outline),
                "previous_summaries": _format_previous_summaries(outline, previous_summaries),
                "section_title": section["title"],
                "section_description": section["description"],
                "materials": _format_full_materials(results) if results else "No materials available. Write based on general knowledge.",
            }
        )

        model = await _provision_model(prompt, config, max_tokens=8192)
        ai_message = await model.ainvoke(prompt)

        content = extract_text_content(ai_message.content)
        draft = clean_thinking_content(content)

        drafts = list(state.get("section_drafts", []))
        drafts.append(draft)

        logger.info(f"Deep Research: wrote section '{section['title']}' ({len(draft)} chars)")

        return {
            "section_drafts": drafts,
            "status": f"Written: {section['title']}",
            "events": _emit_event(state, "write_done", {
                "section": section["title"],
                "section_index": idx,
                "draft_length": len(draft),
                "preview": draft[:200] + "..." if len(draft) > 200 else draft,
            }),
        }
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Node 5: Summarize Section
# ──────────────────────────────────────────────────────────────────────


async def summarize_section(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Summarize the just-written section for cross-section consistency."""
    try:
        outline = state["outline"]
        idx = state["current_section_index"]
        section = outline[idx]
        drafts = state["section_drafts"]
        latest_draft = drafts[-1]

        prompt = Prompter(prompt_template="deep_research/summarize").render(
            data={
                "section_title": section["title"],
                "section_content": latest_draft,
            }
        )

        model = await _provision_model(prompt, config, max_tokens=512)
        ai_message = await model.ainvoke(prompt)

        content = extract_text_content(ai_message.content)
        summary = clean_thinking_content(content).strip()

        summaries = list(state.get("section_summaries", []))
        summaries.append(summary)

        # Advance to next section and reset per-section state
        next_idx = idx + 1
        next_queries = []
        if next_idx < len(outline):
            next_queries = outline[next_idx]["search_queries"]

        logger.info(f"Deep Research: summarized '{section['title']}': {summary[:80]}...")

        return {
            "section_summaries": summaries,
            "current_section_index": next_idx,
            "section_search_count": 0,
            "section_search_results": [],
            "current_queries": next_queries,
            "is_material_sufficient": False,
            "status": f"Summarized: {section['title']}",
            "events": _emit_event(state, "summarize_done", {
                "section": section["title"],
                "section_index": idx,
                "summary": summary,
            }),
        }
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Node 6: Compile Report
# ──────────────────────────────────────────────────────────────────────


async def compile_report(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Compile all section drafts into a final cohesive report."""
    try:
        outline = state["outline"]
        drafts = state["section_drafts"]

        # Format the drafts with section headers
        formatted_drafts = []
        for i, (section, draft) in enumerate(zip(outline, drafts)):
            formatted_drafts.append(f"## {section['title']}\n\n{draft}")
        all_drafts = "\n\n---\n\n".join(formatted_drafts)

        prompt = Prompter(prompt_template="deep_research/compile").render(
            data={
                "question": state["question"],
                "outline": _format_outline(outline),
                "drafts": all_drafts,
            }
        )

        model = await _provision_model(prompt, config, max_tokens=16384)
        ai_message = await model.ainvoke(prompt)

        content = extract_text_content(ai_message.content)
        final_report = clean_thinking_content(content)

        logger.info(f"Deep Research: compiled final report ({len(final_report)} chars)")

        return {
            "final_report": final_report,
            "status": "Complete",
            "events": _emit_event(state, "complete", {
                "report_length": len(final_report),
            }),
        }
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Routing functions
# ──────────────────────────────────────────────────────────────────────


def route_after_evaluate(state: DeepResearchState) -> str:
    """After evaluation: write if sufficient, search more if not."""
    if state.get("is_material_sufficient", False) or state.get("section_search_count", 0) >= 5:
        return "write_section"
    return "search_section"


def route_after_summarize(state: DeepResearchState) -> str:
    """After summarize: continue to next section or compile."""
    outline = state.get("outline", [])
    idx = state.get("current_section_index", 0)
    if idx >= len(outline):
        return "compile_report"
    return "search_section"


# ──────────────────────────────────────────────────────────────────────
# Build the graph
# ──────────────────────────────────────────────────────────────────────

deep_research_graph = StateGraph(DeepResearchState)

# Add nodes
deep_research_graph.add_node("plan_outline", plan_outline)
deep_research_graph.add_node("search_section", search_section)
deep_research_graph.add_node("evaluate_material", evaluate_material)
deep_research_graph.add_node("write_section", write_section)
deep_research_graph.add_node("summarize_section", summarize_section)
deep_research_graph.add_node("compile_report", compile_report)

# Add edges
deep_research_graph.add_edge(START, "plan_outline")
deep_research_graph.add_edge("plan_outline", "search_section")
deep_research_graph.add_edge("search_section", "evaluate_material")
deep_research_graph.add_conditional_edges(
    "evaluate_material",
    route_after_evaluate,
    ["write_section", "search_section"],
)
deep_research_graph.add_edge("write_section", "summarize_section")
deep_research_graph.add_conditional_edges(
    "summarize_section",
    route_after_summarize,
    ["search_section", "compile_report"],
)
deep_research_graph.add_edge("compile_report", END)

# Compile the graph
graph = deep_research_graph.compile()
