"""
Deep Research Agent - LangGraph implementation.

A multi-step research agent that generates comprehensive reports by:
1. Planning an outline (agent decides section count)
2. Processing ALL sections in PARALLEL: search → evaluate (max 3 rounds) → write → summarize
3. Compile all sections into a final report
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import repo_query, ensure_record_id, admin_repo_query
from open_notebook.domain.notebook import vector_search
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content

# ──────────────────────────────────────────────────────────────────────
# LLM Concurrency Limiter
# ──────────────────────────────────────────────────────────────────────

_llm_semaphore = asyncio.Semaphore(50)
_llm_semaphore_limit = 50


def update_llm_concurrency(new_limit: int):
    """Hot-update the LLM concurrency limit. New requests use the new semaphore."""
    global _llm_semaphore, _llm_semaphore_limit
    if new_limit != _llm_semaphore_limit and new_limit > 0:
        _llm_semaphore = asyncio.Semaphore(new_limit)
        _llm_semaphore_limit = new_limit
        logger.info(f"LLM concurrency limit updated to {new_limit}")


async def _llm_invoke(model, prompt):
    """Semaphore-guarded LLM call with timeout. Queues when over the limit."""
    async with _llm_semaphore:
        try:
            return await asyncio.wait_for(model.ainvoke(prompt), timeout=600)
        except asyncio.TimeoutError:
            logger.error("LLM request timed out after 10 minutes")
            raise OpenNotebookError("LLM 请求超时（10分钟），请重试")


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


class SourceExpansionRequest(BaseModel):
    source_id: str = Field(description="Source ID that needs full-text reading")
    information_needs: List[str] = Field(
        description="1-3 specific information needs to look for in the full text, each under 50 characters",
        max_length=3,
    )
    priority: int = Field(
        default=5,
        description="Importance priority 1-10, where 10 means this source is critical for the section and 1 means marginally useful",
    )


class ContextExpansionResult(BaseModel):
    needs_full_context: List[SourceExpansionRequest] = Field(
        default_factory=list,
        description="List of sources that need full-text context expansion, each with a specific information need",
    )
    reason: str = Field(description="Why these sources need full context")


class RewrittenQueries(BaseModel):
    queries: List[str] = Field(description="Two rewritten search queries")


# ──────────────────────────────────────────────────────────────────────
# Agent State
# ──────────────────────────────────────────────────────────────────────


class DeepResearchState(TypedDict):
    question: str
    notebook_id: Optional[str]  # Scope search to this notebook
    job_id: Optional[str]  # Persistent job record ID
    research_type: str  # "deep" or "quick"
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


async def _get_deep_research_settings() -> dict:
    """Read deep research settings from admin DB (shared across all users)."""
    try:
        result = await admin_repo_query(
            "SELECT deep_research_max_search_rounds, deep_research_enable_context_expansion, "
            "deep_research_max_llm_concurrent "
            "FROM open_notebook:content_settings"
        )
        if result and result[0]:
            return result[0]
    except Exception as e:
        logger.warning(f"Failed to read deep research settings from admin DB: {e}")
    return {}


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
        rid_str = str(rid)
        # For source_embedding results, use the parent source ID so that
        # references in the report link to the actual source record.
        if rid_str.startswith("source_embedding:") and r.get("parent_id"):
            rid = r["parent_id"]
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
# Context Expansion helpers
# ──────────────────────────────────────────────────────────────────────

MAX_FULL_TEXT_LENGTH = 15_000  # Per-segment limit for extraction
MAX_SEGMENTS = 10  # Max number of segments to read (total cap = 150K chars)


async def _fetch_source_full_text(source_id: str) -> Optional[str]:
    """Fetch the full_text of a source by its ID.
    Returns None if text is empty or exceeds MAX_SEGMENTS * MAX_FULL_TEXT_LENGTH."""
    result = await repo_query(
        "SELECT full_text FROM source WHERE id = $id",
        {"id": ensure_record_id(source_id)},
    )
    if result and result[0].get("full_text"):
        text = result[0]["full_text"]
        max_total = MAX_FULL_TEXT_LENGTH * MAX_SEGMENTS
        if len(text) > max_total:
            logger.info(
                f"Source {source_id} full_text too long "
                f"({len(text)} chars > {max_total}), skipping"
            )
            return None
        return text
    return None


async def _extract_from_chunk(
    chunk_text: str,
    chunk_index: int,
    source_title: str,
    source_id: str,
    section: Dict[str, Any],
    config: RunnableConfig,
    information_needs: List[str] = None,
) -> str:
    """Extract relevant info from a single chunk of full text."""
    prompt = Prompter(prompt_template="deep_research/extract_from_source").render(
        data={
            "section_title": section["title"],
            "section_description": section["description"],
            "source_title": f"{source_title} (part {chunk_index + 1})",
            "source_id": source_id,
            "full_text": chunk_text,
            "information_needs": information_needs or [],
        }
    )
    model = await _provision_model(prompt, config, max_tokens=1024)
    ai_message = await _llm_invoke(model, prompt)
    content = extract_text_content(ai_message.content)
    return clean_thinking_content(content).strip()


async def _extract_from_single_source(
    source_id: str,
    source_title: str,
    section: Dict[str, Any],
    config: RunnableConfig,
    information_needs: List[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch full text for one source and extract relevant info (≤500 chars).
    If the text exceeds MAX_FULL_TEXT_LENGTH, it is split into segments,
    each processed in parallel, then consolidated with a final LLM call."""
    full_text = await _fetch_source_full_text(source_id)
    if not full_text:
        return None

    if len(full_text) <= MAX_FULL_TEXT_LENGTH:
        # ── Short text: single-pass extraction ──
        prompt = Prompter(prompt_template="deep_research/extract_from_source").render(
            data={
                "section_title": section["title"],
                "section_description": section["description"],
                "source_title": source_title,
                "source_id": source_id,
                "full_text": full_text,
                "information_needs": information_needs or [],
            }
        )
        model = await _provision_model(prompt, config, max_tokens=1024)
        ai_message = await _llm_invoke(model, prompt)
        content = extract_text_content(ai_message.content)
        extracted = clean_thinking_content(content).strip()
    else:
        # ── Long text: chunked parallel extraction + consolidation ──
        # Split into segments of MAX_FULL_TEXT_LENGTH
        segments = [
            full_text[i : i + MAX_FULL_TEXT_LENGTH]
            for i in range(0, len(full_text), MAX_FULL_TEXT_LENGTH)
        ]
        segments = segments[:MAX_SEGMENTS]  # Cap at MAX_SEGMENTS
        logger.info(
            f"Context Expansion: source {source_id} ({source_title}) "
            f"split into {len(segments)} segments "
            f"({len(full_text)} chars total)"
        )

        # Extract from each segment in parallel
        tasks = [
            _extract_from_chunk(seg, idx, source_title, source_id, section, config, information_needs)
            for idx, seg in enumerate(segments)
        ]
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful extractions
        partial_extractions = []
        for i, r in enumerate(chunk_results):
            if isinstance(r, Exception):
                logger.warning(
                    f"Context Expansion: chunk {i} extraction failed "
                    f"for {source_id}: {r}"
                )
            elif r:
                partial_extractions.append(r)

        if not partial_extractions:
            return None

        # Consolidate with final LLM call
        combined = "\n\n---\n\n".join(partial_extractions)
        consolidation_prompt = Prompter(
            prompt_template="deep_research/consolidate_extractions"
        ).render(
            data={
                "section_title": section["title"],
                "section_description": section["description"],
                "source_title": source_title,
                "source_id": source_id,
                "partial_extractions": combined,
                "information_needs": information_needs or [],
            }
        )
        model = await _provision_model(consolidation_prompt, config, max_tokens=1024)
        ai_message = await _llm_invoke(model, consolidation_prompt)
        content = extract_text_content(ai_message.content)
        extracted = clean_thinking_content(content).strip()

    if not extracted:
        return None

    logger.info(
        f"Context Expansion: extracted {len(extracted)} chars "
        f"from source {source_id} ({source_title})"
    )

    return {
        "id": source_id,
        "title": f"[Full-Text Extract] {source_title}",
        "content": extracted,
        "parent_id": source_id,
        "similarity": 1.0,  # High priority since explicitly requested
    }


