"""
Deep Research Agent - LangGraph implementation.

A multi-step research agent that generates comprehensive reports by:
1. Planning an outline (agent decides section count)
2. Processing ALL sections in PARALLEL: search → evaluate (max 3 rounds) → write → summarize
3. Compile all sections into a final report
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
from open_notebook.database.repository import repo_query, ensure_record_id
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
    notebook_id: Optional[str]  # Scope search to this notebook
    job_id: Optional[str]  # Persistent job record ID
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


async def _update_job(state: DeepResearchState, updates: dict) -> None:
    """Persist job state to the deep_research_job record in the user's DB."""
    job_id = state.get("job_id")
    if not job_id:
        return
    try:
        set_clauses = []
        params: Dict[str, Any] = {"job_id": ensure_record_id(job_id)}
        for key, value in updates.items():
            set_clauses.append(f"{key} = ${key}")
            params[key] = value
        set_clauses.append("updated = time::now()")
        query = f"UPDATE $job_id SET {', '.join(set_clauses)}"
        await repo_query(query, params)
    except Exception as e:
        logger.warning(f"Failed to update deep research job {job_id}: {e}")


async def _notebook_vector_search(
    keyword: str, notebook_id: str, match_count: int = 10, min_similarity: float = 0.2
) -> list:
    """Vector search scoped to a specific notebook's sources, done at SurrealQL level."""
    from open_notebook.utils.embedding import generate_embedding

    embed = await generate_embedding(keyword)

    # Debug: check how many sources are linked to this notebook
    sources_check = await repo_query(
        "SELECT VALUE in FROM reference WHERE out = $notebook_id",
        {"notebook_id": ensure_record_id(notebook_id)},
    )
    logger.info(f"Notebook {notebook_id} has {len(sources_check) if sources_check else 0} linked sources: {sources_check}")

    # Debug: check if embeddings exist for these sources
    if sources_check:
        embed_count = await repo_query(
            "SELECT count() FROM source_embedding WHERE source IN $sources GROUP ALL",
            {"sources": [ensure_record_id(s) if isinstance(s, str) else s for s in sources_check]},
        )
        insight_count = await repo_query(
            "SELECT count() FROM source_insight WHERE source IN $sources GROUP ALL",
            {"sources": [ensure_record_id(s) if isinstance(s, str) else s for s in sources_check]},
        )
        logger.info(f"Embeddings: {embed_count}, Insights: {insight_count}")

    # Step-by-step search with detailed logging
    notebook_sources = sources_check or []
    source_ids = [ensure_record_id(s) if isinstance(s, str) else s for s in notebook_sources]

    logger.info(f"[VectorSearch] Query: '{keyword}', notebook: {notebook_id}, source_ids: {source_ids}")

    # Step 1: Search source_embedding
    source_results_raw = await repo_query(
        """
        SELECT
            id,
            source.title AS title,
            content,
            source.id AS parent_id,
            vector::similarity::cosine(embedding, $embed) AS similarity
        FROM source_embedding
        WHERE source IN $sources
            AND vector::similarity::cosine(embedding, $embed) >= $min_similarity
        ORDER BY similarity DESC
        LIMIT $match_count
        """,
        {
            "sources": source_ids,
            "embed": embed,
            "match_count": match_count,
            "min_similarity": min_similarity,
        },
    )
    logger.info(f"[VectorSearch] source_embedding results: {len(source_results_raw) if source_results_raw else 0}")
    if source_results_raw:
        for r in source_results_raw[:3]:
            logger.info(f"[VectorSearch]   - sim={r.get('similarity', '?'):.4f}, title={r.get('title', '?')}, content={str(r.get('content', ''))[:80]}...")

    # Step 2: Search source_insight
    insight_results_raw = await repo_query(
        """
        SELECT
            id,
            insight_type + ' - ' + source.title AS title,
            content,
            source.id AS parent_id,
            vector::similarity::cosine(embedding, $embed) AS similarity
        FROM source_insight
        WHERE source IN $sources
            AND vector::similarity::cosine(embedding, $embed) >= $min_similarity
        ORDER BY similarity DESC
        LIMIT $match_count
        """,
        {
            "sources": source_ids,
            "embed": embed,
            "match_count": match_count,
            "min_similarity": min_similarity,
        },
    )
    logger.info(f"[VectorSearch] source_insight results: {len(insight_results_raw) if insight_results_raw else 0}")
    if insight_results_raw:
        for r in insight_results_raw[:3]:
            logger.info(f"[VectorSearch]   - sim={r.get('similarity', '?'):.4f}, title={r.get('title', '?')}, content={str(r.get('content', ''))[:80]}...")

    # Combine results
    all_results = (source_results_raw or []) + (insight_results_raw or [])

    # Deduplicate by id, keep highest similarity
    seen = {}
    for r in all_results:
        rid = str(r.get("id", ""))
        if rid not in seen or r.get("similarity", 0) > seen[rid].get("similarity", 0):
            seen[rid] = r

    results = sorted(seen.values(), key=lambda x: x.get("similarity", 0), reverse=True)[:match_count]
    logger.info(f"[VectorSearch] Final combined results: {len(results)}")

    return results


