"""Build PPTX files by cloning template slides and replacing text content."""

import copy
import io
import os
from typing import Any

from loguru import logger
from pptx import Presentation
from pptx.util import Pt
from pptx.dml.color import RGBColor

# Path to our custom template
TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "ppttemplate", "template1.pptx"
)

# Template slide catalog (0-indexed)
# Each entry maps a type name to the template slide index and describes
# which shapes to fill and how to identify them.
#
# Slide 1 (idx=0): Cover page - title(ph0) + subtitle(ph1)
# Slide 2 (idx=1): TOC 5 items - title(ph0) + 5 text boxes (项目背景 etc.)
# Slide 6 (idx=5): Content with badge - title(ph0) + badge(对角圆角矩形) + body(圆角矩形)
# Slide 7 (idx=6): Content with badge2 - same structure
# Slide 8 (idx=7): Two blocks - title(ph0) + 2 badges + 2 content areas
# Slide 10 (idx=9): Two rows - title(ph0) + 2 badges + 2 content areas (vertical)
# Slide 11 (idx=10): Three items - title(ph0) + 3 numbered content areas
# Slide 12 (idx=11): Four items - title(ph0) + 4 numbered content areas
# Slide 14 (idx=13): Ending page - title(ph0) + subtitle(ph1)

SLIDE_CATALOG = {
    "cover": {
        "template_index": 0,
        "description": "Cover page with title and subtitle",
    },
    "content": {
        "template_index": 5,  # Slide 6
        "description": "Content slide with a badge label and body text",
    },
    "content_alt": {
        "template_index": 6,  # Slide 7
        "description": "Content slide with badge (alternative style)",
    },
    "two_blocks": {
        "template_index": 7,  # Slide 8
        "description": "Two content blocks side by side",
    },
    "two_rows": {
        "template_index": 9,  # Slide 10
        "description": "Two content blocks stacked vertically",
    },
    "three_points": {
        "template_index": 10,  # Slide 11
        "description": "Three numbered content areas",
    },
    "four_points": {
        "template_index": 11,  # Slide 12
        "description": "Four numbered content areas in 2x2 grid",
    },
    "ending": {
        "template_index": 13,  # Slide 14
        "description": "Thank you / ending page",
    },
}


def _clone_slide(prs: Any, source_slide: Any) -> Any:
    """Clone a slide within the presentation, preserving all shapes and images."""
    slide_layout = source_slide.slide_layout
    new_slide = prs.slides.add_slide(slide_layout)

    # Remove default shapes from new slide
    sp_tree = new_slide.shapes._spTree
    for child in list(sp_tree):
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in ("sp", "pic", "grpSp", "cxnSp", "graphicFrame"):
            sp_tree.remove(child)

    # Copy all shapes from source
    src_tree = source_slide.shapes._spTree
    for child in src_tree:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in ("sp", "pic", "grpSp", "cxnSp", "graphicFrame"):
            sp_tree.append(copy.deepcopy(child))

    # Copy image relationships
    for rel in source_slide.part.rels.values():
        if "image" in rel.reltype.lower():
            new_slide.part.rels.get_or_add(rel.reltype, rel.target_part)

    return new_slide


def _get_text_shapes(slide: Any) -> list[dict]:
    """Get all text-bearing shapes with their metadata, sorted by position."""
    shapes = []
    for i, shape in enumerate(slide.shapes):
        if not shape.has_text_frame:
            continue
        is_ph = shape.is_placeholder
        ph_idx = shape.placeholder_format.idx if is_ph else -1
        shapes.append({
            "index": i,
            "shape": shape,
            "name": shape.name,
            "ph_idx": ph_idx,
            "left": shape.left,
            "top": shape.top,
            "width": shape.width,
            "height": shape.height,
            "text": shape.text_frame.text,
        })
    return shapes


