import asyncio
import sqlite3
from typing import Annotated, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import ConfigurationError, OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class ThreadState(TypedDict):
    messages: Annotated[list, add_messages]
    notebook: Optional[Notebook]
    context: Optional[str]
    context_config: Optional[dict]
    model_override: Optional[str]


def _run_async_in_thread(coro):
    """Helper to run an async coroutine from sync context, handling nested loops.

    Automatically captures and propagates the current user's database context
    to the new thread, since ContextVar doesn't propagate across threads.
    """
    # Auto-capture database context in the calling thread BEFORE creating new thread
    from open_notebook.database.repository import get_current_user_db
    captured_user_db = get_current_user_db()

    def _in_new_loop():
        # Restore database context in the new thread
        if captured_user_db:
            from open_notebook.database.repository import set_current_user_db
            set_current_user_db(captured_user_db)
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_in_new_loop)
            return future.result()
    except RuntimeError:
        return asyncio.run(coro)


def _augment_context_with_chunks(state: ThreadState) -> ThreadState:
    """Augment context with relevant chunks found via vector search on user's query.

    Scoped to the current notebook's sources via the reference table.
    """
    # Skip RAG augmentation if no_context flag is set
    context_config = state.get("context_config") or {}
    if context_config.get("no_context"):
        logger.info("[RAG] no_context flag set, skipping RAG augmentation")
        return state

    messages = state.get("messages", [])
    user_query = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            user_query = msg.content
            break

    if not user_query:
        logger.info("[RAG] No user query found, skipping augmentation")
        return state

    # Get notebook ID for scoped search
    notebook = state.get("notebook")
    notebook_id = notebook.id if notebook else None
    logger.info(f"[RAG] Starting vector search for query: {user_query[:100]}, notebook_id={notebook_id}")

    try:
        if notebook_id:
            # Notebook-scoped search: only search sources linked to this notebook
            from open_notebook.graphs.deep_research import _notebook_vector_search
            search_results = _run_async_in_thread(
                _notebook_vector_search(user_query, notebook_id, match_count=5)
            )
        else:
            # Fallback: global search if no notebook context
            from open_notebook.domain.notebook import vector_search
            search_results = _run_async_in_thread(
                vector_search(user_query, 5, True, False)
            )
        logger.info(f"[RAG] Vector search returned {len(search_results) if search_results else 0} results")
        if search_results:
            logger.info(f"[RAG] First result title: {search_results[0].get('title', 'N/A')}, similarity: {search_results[0].get('similarity', 'N/A')}")
        else:
            logger.info(f"[RAG] Raw search_results value: {repr(search_results)}")
    except Exception as e:
        logger.warning(f"[RAG] Vector search augmentation failed: {e}")
        return state

    if not search_results:
        logger.info("[RAG] No search results found, skipping augmentation")
        return state

    # Build chunk text from search results
    chunk_parts = []
    for i, result in enumerate(search_results, 1):
        title = result.get("title", "Unknown")
        # _notebook_vector_search returns 'content' (string/list),
        # fn::vector_search returns 'matches' (list)
        content = ""
        matches = result.get("matches")
        if matches and isinstance(matches, list):
            for match in matches:
                content += str(match) + "\n"
        if not content:
            raw_content = result.get("content", "")
            if isinstance(raw_content, list):
                content = "\n".join(str(c) for c in raw_content)
            else:
                content = str(raw_content)
        if content.strip():
            chunk_parts.append(f"[Chunk {i}] {title}:\n{content}")

    if not chunk_parts:
        return state

    logger.info(
        f"RAG augmentation: found {len(chunk_parts)} relevant chunks "
        f"for query: {user_query[:80]}..."
    )

    # Append chunks to existing context
    augmented_state = dict(state)
    context = augmented_state.get("context") or {}
    chunks_text = "\n\n".join(chunk_parts)

    if isinstance(context, dict):
        # Build a clean string from the dict context + chunks
        parts = []
        # Add existing source/note context if any
        for source_ctx in context.get("sources", []):
            if source_ctx:
                parts.append(str(source_ctx))
        for note_ctx in context.get("notes", []):
            if note_ctx:
                parts.append(str(note_ctx))
        # Add RAG chunks
        parts.append(f"# RELEVANT SEARCH RESULTS\n\n{chunks_text}")
        augmented_state["context"] = "\n\n".join(parts)
    else:
        augmented_state["context"] = str(context) + "\n\n# RELEVANT SEARCH RESULTS\n\n" + chunks_text

    return augmented_state


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        # Augment context with relevant chunks via vector search
        augmented_state = _augment_context_with_chunks(state)

        system_prompt = Prompter(prompt_template="chat/system").render(data=augmented_state)  # type: ignore[arg-type]
        payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])
        model_id = config.get("configurable", {}).get("model_id") or state.get(
            "model_override"
        )

        # Helper to provision model (handles async-in-sync)
        def _provision_model(content_str, mid, default_type, **kwargs):
            def run_in_new_loop():
                new_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(new_loop)
                    return new_loop.run_until_complete(
                        provision_langchain_model(
                            content_str, mid, default_type, **kwargs
                        )
                    )
                finally:
                    new_loop.close()
                    asyncio.set_event_loop(None)

            try:
                asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_new_loop)
                    return future.result()
            except RuntimeError:
                return asyncio.run(
                    provision_langchain_model(
                        content_str, mid, default_type, **kwargs
                    )
                )

        try:
            model = _provision_model(str(payload), model_id, "chat", max_tokens=8192)
        except ConfigurationError as ce:
            if "large_context" in str(ce):
                # Fallback: truncate context to last 15000 chars + current query
                logger.warning(
                    "Large context model not configured. "
                    "Falling back to truncated context (last 15000 chars)."
                )
                # Truncate system prompt to last 15000 chars
                truncated_prompt = system_prompt[-15000:] if len(system_prompt) > 15000 else system_prompt
                # Keep only the last user message (current query)
                messages = state.get("messages", [])
                recent_messages = messages[-1:] if messages else []
                payload = [SystemMessage(content=truncated_prompt)] + recent_messages
                model = _provision_model(str(payload), model_id, "chat", max_tokens=8192)
            else:
                raise

        ai_message = model.invoke(payload)

        # Clean thinking content from AI response (e.g., <think>...</think> tags)
        content = extract_text_content(ai_message.content)
        cleaned_content = clean_thinking_content(content)
        cleaned_message = ai_message.model_copy(update={"content": cleaned_content})

        return {"messages": cleaned_message}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e





conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
memory = SqliteSaver(conn)

agent_state = StateGraph(ThreadState)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_edge(START, "agent")
agent_state.add_edge("agent", END)
graph = agent_state.compile(checkpointer=memory)
