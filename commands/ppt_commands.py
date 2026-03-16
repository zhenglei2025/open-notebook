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

IMPORTANT FORMAT RULES (银联模板规范，来源：templateyinlian2.pptx):
- Font: 方正银联黑简体 (used throughout)
- Cover title: 48pt, gray RGB(65,65,65), centered
- Page header: 36pt, gray RGB(130,130,130)
- Level 1 heading: 24pt, gray RGB(65,65,65), bold, ■ square bullet
- Level 2 heading: 18pt, gray RGB(65,65,65), □ hollow square bullet
- Body text: 20pt, gray RGB(65,65,65)
- Emphasis text: red RGB(244,58,62), bold
- Line spacing: 1.5x; paragraph spacing: 0pt before, 0.3pt after
- Number sequences: use 1. 2. 3. for primary level, 1.1 1.2 for secondary
- Max ~200 characters per content slide (about 11 lines of pure text)
- Keep content concise and highlight key points
- Use bullet points for clarity

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
      "title": "Section Title",
      "badge": "Key Topic",
      "content": "- Main point with explanation\\n- Second point with supporting detail\\n- Third point describing key findings"
    },
    {
      "layout": "two_blocks",
      "title": "Comparison",
      "left_title": "Category A",
      "left": "- Point 1\\n- Point 2\\n- Point 3",
      "right_title": "Category B",
      "right": "- Point 1\\n- Point 2\\n- Point 3"
    },
    {
      "layout": "ending",
      "title": "谢  谢！",
      "subtitle": ""
    }
  ]
}

AVAILABLE TEMPLATE SLIDES:

1. "cover" — Cover page.
   Fields: "title", "subtitle"
   Use: FIRST slide only.

2. "content" — Simple content slide for body text and lists (PRIMARY).
   Fields: "title" (page header), "content" (bullet text or paragraphs)
   Use: Main content slides. Use this for MOST slides. Clean layout with title and body text.

3. "content_badges" — Content slide with badge labels and body text.
   Fields: "title" (section badge label), "badge" (secondary badge), "content" (bullet text)
   Use: When you want to emphasize a section with colored badge labels.

4. "two_blocks" — Two content blocks (top and bottom rows).
   Fields: "title" (page header), "left_title" (first row label), "left" (first row bullets), "right_title" (second row label), "right" (second row bullets)
   Use: Comparisons, two categories.

5. "ending" — Thank you / closing page.
   Fields: "title" (e.g. "谢  谢！"), "subtitle" (optional closing text)
   Use: LAST slide only.

CHART LAYOUTS (use when content fits a visual pattern):

8. "arrow_flow" — 5-step arrow flow diagram.
   Fields: "title", "steps" (array of 5 objects with "label" and "content")
   Use: Process flows, value chains, sequential steps.

9. "timeline" — Horizontal timeline with 4 milestones.
   Fields: "title", "milestones" (array of 4 strings)
   Use: Chronological events, development history, project phases.

10. "quadrant" — 4-quadrant analysis chart.
    Fields: "title", "quadrants" (array of 4 objects with "label" and "content")
    Use: SWOT analysis, 2×2 matrix, categorization.

11. "card_4col" — 4 column cards with shared banner.
    Fields: "title", "banner" (subtitle text), "cards" (array of 4 objects with "label" and "content")
    Use: Feature comparison, service overview, key metrics.


13. "cycle_4" — 4-node cycle diagram.
    Fields: "title", "nodes" (array of 4 objects with "label" and "content")
    Use: Iterative processes, feedback loops, cyclical workflows.

14. "compare_list" — 3-column comparison table.
    Fields: "title", "columns" (array of 3 objects with "header" and "items" array of strings)
    Use: Feature comparison, before/after, multi-option evaluation.

15. "pyramid" — 3-level pyramid hierarchy.
    Fields: "title", "levels" (array of 3 objects with "label" and "content", top to bottom)
    Use: Hierarchy, importance ranking, layered architecture.

RULES:
- Keep the output language identical to the input report language
- Start with "cover", end with "ending"
- Use "content" for MOST slides — it is the PRIMARY layout for body text and lists
- Use CHART LAYOUTS when content naturally fits a visual pattern (flows, timelines, comparisons, etc.)
- Each PPT should have 2-4 chart slides mixed with content slides for visual variety
- Use "two_blocks" for comparisons or dual perspectives
- Keep each content slide under 200 characters total
- Keep chart data fields SHORT (under 15 characters for labels, under 50 for content)
- Include 3-5 concise bullet points per content slide
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