async def _expand_context(
    section: Dict[str, Any],
    relevant_results: List[Dict[str, Any]],
    config: RunnableConfig,
) -> List[Dict[str, Any]]:
    """
    Context Expansion: judge which sources need full-text reading,
    then extract relevant info (≤500 chars) from each in parallel.
    """
    # Collect unique source IDs from relevant chunks
    source_ids_in_results = set()
    source_titles: Dict[str, str] = {}
    for r in relevant_results:
        pid = r.get("parent_id") or r.get("id", "")
        pid_str = str(pid)
        if pid_str.startswith("source:"):
            source_ids_in_results.add(pid_str)
            if pid_str not in source_titles:
                source_titles[pid_str] = r.get("title", "")

    if not source_ids_in_results:
        return []

    # Build a summary of chunks grouped by source for the LLM
    chunks_summary_lines = []
    for r in relevant_results:
        pid = str(r.get("parent_id") or r.get("id", ""))
        title = r.get("title", "")
        snippet = str(r.get("content", ""))[:150]
        chunks_summary_lines.append(f"- Source ID: {pid} | {title}\n  Snippet: {snippet}...")
    chunks_summary = "\n".join(chunks_summary_lines)

    # Step 1: LLM judges which sources need full context
    parser = PydanticOutputParser(pydantic_object=ContextExpansionResult)
    prompt = Prompter(prompt_template="deep_research/expand_context", parser=parser).render(
        data={
            "section_title": section["title"],
            "section_description": section["description"],
            "chunks_summary": chunks_summary,
        }
    )

    model = await _provision_model(prompt, config, max_tokens=1024, structured=dict(type="json"))
    ai_message = await _llm_invoke(model, prompt)
    content = extract_text_content(ai_message.content)
    cleaned = clean_thinking_content(content)
    expansion_result = parser.parse(cleaned)

    # Filter to only valid source IDs that exist in our results,
    # then sort by priority descending so the most important sources come first
    sources_to_expand = sorted(
        [
            req for req in expansion_result.needs_full_context
            if req.source_id in source_ids_in_results
        ],
        key=lambda r: r.priority,
        reverse=True,
    )

    if not sources_to_expand:
        logger.info("Context Expansion: no sources need full-text reading")
        return []

    logger.info(
        f"Context Expansion: expanding {len(sources_to_expand)} sources "
        f"(sorted by priority): "
        f"{[(r.source_id, r.priority, r.information_needs) for r in sources_to_expand]} "
        f"(reason: {expansion_result.reason})"
    )

    # Step 2: Extract from each source in parallel
    tasks = [
        _extract_from_single_source(
            req.source_id, source_titles.get(req.source_id, ""), section, config,
            information_needs=req.information_needs,
        )
        for req in sources_to_expand
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect successful extractions
    expanded_materials = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Context Expansion: extraction failed: {r}")
        elif r is not None:
            expanded_materials.append(r)

    logger.info(f"Context Expansion: got {len(expanded_materials)} extractions")
    return expanded_materials


# ──────────────────────────────────────────────────────────────────────
# Node 1: Plan Outline
# ──────────────────────────────────────────────────────────────────────


async def plan_outline(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Agent autonomously decides the number of sections and search plan."""
    try:
        notebook_id = state.get("notebook_id")
        question = state["question"]

        # ── Step 1: Gather source previews ──
        source_previews = []
        preliminary_results = []

        if notebook_id:
            logger.info(f"Deep Research: fetching source previews for notebook {notebook_id}")

            source_ids = await repo_query(
                "SELECT VALUE in FROM reference WHERE out = $notebook_id",
                {"notebook_id": ensure_record_id(notebook_id)},
            )
            logger.info(f"Deep Research: found {len(source_ids) if source_ids else 0} sources in notebook")

            if source_ids:
                previews_raw = await repo_query(
                    """
                    SELECT
                        source.title AS title,
                        content
                    FROM source_embedding
                    WHERE source IN $sources AND order = 0
                    """,
                    {"sources": [ensure_record_id(s) if isinstance(s, str) else s for s in source_ids]},
                )
                if previews_raw:
                    for p in previews_raw:
                        title = p.get("title", "Untitled")
                        content = str(p.get("content", ""))[:200]
                        source_previews.append({"title": title, "preview": content})
                    logger.info(f"Deep Research: collected {len(source_previews)} source previews for outline")

            # ── Step 2: LLM rewrites user query into 2 alternative queries ──
            rewrite_parser = PydanticOutputParser(pydantic_object=RewrittenQueries)
            rewrite_prompt = Prompter(
                prompt_template="deep_research/rewrite_queries", parser=rewrite_parser
            ).render(
                data={
                    "question": question,
                    "source_previews": source_previews,
                }
            )
            rewrite_model = await _provision_model(
                rewrite_prompt, config, max_tokens=512, structured=dict(type="json")
            )
            rewrite_msg = await _llm_invoke(rewrite_model, rewrite_prompt)
            rewrite_content = clean_thinking_content(
                extract_text_content(rewrite_msg.content)
            )
            rewritten = rewrite_parser.parse(rewrite_content)
            alt_queries = rewritten.queries[:2]  # Cap at 2
            logger.info(f"Deep Research: rewritten queries = {alt_queries}")

            # ── Step 3: 3 parallel vector searches (original + 2 rewritten), each top 5 ──
            all_queries = [question] + alt_queries
            search_tasks = [
                _notebook_vector_search(q, notebook_id, match_count=5)
                for q in all_queries
            ]
            search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)

            # Deduplicate by chunk ID, keep full fields for context expansion
            seen_ids = set()
            for i, results in enumerate(search_results_list):
                if isinstance(results, Exception):
                    logger.warning(f"Deep Research: search {i} failed: {results}")
                    continue
                for r in (results or []):
                    rid = r.get("id", "")
                    if rid not in seen_ids:
                        seen_ids.add(rid)
                        preliminary_results.append(r)  # Keep full fields
            logger.info(
                f"Deep Research: preliminary search found "
                f"{len(preliminary_results)} unique results from {len(all_queries)} queries"
            )

            # Emit outline search progress event
            running_events = _emit_event(state, "outline_search_done", {
                "outline_search_count": len(all_queries),
                "outline_result_count": len(preliminary_results),
            })
            await _update_job(state, {"status": "搜索完成", "events": running_events})

        # ── Step 3.5: Context Expansion for outline (max 3 sources) ──
        expanded_context = []
        if not preliminary_results:
            # No search results — initialise running_events from empty state
            running_events = state.get("events", [])

        if preliminary_results:
            dr_settings = await _get_deep_research_settings()
            enable_expansion = dr_settings.get("deep_research_enable_context_expansion", True)
            if enable_expansion:
                try:
                    # Build a virtual section for context expansion
                    virtual_section = {
                        "title": question,
                        "description": "Overall research question — identify key sources that need full-text reading for comprehensive outline planning",
                    }
                    expanded = await _expand_context(virtual_section, preliminary_results, config)
                    if expanded:
                        expanded_context = expanded[:2]  # Limit to 2 sources
                        logger.info(
                            f"Deep Research outline: context expansion got "
                            f"{len(expanded_context)} full-text extracts"
                        )
                        # Emit context expansion progress event
                        running_events = running_events + [{
                            "type": "outline_context_expanded",
                            "outline_expanded_count": len(expanded_context),
                        }]
                        await _update_job(state, {"status": "查看全文完成", "events": running_events})
                except Exception as e:
                    logger.warning(f"Deep Research outline: context expansion failed: {e}")
                    # Non-fatal: proceed without expanded context

        # Build preview list (200-char truncated) for prompt
        preliminary_previews = [
            {
                "title": r.get("title", ""),
                "content": str(r.get("content", ""))[:200],
                "similarity": r.get("similarity"),
            }
            for r in preliminary_results
        ]

        # ── Step 4: LLM plans outline using all gathered context ──
        # Emit planning event
        running_events = running_events + [{"type": "outline_planning"}]
        await _update_job(state, {"status": "正在规划大纲", "events": running_events})

        parser = PydanticOutputParser(pydantic_object=Outline)
        prompt = Prompter(prompt_template="deep_research/outline", parser=parser).render(
            data={
                "question": question,
                "source_previews": source_previews,
                "preliminary_results": preliminary_previews,
                "expanded_context": expanded_context,
            }
        )

        model = await _provision_model(prompt, config, max_tokens=4096, structured=dict(type="json"))
        ai_message = await _llm_invoke(model, prompt)

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
            "events": running_events + [{
                "type": "outline",
                "sections": [{"title": s["title"], "description": s["description"]} for s in sections],
                "reasoning": outline.reasoning,
            }],
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

    # ── Search + Evaluate loop ──
    is_quick = state.get("research_type") == "quick"
    dr_settings = await _get_deep_research_settings()
    # Sync LLM concurrency limit from settings
    concurrency = dr_settings.get("deep_research_max_llm_concurrent") or 50
    update_llm_concurrency(concurrency)
    configured_max = dr_settings.get("deep_research_max_search_rounds") or MAX_SEARCH_ROUNDS
    max_rounds = 1 if is_quick else configured_max
    all_results: List[Dict[str, Any]] = []
    existing_ids: set = set()
    queries = list(section["search_queries"])
    search_count = 0
    is_sufficient = False
    previous_reason: str = ""

    while search_count < max_rounds and not is_sufficient:
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

        # Evaluate (skip for quick research — use all results directly)
        if is_quick:
            _add_event("evaluate", {
                "section": section_title,
                "section_index": section_index,
                "sufficient": True,
                "reason": "Quick research: skipping evaluation",
                "relevant_count": len(all_results),
                "new_queries": [],
            })
            break

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
                "previous_reason": previous_reason,
            }
        )

        model = await _provision_model(prompt, config, max_tokens=2048, structured=dict(type="json"))
        ai_message = await _llm_invoke(model, prompt)
        content = extract_text_content(ai_message.content)
        cleaned = clean_thinking_content(content)
        evaluation = parser.parse(cleaned)

        # Filter results based on relevance
        relevant_indices = {item.result_index for item in evaluation.relevance if item.relevant}
        all_results = [r for i, r in enumerate(all_results) if i in relevant_indices]

        is_sufficient = evaluation.is_sufficient or search_count >= max_rounds
        queries = evaluation.new_queries if not is_sufficient else []
        previous_reason = evaluation.reason

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

    # ── Context Expansion (after evaluate, before write) ──
    enable_expansion = dr_settings.get("deep_research_enable_context_expansion", True)
    if not is_quick and all_results and enable_expansion:
        try:
            expanded = await _expand_context(section, all_results, config)
            if expanded:
                all_results.extend(expanded)
                _add_event("context_expanded", {
                    "section": section_title,
                    "section_index": section_index,
                    "expanded_sources": len(expanded),
                })
                await _update_job(state, {
                    "status": f"Context expanded: {section_title} (+{len(expanded)} sources)",
                    "events": list(state.get("events", [])) + events,
                })
        except Exception as e:
            logger.warning(f"Context Expansion failed for '{section_title}': {e}")
            # Non-fatal: proceed with original chunks

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
    ai_message = await _llm_invoke(model, write_prompt)
    content = extract_text_content(ai_message.content)
    draft = clean_thinking_content(content)

    # Strip the writing plan (between <!-- PLAN --> and <!-- /PLAN --> markers)
    draft = re.sub(r'<!--\s*PLAN\s*-->.*?<!--\s*/PLAN\s*-->', '', draft, flags=re.DOTALL).strip()

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

    # ── Summarize section (skip for quick research) ──
    summary = ""
    if not is_quick:
        summarize_prompt = Prompter(prompt_template="deep_research/summarize").render(
            data={
                "section_title": section["title"],
                "section_content": draft,
            }
        )

        model = await _provision_model(summarize_prompt, config, max_tokens=512)
        ai_message = await _llm_invoke(model, summarize_prompt)
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
    else:
        # For quick research, emit summarize_done immediately so frontend shows completion
        _add_event("summarize_done", {
            "section": section_title,
            "section_index": section_index,
            "summary": "",
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
        is_quick = state.get("research_type") == "quick"
        outline = state["outline"]
        drafts = state["section_drafts"]

        if is_quick:
            # Quick Research: directly concatenate drafts (no LLM compile)
            compiling_events = _emit_event(state, "compiling", {})
            await _update_job(state, {"events": compiling_events})
            state = {**state, "events": compiling_events}

            parts = []
            for i, (section, draft) in enumerate(zip(outline, drafts)):
                # Check if draft already starts with the section title (LLM often includes it)
                draft_stripped = draft.strip()
                title = section['title']
                if draft_stripped.startswith(f"## {title}") or draft_stripped.startswith(f"# {title}"):
                    parts.append(draft_stripped)
                else:
                    parts.append(f"## {title}\n\n{draft_stripped}")
            final_report = "\n\n---\n\n".join(parts)
        else:
            # Deep Research: incremental section-by-section LLM compile
            compiling_events = _emit_event(state, "compiling", {})
            await _update_job(state, {"events": compiling_events})
            state = {**state, "events": compiling_events}

            compiled_parts: list[str] = []
            outline_formatted = _format_outline(outline)

            for i, (section, draft) in enumerate(zip(outline, drafts)):
                is_first = (i == 0)
                is_last = (i == len(outline) - 1)

                # Build current draft with title
                draft_stripped = draft.strip()
                title = section['title']
                if draft_stripped.startswith(f"## {title}") or draft_stripped.startswith(f"# {title}"):
                    current_draft = draft_stripped
                else:
                    current_draft = f"## {title}\n\n{draft_stripped}"

                # Already compiled sections as context
                compiled_so_far = "\n\n".join(compiled_parts) if compiled_parts else ""

                prompt = Prompter(prompt_template="deep_research/compile_section").render(
                    data={
                        "question": state["question"],
                        "outline": outline_formatted,
                        "compiled_so_far": compiled_so_far,
                        "current_draft": current_draft,
                        "is_first_section": is_first,
                        "is_last_section": is_last,
                    }
                )

                model = await _provision_model(prompt, config, max_tokens=8192)
                ai_message = await _llm_invoke(model, prompt)

                content = extract_text_content(ai_message.content)
                compiled_section = clean_thinking_content(content)
                compiled_parts.append(compiled_section)

                logger.info(
                    f"Deep Research: compiled section [{i}] "
                    f"'{title}' ({len(compiled_section)} chars)"
                )

                compile_events = _emit_event(state, "compile_section_done", {
                    "section": title,
                    "section_index": i,
                    "compiled_count": i + 1,
                    "total_sections": len(outline),
                })
                state = {**state, "events": compile_events}

                await _update_job(state, {
                    "status": f"Compiling: {title} ({i + 1}/{len(outline)})",
                    "events": compile_events,
                })

            final_report = "\n\n".join(compiled_parts)

        research_label = "Quick" if is_quick else "Deep"
        logger.info(f"{research_label} Research: compiled final report ({len(final_report)} chars)")

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

