"""Command for generating PPT via LLM + python-pptx."""

import base64
import json
import re
import time
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.database.repository import set_current_user_db
from open_notebook.exceptions import ConfigurationError

SYSTEM_PROMPT = """\
You are a presentation expert. Convert the following report into a structured \
JSON object that describes a PowerPoint presentation.

OUTPUT FORMAT (strict JSON, no code fences):
{
  "slides": [
    {
      "layout": "title_slide",
      "title": "Presentation Title",
      "subtitle": "Author / Date / Subtitle"
    },
    {
      "layout": "title_and_content",
      "title": "Slide Title",
      "content": "- Bullet point 1\\n- Bullet point 2\\n- Bullet point 3"
    },
    {
      "layout": "two_content",
      "title": "Comparison Title",
      "left": "- Left item 1\\n- Left item 2",
      "right": "- Right item 1\\n- Right item 2"
    }
  ]
}

AVAILABLE LAYOUTS (from our custom template):

1. "title_slide" — Cover page with title and subtitle.
   Fields: "title" (main title), "subtitle" (author/date/subtitle text)
   Use: FIRST slide only.

2. "title_and_content" — Standard content slide with title + bullet points.
   Fields: "title" (slide heading), "content" (bullet points, one per line with - prefix)
   Use: Most content slides. Also use for section dividers (put section name as title, summary as content).

3. "two_content" — Two-column slide with title + left and right columns.
   Fields: "title" (slide heading), "left" (left column bullets), "right" (right column bullets)
   Use: Comparisons, pros/cons, before/after.

RULES:
- Keep the output language identical to the input report language
- Start with a "title_slide"
- Use "title_and_content" for most slides
- Use "two_content" for comparisons or pros/cons
- Keep each slide concise (3-5 bullet points max)
- End with a summary/conclusion slide using "title_and_content"
- Aim for 8-15 slides total
- Output ONLY valid JSON, no markdown, no code fences
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
    """Generate PPTX from a note using LLM + python-pptx template."""
    start_time = time.time()

    # Restore user database context
    set_current_user_db(input_data.user_db_name)

    try:
        from open_notebook.ai.provision import provision_langchain_model
        from open_notebook.domain.note_ppt import NotePpt
        from open_notebook.utils import clean_thinking_content
        from open_notebook.utils.pptx_builder import build_pptx
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

        # Parse JSON from LLM response
        # Try to extract JSON from potential code fences
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        json_str = json_match.group(1) if json_match else cleaned

        try:
            slides_data = json.loads(json_str)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            brace_match = re.search(r"\{.*\}", json_str, re.DOTALL)
            if brace_match:
                slides_data = json.loads(brace_match.group(0))
            else:
                raise ValueError("LLM did not return valid JSON for slides")

        slides = slides_data.get("slides", [])
        if not slides:
            raise ValueError("No slides in LLM response")

        logger.info(f"LLM generated {len(slides)} slides for {input_data.note_ppt_id}")

        # Build PPTX
        pptx_bytes = build_pptx(slides)
        pptx_b64 = base64.b64encode(pptx_bytes).decode("utf-8")

        # Save result
        ppt.content = json.dumps(slides_data, ensure_ascii=False, indent=2)
        ppt.pptx_data = pptx_b64
        ppt.status = "completed"
        await ppt.save()

        processing_time = time.time() - start_time
        logger.info(
            f"PPT generated for {input_data.note_ppt_id} in {processing_time:.1f}s "
            f"({len(slides)} slides, {len(pptx_bytes)} bytes)"
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
