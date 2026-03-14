"""Command for generating PPT markdown via LLM."""

import time
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.database.repository import set_current_user_db
from open_notebook.exceptions import ConfigurationError

SYSTEM_PROMPT = """\
You are a presentation expert. Convert the following report into a well-structured \
Markdown presentation using Marp format (slides separated by ---).

Rules:
- Keep the output language identical to the input report language
- Each slide should have a clear title (## heading)
- Use bullet points for key information
- Include a title slide and a summary/conclusion slide
- Keep each slide concise (3-5 bullet points max)
- Do NOT wrap the output in code fences; output raw Markdown only
"""


class GeneratePptInput(CommandInput):
    note_ppt_id: str  # note_ppt record ID
    note_content: str  # the note's markdown content
    note_title: str  # for context
    user_prompt: Optional[str] = None
    user_db_name: Optional[str] = None


class GeneratePptOutput(CommandOutput):
    success: bool
    note_ppt_id: str
    processing_time: float
    error_message: Optional[str] = None


@command(
    "generate_ppt",
    app="open_notebook",
    retry={
        "max_attempts": 3,
        "wait_strategy": "exponential_jitter",
        "wait_min": 2,
        "wait_max": 30,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def generate_ppt_command(
    input_data: GeneratePptInput,
) -> GeneratePptOutput:
    """Generate PPT-style markdown from a note using the default chat model."""
    start_time = time.time()

    # Restore user database context
    set_current_user_db(input_data.user_db_name)

    try:
        from open_notebook.ai.provision import provision_langchain_model
        from open_notebook.domain.note_ppt import NotePpt
        from open_notebook.utils import clean_thinking_content
        from open_notebook.utils.text_utils import extract_text_content

        # Update status to running
        ppt = await NotePpt.get(input_data.note_ppt_id)
        ppt.status = "running"
        await ppt.save()

        logger.info(f"Generating PPT for {input_data.note_ppt_id}")

        # Build prompt
        system = SYSTEM_PROMPT
        if input_data.user_prompt:
            system += f"\nUser's additional requirements: {input_data.user_prompt}\n"

        system += "\n# REPORT CONTENT"

        payload = [
            SystemMessage(content=system),
            HumanMessage(content=input_data.note_content),
        ]

        # Use default chat model (model_id=None)
        chain = await provision_langchain_model(
            str(payload), None, "chat", max_tokens=8192
        )
        response = await chain.ainvoke(payload)

        raw = extract_text_content(response.content)
        cleaned = clean_thinking_content(raw)

        # Save result
        ppt.content = cleaned
        ppt.status = "completed"
        await ppt.save()

        processing_time = time.time() - start_time
        logger.info(
            f"PPT generated for {input_data.note_ppt_id} in {processing_time:.1f}s"
        )

        return GeneratePptOutput(
            success=True,
            note_ppt_id=input_data.note_ppt_id,
            processing_time=processing_time,
        )

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"PPT generation failed for {input_data.note_ppt_id}: {e}")

        # Mark as failed
        try:
            from open_notebook.domain.note_ppt import NotePpt

            ppt = await NotePpt.get(input_data.note_ppt_id)
            ppt.status = "failed"
            ppt.error_message = str(e)[:500]
            await ppt.save()
        except Exception:
            pass

        return GeneratePptOutput(
            success=False,
            note_ppt_id=input_data.note_ppt_id,
            processing_time=processing_time,
            error_message=str(e)[:500],
        )
