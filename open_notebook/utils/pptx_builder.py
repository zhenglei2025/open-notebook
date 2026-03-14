"""Build PPTX files from structured JSON slide data using a custom template."""

import io
import os
from typing import Any

from loguru import logger
from pptx import Presentation
from pptx.util import Pt

# Path to our custom template
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "ppttemplate", "template1.pptx")

# Mapping from layout names to template layout indices
# Based on analysis of template1.pptx:
#   Layout 0: "标题幻灯片" — title(idx=0) + subtitle(idx=1)
#   Layout 1: "标题和内容" — title(idx=0) + body(idx=1) + slide_number(idx=12)
#   Layout 2: "两栏内容"   — title(idx=0) + left(idx=1) + right(idx=2) + slide_number(idx=12)
#   Layout 3: "仅标题"     — title(idx=0) + dateplaceholder + footer + slide_number
#   Layout 4: "空白"       — slide_number(idx=12) only
LAYOUT_MAP = {
    "title_slide": 0,        # Cover: title + subtitle
    "title_and_content": 1,  # Standard content: title + bullet body
    "section_header": 1,     # Reuse title+content for section headers
    "two_content": 2,        # Two columns: title + left + right
    "title_only": 3,         # Title only
    "blank": 4,              # Blank
}


def _get_placeholder(slide: Any, idx: int) -> Any:
    """Get a placeholder by its idx, or None if not found."""
    for shape in slide.placeholders:
        if shape.placeholder_format.idx == idx:
            return shape
    return None


def _set_text_with_bullets(text_frame: Any, text: str) -> None:
    """Set text in a text frame, converting markdown bullets to paragraphs."""
    text_frame.clear()
    lines = text.strip().split("\n")
    first = True
    for line in lines:
        line = line.strip()
        if not line:
            continue
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


def _fill_slide(slide: Any, layout_name: str, data: dict) -> None:
    """Fill a slide based on layout type and data."""
    # Get title placeholder (idx=0) — present in all layouts except blank
    title_ph = _get_placeholder(slide, 0)
    if title_ph and data.get("title"):
        title_ph.text = data["title"]
        logger.debug(f"Set title: '{data['title']}'")

    if layout_name in ("title_slide",):
        # Subtitle placeholder (idx=1)
        subtitle_ph = _get_placeholder(slide, 1)
        if subtitle_ph and data.get("subtitle"):
            subtitle_ph.text = data["subtitle"]

    elif layout_name in ("title_and_content", "section_header"):
        # Body placeholder (idx=1)
        body_ph = _get_placeholder(slide, 1)
        if body_ph and data.get("content"):
            _set_text_with_bullets(body_ph.text_frame, data["content"])
        elif body_ph and data.get("subtitle"):
            # For section_header, put subtitle in the body
            body_ph.text_frame.clear()
            body_ph.text_frame.paragraphs[0].text = data["subtitle"]
            body_ph.text_frame.paragraphs[0].font.size = Pt(24)

    elif layout_name == "two_content":
        # Left (idx=1) and right (idx=2)
        left_ph = _get_placeholder(slide, 1)
        right_ph = _get_placeholder(slide, 2)
        if left_ph and data.get("left"):
            _set_text_with_bullets(left_ph.text_frame, data["left"])
        if right_ph and data.get("right"):
            _set_text_with_bullets(right_ph.text_frame, data["right"])


def build_pptx(slides: list[dict]) -> bytes:
    """
    Build a PPTX file from structured slide data using the custom template.

    Args:
        slides: List of dicts, each with 'layout' key and content fields.

    Returns:
        bytes of the generated .pptx file.
    """
    # Load template
    template_path = os.path.abspath(TEMPLATE_PATH)
    if not os.path.exists(template_path):
        logger.warning(f"Template not found at {template_path}, using default")
        prs = Presentation()
    else:
        prs = Presentation(template_path)
        # Remove all existing slides from the template
        nsmap = {
            'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
            'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        }
        sld_id_lst = prs.element.find('.//p:sldIdLst', nsmap)
        if sld_id_lst is not None:
            for sld_id in list(sld_id_lst):
                rId = sld_id.get(
                    '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
                )
                sld_id_lst.remove(sld_id)
                if rId:
                    try:
                        prs.part.drop_rel(rId)
                    except Exception:
                        pass
        logger.info(f"Loaded template with {len(prs.slide_layouts)} layouts, cleared existing slides")

    # Log available layouts
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
        except Exception as e:
            logger.error(f"Error filling slide {i} ({layout_name}): {e}", exc_info=True)

    logger.info(f"Built PPTX with {len(prs.slides)} slides")

    # Write to bytes
    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.read()
