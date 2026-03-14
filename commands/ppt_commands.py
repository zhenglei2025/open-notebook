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
JSON object that describes a PowerPoint presentation, using our custom template slides.

OUTPUT FORMAT (strict JSON, no code fences):
{
  "slides": [
    {
      "layout": "cover",
      "title": "Presentation Title",
      "subtitle": "Author / Date"
    },
    {
      "layout": "content",
      "title": "Slide Title",
      "badge": "Key Topic",
      "content": "- Main point with explanation\\n- Second point with supporting detail\\n- Third point describing key findings\\n- Fourth point with specific data or examples\\n- Fifth point with implications or next steps"
    },
    {
      "layout": "two_blocks",
      "title": "Comparison",
      "left_title": "Pros",
      "left": "- Advantage 1\\n- Advantage 2",
      "right_title": "Cons",
      "right": "- Disadvantage 1\\n- Disadvantage 2"
    },
    {
      "layout": "three_points",
      "title": "Key Findings",
      "points": [
        {"label": "1", "content": "- Finding detail 1"},
        {"label": "2", "content": "- Finding detail 2"},
        {"label": "3", "content": "- Finding detail 3"}
      ]
    },
    {
      "layout": "ending",
      "title": "Thank You!",
      "subtitle": "Questions?"
    }
  ]
}

AVAILABLE TEMPLATE SLIDES:

1. "cover" — Cover page.
   Fields: "title", "subtitle"
   Use: FIRST slide only.

2. "content" — Content slide with a colored badge label and text body.
   Fields: "title" (heading), "badge" (short label like section name), "content" (bullet text)
   Use: Main content slides. Most commonly used.

3. "content_alt" — Same as content but with a different badge style.
   Fields: "title", "badge", "content"
   Use: Alternate content slides for visual variety.

4. "two_blocks" — Two content blocks side by side.
   Fields: "title", "left_title" (left badge), "left" (left bullets), "right_title" (right badge), "right" (right bullets)
   Use: Comparisons, pros/cons, two categories.

5. "two_rows" — Two content blocks stacked vertically.
   Fields: "title", "top_title" (top badge), "top" (top bullets), "bottom_title" (bottom badge), "bottom" (bottom bullets)
   Use: Sequential information, before/after.

6. "three_points" — Three numbered content areas.
   Fields: "title", "points" (array of 3 objects with "label" and "content")
   Use: Three key findings, three steps, three categories.

7. "four_points" — Four numbered content areas in 2x2 grid.
   Fields: "title", "points" (array of 4 objects with "label" and "content")
   Use: Four aspects, four categories.

8. "ending" — Thank you / closing page.
   Fields: "title" (e.g. "Thank You!"), "subtitle" (closing text)
   Use: LAST slide only.

RULES:
- Keep the output language identical to the input report language
- Start with "cover", end with "ending"
- Use "content" for most slides
- Use "two_blocks" for comparisons or dual perspectives
- Use "three_points" or "four_points" for listing key items
- Alternate between "content" and "content_alt" for visual variety
- Keep each bullet point informative with enough detail
- Include 5-8 bullet points per content slide to fill the space well
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