def _set_shape_text(shape: Any, text: str, font_size: int = 18) -> None:
    """Set text in a shape, handling bullet points."""
    tf = shape.text_frame
    tf.clear()
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
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()
        p.text = clean
        p.font.size = Pt(font_size)
        p.font.color.rgb = RGBColor(0, 0, 0)  # Ensure black text
    logger.debug(f"Set shape text ({shape.name}): {tf.text[:50]}")


def _fill_cover(slide: Any, data: dict) -> None:
    """Fill cover slide: title(ph0), subtitle(ph1)."""
    shapes = _get_text_shapes(slide)
    for s in shapes:
        if s["ph_idx"] == 0 and data.get("title"):
            s["shape"].text = data["title"]
        elif s["ph_idx"] == 1 and data.get("subtitle"):
            s["shape"].text = data["subtitle"]


def _fill_content(slide: Any, data: dict) -> None:
    """Fill content slide: title(ph0), badge(对角圆角矩形), body(圆角矩形) + detail below."""
    from pptx.util import Inches, Emu

    shapes = _get_text_shapes(slide)
    logger.debug(f"_fill_content: {len(shapes)} text shapes, data keys={list(data.keys())}")

    content_shape = None
    for s in shapes:
        logger.debug(f"  shape: name='{s['name']}' ph={s['ph_idx']}")
        if s["ph_idx"] == 0 and data.get("title"):
            s["shape"].text = data["title"]
        elif "对角圆角矩形" in s["name"] and data.get("badge"):
            s["shape"].text = data["badge"]
        elif "圆角矩形" in s["name"] and "对角" not in s["name"]:
            content_shape = s["shape"]

    # Enlarge content box and fill
    if content_shape and data.get("content"):
        content_shape.height = Inches(5.5)
        _set_shape_text(content_shape, data["content"], font_size=16)


def _fill_two_blocks(slide: Any, data: dict) -> None:
    """Fill two-block slide: title(ph0), 2 badges(对角圆角矩形), 2 content(圆角矩形)."""
    shapes = _get_text_shapes(slide)

    # Separate badges and content areas, sort by left position
    badges = sorted(
        [s for s in shapes if "对角圆角矩形" in s["name"]],
        key=lambda s: s["left"],
    )
    contents = sorted(
        [s for s in shapes if "圆角矩形" in s["name"] and "对角" not in s["name"]],
        key=lambda s: s["left"],
    )

    for s in shapes:
        if s["ph_idx"] == 0 and data.get("title"):
            s["shape"].text = data["title"]

    if len(badges) >= 1 and data.get("left_title"):
        badges[0]["shape"].text = data["left_title"]
    if len(badges) >= 2 and data.get("right_title"):
        badges[1]["shape"].text = data["right_title"]
    if len(contents) >= 1 and data.get("left"):
        _set_shape_text(contents[0]["shape"], data["left"])
    if len(contents) >= 2 and data.get("right"):
        _set_shape_text(contents[1]["shape"], data["right"])


def _fill_two_rows(slide: Any, data: dict) -> None:
    """Fill two-row slide: title(ph0), 2 badges(对角圆角矩形), 2 content(圆角矩形)."""
    shapes = _get_text_shapes(slide)

    badges = sorted(
        [s for s in shapes if "对角圆角矩形" in s["name"]],
        key=lambda s: s["top"],
    )
    contents = sorted(
        [s for s in shapes if "圆角矩形" in s["name"] and "对角" not in s["name"]],
        key=lambda s: s["top"],
    )

    for s in shapes:
        if s["ph_idx"] == 0 and data.get("title"):
            s["shape"].text = data["title"]

    if len(badges) >= 1 and data.get("top_title"):
        badges[0]["shape"].text = data["top_title"]
    if len(badges) >= 2 and data.get("bottom_title"):
        badges[1]["shape"].text = data["bottom_title"]
    if len(contents) >= 1 and data.get("top"):
        _set_shape_text(contents[0]["shape"], data["top"])
    if len(contents) >= 2 and data.get("bottom"):
        _set_shape_text(contents[1]["shape"], data["bottom"])


