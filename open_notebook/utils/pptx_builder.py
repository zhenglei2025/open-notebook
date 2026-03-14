"""Build PPTX files from structured JSON slide data using python-pptx."""

import io
from typing import Any

from loguru import logger
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN


# Mapping from our layout names to default template slide layout indices
LAYOUT_MAP = {
    "title_slide": 0,       # Title Slide: title + subtitle
    "title_and_content": 1, # Title and Content: title + body
    "section_header": 2,    # Section Header: title + subtitle
    "two_content": 3,       # Two Content: title + left + right
    "title_only": 5,        # Title Only: title
    "blank": 6,             # Blank: no placeholders
}


def _set_text_with_bullets(text_frame: Any, text: str) -> None:
    """Set text in a text frame, converting markdown bullets to paragraphs."""
    # Clear existing text
    text_frame.clear()

    lines = text.strip().split("\n")
    first = True
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Strip leading bullet markers
        clean = line.lstrip("-*•").strip()
        if not clean:
            continue

        if first:
            p = text_frame.paragraphs[0]
            first = False
        else:
            p = text_frame.add_paragraph()

        p.text = clean
        p.font.size = Pt(18)


def _get_placeholders(slide: Any) -> dict:
    """Get all placeholders as a dict keyed by placeholder idx."""
    result = {}
    for shape in slide.placeholders:
        result[shape.placeholder_format.idx] = shape
    return result


def _fill_slide(slide: Any, layout_name: str, data: dict) -> None:
    """Fill a slide based on layout type and data."""
    phs = _get_placeholders(slide)

    logger.debug(f"Filling {layout_name} slide: placeholders={list(phs.keys())}, data_keys={list(data.keys())}")

    if layout_name == "title_slide":
        # Title slide: idx 0 = title, idx 1 = subtitle
        if 0 in phs and data.get("title"):
            phs[0].text = data["title"]
        if 1 in phs and data.get("subtitle"):
            phs[1].text = data["subtitle"]

    elif layout_name == "title_and_content":
        # Title + Content: idx 0 = title, idx 1 = body
        if 0 in phs and data.get("title"):
            phs[0].text = data["title"]
        if 1 in phs and data.get("content"):
            _set_text_with_bullets(phs[1].text_frame, data["content"])

    elif layout_name == "section_header":
        # Section header: idx 0 = title, idx 1 = subtitle
        if 0 in phs and data.get("title"):
            phs[0].text = data["title"]
        if 1 in phs and data.get("subtitle"):
            phs[1].text = data["subtitle"]

    elif layout_name == "two_content":
        # Two content: idx 0 = title, idx 1 = left, idx 2 = right
        if 0 in phs and data.get("title"):
            phs[0].text = data["title"]
        if 1 in phs and data.get("left"):
            _set_text_with_bullets(phs[1].text_frame, data["left"])
        if 2 in phs and data.get("right"):
            _set_text_with_bullets(phs[2].text_frame, data["right"])

    elif layout_name == "title_only":
        if 0 in phs and data.get("title"):
            phs[0].text = data["title"]

    # Fallback: try to fill using slide.shapes.title if nothing matched
    if data.get("title") and slide.shapes.title is not None:
        if not slide.shapes.title.text:
            slide.shapes.title.text = data["title"]


def build_pptx(slides: list[dict]) -> bytes:
    """
    Build a PPTX file from structured slide data.

    Args:
        slides: List of dicts, each with 'layout' key and content fields.

    Returns:
        bytes of the generated .pptx file.
    """
    prs = Presentation()
    # Set 16:9 aspect ratio
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Log available layouts for debugging
    for i, layout in enumerate(prs.slide_layouts):
        ph_indices = [ph.placeholder_format.idx for ph in layout.placeholders]
        logger.debug(f"Layout {i}: '{layout.name}' placeholders={ph_indices}")

    for i, slide_data in enumerate(slides):
        layout_name = slide_data.get("layout", "title_and_content")
        layout_idx = LAYOUT_MAP.get(layout_name)

        if layout_idx is None:
            logger.warning(f"Unknown layout '{layout_name}' at slide {i}, falling back to title_and_content")
            layout_name = "title_and_content"
            layout_idx = LAYOUT_MAP["title_and_content"]

        if layout_idx >= len(prs.slide_layouts):
            logger.warning(f"Layout index {layout_idx} out of range, falling back to 1")
            layout_idx = 1
            layout_name = "title_and_content"

        slide_layout = prs.slide_layouts[layout_idx]
        slide = prs.slides.add_slide(slide_layout)

        try:
            _fill_slide(slide, layout_name, slide_data)
            logger.debug(f"Slide {i} ({layout_name}): title='{slide.shapes.title.text if slide.shapes.title else 'N/A'}'")
        except Exception as e:
            logger.error(f"Error filling slide {i} ({layout_name}): {e}", exc_info=True)

    # Write to bytes
    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.read()
