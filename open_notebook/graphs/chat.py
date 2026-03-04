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


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        system_prompt = Prompter(prompt_template="chat/system").render(data=state)  # type: ignore[arg-type]
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
                # Fallback: use vector search to find relevant chunks
                # instead of sending the full context
                logger.warning(
                    "Large context model not configured. "
                    "Falling back to vector search with top 5 chunks."
                )
                model, payload = _fallback_to_vector_search(
                    state, model_id, _provision_model
                )
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


def _fallback_to_vector_search(state, model_id, provision_fn):
    """Fallback to vector search when context is too long.

    Uses the user's last message to find the top 5 most relevant chunks
    via vector search, then rebuilds the context from those chunks.
    """
    from open_notebook.domain.notebook import vector_search

    # Get user's last message for search query
    messages = state.get("messages", [])
    user_query = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            user_query = msg.content
            break

    if not user_query:
        from open_notebook.exceptions import ConfigurationError
        raise ConfigurationError(
            "No user message found for vector search fallback."
        )

    # Run vector search to get relevant chunks
    def run_vector_search():
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            return new_loop.run_until_complete(
                vector_search(user_query, 5, True, True)
            )
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)

    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_vector_search)
            search_results = future.result()
    except RuntimeError:
        search_results = asyncio.run(
            vector_search(user_query, 5, True, True)
        )

    # Build context from vector search results
    chunk_context_parts = []
    for i, result in enumerate(search_results or [], 1):
        title = result.get("title", "Unknown")
        content = ""
        for match in result.get("matches", []):
            content += match + "\n"
        if not content:
            content = result.get("content", "")
        chunk_context_parts.append(
            f"[Chunk {i}] {title}:\n{content}"
        )

    chunk_context = "\n\n".join(chunk_context_parts) if chunk_context_parts else ""

    logger.info(
        f"Vector search fallback: found {len(chunk_context_parts)} chunks "
        f"for query: {user_query[:100]}..."
    )

    # Rebuild state with shortened context
    fallback_state = dict(state)
    fallback_state["context"] = {
        "sources": [{"title": "Vector Search Results", "content": chunk_context}],
        "notes": [],
    }

    # Build new payload with shortened context
    system_prompt = Prompter(prompt_template="chat/system").render(data=fallback_state)  # type: ignore[arg-type]
    payload = [SystemMessage(content=system_prompt)] + messages

    # Provision regular chat model (context is now short enough)
    model = provision_fn(str(payload), model_id, "chat", max_tokens=8192)

    return model, payload


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