# ──────────────────────────────────────────────────────────────────────
# Node 1: Plan Outline
# ──────────────────────────────────────────────────────────────────────


async def plan_outline(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Agent autonomously decides the number of sections and search plan."""
    try:
        notebook_id = state.get("notebook_id")
        question = state["question"]

        # ── Gather notebook context for better outline planning ──
        source_previews = []
        preliminary_results = []

        if notebook_id:
            # 1. Get first 200 chars of each source in the notebook
            previews_raw = await repo_query(
                """
                LET $sources = (SELECT VALUE in FROM reference WHERE out = $notebook_id);
                SELECT
                    source.title AS title,
                    content
                FROM source_embedding
                WHERE source IN $sources AND order = 0
                """,
                {"notebook_id": ensure_record_id(notebook_id)},
            )
            if previews_raw:
                for p in previews_raw:
                    title = p.get("title", "Untitled")
                    content = str(p.get("content", ""))[:200]
                    source_previews.append({"title": title, "preview": content})
                logger.info(f"Deep Research: collected {len(source_previews)} source previews for outline")

            # 2. Preliminary vector search based on the question
            preliminary_results = await _notebook_vector_search(question, notebook_id, match_count=5)
            logger.info(f"Deep Research: preliminary search found {len(preliminary_results)} results")

        parser = PydanticOutputParser(pydantic_object=Outline)
        prompt = Prompter(prompt_template="deep_research/outline", parser=parser).render(
            data={
                "question": question,
                "source_previews": source_previews,
                "preliminary_results": preliminary_results,
            }
        )

        model = await _provision_model(prompt, config, max_tokens=4096, structured=dict(type="json"))
        ai_message = await model.ainvoke(prompt)

        content = extract_text_content(ai_message.content)
        cleaned = clean_thinking_content(content)
        outline = parser.parse(cleaned)

        sections = [s.model_dump() for s in outline.sections]

        logger.info(f"Deep Research: planned {len(sections)} sections")

        result = {
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
        await _update_job(state, {"status": result["status"], "events": result["events"]})
        return result
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

MAX_SEARCH_ROUNDS = 3
MAX_WRITE_MATERIALS = 20


# ──────────────────────────────────────────────────────────────────────
# Parallel section processing
# ──────────────────────────────────────────────────────────────────────


async def _process_single_section(
    section: Dict[str, Any],
    section_index: int,
    outline: List[Dict[str, Any]],
    state: DeepResearchState,
    config: RunnableConfig,
) -> Dict[str, Any]:
    """
    Process a single section: search → evaluate → write → summarize.
    Runs independently so multiple sections can execute in parallel.
    """
    notebook_id = state.get("notebook_id")
    section_title = section["title"]
    events: List[Dict[str, Any]] = []

    def _add_event(event_type: str, data: Dict[str, Any]) -> None:
        event = {"type": event_type, **data}
        events.append(event)

    # ── Search + Evaluate loop (max MAX_SEARCH_ROUNDS rounds) ──
    all_results: List[Dict[str, Any]] = []
    existing_ids: set = set()
    queries = list(section["search_queries"])
    search_count = 0
    is_sufficient = False

    while search_count < MAX_SEARCH_ROUNDS and not is_sufficient:
        # Search
        new_result_count = 0
        for query in queries:
            try:
                if notebook_id:
                    results = await _notebook_vector_search(query, notebook_id, 10)
                else:
                    results = await vector_search(query, 10, True, True)
                for r in results:
                    if r.get("id") not in existing_ids:
                        all_results.append(r)
                        existing_ids.add(r.get("id"))
                        new_result_count += 1
            except Exception as e:
                logger.warning(f"Search failed for query '{query}': {e}")

        search_count += 1
        logger.info(
            f"Deep Research: section [{section_index}] '{section_title}' "
            f"search #{search_count}, {new_result_count} new, total {len(all_results)}"
        )

        _add_event("search_done", {
            "section": section_title,
            "section_index": section_index,
            "attempt": search_count,
            "new_results": new_result_count,
            "total_results": len(all_results),
        })

        # Update job with search progress
        await _update_job(state, {
            "status": f"Searching: {section_title} (attempt {search_count})",
            "events": list(state.get("events", [])) + events,
        })

        # Evaluate
        if not all_results:
            logger.info(f"Deep Research: no results for '{section_title}', proceeding to write")
            _add_event("evaluate", {
                "section": section_title,
                "section_index": section_index,
                "sufficient": True,
                "reason": "No search results available",
            })
            break

        parser = PydanticOutputParser(pydantic_object=EvaluationResult)
        prompt = Prompter(prompt_template="deep_research/evaluate", parser=parser).render(
            data={
                "section_title": section["title"],
                "section_description": section["description"],
                "result_count": len(all_results),
                "search_count": search_count,
                "results_summary": _format_results_summary(all_results),
            }
        )

        model = await _provision_model(prompt, config, max_tokens=2048, structured=dict(type="json"))
        ai_message = await model.ainvoke(prompt)
        content = extract_text_content(ai_message.content)
        cleaned = clean_thinking_content(content)
        evaluation = parser.parse(cleaned)

        # Filter results based on relevance
        relevant_indices = {item.result_index for item in evaluation.relevance if item.relevant}
        all_results = [r for i, r in enumerate(all_results) if i in relevant_indices]

        is_sufficient = evaluation.is_sufficient or search_count >= MAX_SEARCH_ROUNDS
        queries = evaluation.new_queries if not is_sufficient else []

        logger.info(
            f"Deep Research: evaluate [{section_index}] '{section_title}' - "
            f"{len(all_results)} relevant, sufficient={is_sufficient}"
        )

        _add_event("evaluate", {
            "section": section_title,
            "section_index": section_index,
            "sufficient": is_sufficient,
            "reason": evaluation.reason,
            "relevant_count": len(all_results),
            "new_queries": queries,
        })

        await _update_job(state, {
            "status": f"Evaluated: {section_title} ({'sufficient' if is_sufficient else 'need more'})",
            "events": list(state.get("events", [])) + events,
        })

    # ── Write section ──
    write_results = all_results
    if write_results and len(write_results) > MAX_WRITE_MATERIALS:
        write_results = sorted(
            write_results, key=lambda r: r.get("similarity", 0), reverse=True
        )[:MAX_WRITE_MATERIALS]
        logger.info(
            f"Deep Research: trimmed {len(all_results)} results to "
            f"top {MAX_WRITE_MATERIALS} for writing"
        )

    write_prompt = Prompter(prompt_template="deep_research/write").render(
        data={
            "outline": _format_outline(outline),
            "previous_summaries": "",  # No cross-section context in parallel mode
            "section_title": section["title"],
            "section_description": section["description"],
            "materials": _format_full_materials(write_results)
            if write_results
            else "No materials available. Write based on general knowledge.",
        }
    )

    model = await _provision_model(write_prompt, config, max_tokens=8192)
    ai_message = await model.ainvoke(write_prompt)
    content = extract_text_content(ai_message.content)
    draft = clean_thinking_content(content)

    logger.info(
        f"Deep Research: wrote section [{section_index}] "
        f"'{section_title}' ({len(draft)} chars)"
    )

    _add_event("write_done", {
        "section": section_title,
        "section_index": section_index,
        "draft_length": len(draft),
        "preview": draft[:200] + "..." if len(draft) > 200 else draft,
    })

    await _update_job(state, {
        "status": f"Written: {section_title}",
        "events": list(state.get("events", [])) + events,
    })

    # ── Summarize section ──
    summarize_prompt = Prompter(prompt_template="deep_research/summarize").render(
        data={
            "section_title": section["title"],
            "section_content": draft,
        }
    )

    model = await _provision_model(summarize_prompt, config, max_tokens=512)
    ai_message = await model.ainvoke(summarize_prompt)
    content = extract_text_content(ai_message.content)
    summary = clean_thinking_content(content).strip()

    logger.info(
        f"Deep Research: summarized [{section_index}] "
        f"'{section_title}': {summary[:80]}..."
    )

    _add_event("summarize_done", {
        "section": section_title,
        "section_index": section_index,
        "summary": summary,
    })

    return {
        "section_index": section_index,
        "draft": draft,
        "summary": summary,
        "events": events,
    }


async def process_all_sections(
    state: DeepResearchState, config: RunnableConfig
) -> dict:
    """Process all sections in parallel using asyncio.gather."""
    try:
        outline = state["outline"]

        logger.info(f"Deep Research: processing {len(outline)} sections in parallel")

        # Launch all sections concurrently
        tasks = [
            _process_single_section(section, idx, outline, state, config)
            for idx, section in enumerate(outline)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results in order
        drafts = [""] * len(outline)
        summaries = [""] * len(outline)
        all_events = list(state.get("events", []))

        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Deep Research: section processing failed: {r}")
                continue
            idx = r["section_index"]
            drafts[idx] = r["draft"]
            summaries[idx] = r["summary"]
            all_events.extend(r["events"])

        result = {
            "section_drafts": drafts,
            "section_summaries": summaries,
            "events": all_events,
            "status": "All sections written, compiling report",
        }
        await _update_job(state, {"status": result["status"], "events": all_events})
        return result
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Node: Compile Report
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

        result = {
            "final_report": final_report,
            "status": "completed",
            "events": _emit_event(state, "complete", {
                "report_length": len(final_report),
            }),
        }
        await _update_job(state, {
            "status": "completed",
            "events": result["events"],
            "final_report": final_report,
        })
        return result
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


# ──────────────────────────────────────────────────────────────────────
# Build the graph (simplified: parallel sections)
# ──────────────────────────────────────────────────────────────────────

deep_research_graph = StateGraph(DeepResearchState)

# Add nodes
deep_research_graph.add_node("plan_outline", plan_outline)
deep_research_graph.add_node("process_all_sections", process_all_sections)
deep_research_graph.add_node("compile_report", compile_report)

# Add edges: plan → parallel sections → compile → done
deep_research_graph.add_edge(START, "plan_outline")
deep_research_graph.add_edge("plan_outline", "process_all_sections")
deep_research_graph.add_edge("process_all_sections", "compile_report")
deep_research_graph.add_edge("compile_report", END)

# Compile the graph
graph = deep_research_graph.compile()