def _fill_n_points(slide: Any, data: dict, n: int) -> None:
    """Fill N-point slide: title(ph0), N badges + N content areas."""
    shapes = _get_text_shapes(slide)

    # Sort by top then left to get proper order
    badges = sorted(
        [s for s in shapes if "对角圆角矩形" in s["name"]],
        key=lambda s: (s["top"], s["left"]),
    )
    contents = sorted(
        [s for s in shapes if "圆角矩形" in s["name"] and "对角" not in s["name"]],
        key=lambda s: (s["top"], s["left"]),
    )

    for s in shapes:
        if s["ph_idx"] == 0 and data.get("title"):
            s["shape"].text = data["title"]

    points = data.get("points", [])
    for i in range(min(n, len(points), len(contents))):
        point = points[i]
        if isinstance(point, dict):
            if i < len(badges) and point.get("label"):
                badges[i]["shape"].text = point["label"]
            if point.get("content"):
                _set_shape_text(contents[i]["shape"], point["content"])
        elif isinstance(point, str):
            if i < len(badges):
                badges[i]["shape"].text = str(i + 1)
            _set_shape_text(contents[i]["shape"], point)


def _fill_ending(slide: Any, data: dict) -> None:
    """Fill ending slide: title(ph0), subtitle(ph1)."""
    _fill_cover(slide, data)  # Same structure


FILL_FUNCTIONS = {
    "cover": _fill_cover,
    "content": _fill_content,
    "content_alt": _fill_content,
    "two_blocks": _fill_two_blocks,
    "two_rows": _fill_two_rows,
    "three_points": lambda slide, data: _fill_n_points(slide, data, 3),
    "four_points": lambda slide, data: _fill_n_points(slide, data, 4),
    "ending": _fill_ending,
}


def build_pptx(slides: list[dict]) -> bytes:
    """
    Build a PPTX file by cloning template slides and replacing text.

    Args:
        slides: List of dicts from LLM, each with 'layout' and content fields.

    Returns:
        bytes of the generated .pptx file.
    """
    template_path = os.path.abspath(TEMPLATE_PATH)
    if not os.path.exists(template_path):
        logger.error(f"Template not found at {template_path}")
        raise FileNotFoundError(f"PPT template not found: {template_path}")

    # Load template to use as source for cloning
    source_prs = Presentation(template_path)
    source_slides = list(source_prs.slides)
    logger.info(f"Loaded template: {len(source_slides)} source slides")

    # Create output presentation from the same template, then clear it
    prs = Presentation(template_path)

    nsmap = {
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    sld_id_lst = prs.element.find(".//p:sldIdLst", nsmap)
    if sld_id_lst is not None:
        for sld_id in list(sld_id_lst):
            rId = sld_id.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            sld_id_lst.remove(sld_id)
            if rId:
                try:
                    prs.part.drop_rel(rId)
                except Exception:
                    pass
    logger.info("Cleared output presentation")

    for i, slide_data in enumerate(slides):
        layout_name = slide_data.get("layout", "content")
        catalog_entry = SLIDE_CATALOG.get(layout_name)

        if not catalog_entry:
            logger.warning(f"Unknown layout '{layout_name}' at slide {i}, defaulting to 'content'")
            layout_name = "content"
            catalog_entry = SLIDE_CATALOG["content"]

        template_idx = catalog_entry["template_index"]
        if template_idx >= len(source_slides):
            logger.warning(f"Template index {template_idx} out of range, using 'content'")
            template_idx = SLIDE_CATALOG["content"]["template_index"]
            layout_name = "content"

        # Clone the template slide
        source_slide = source_slides[template_idx]
        new_slide = _clone_slide(prs, source_slide)

        # Fill content
        fill_fn = FILL_FUNCTIONS.get(layout_name)
        if fill_fn:
            try:
                fill_fn(new_slide, slide_data)
                logger.debug(f"Filled slide {i} ({layout_name})")
            except Exception as e:
                logger.error(f"Error filling slide {i} ({layout_name}): {e}", exc_info=True)

    logger.info(f"Built PPTX with {len(prs.slides)} slides")

    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.read()
