"""
services/pdf_parser.py — The core PDF text extraction logic.
"""

import fitz
import re
from typing import Optional


def extract_text_with_positions(pdf_path: str) -> list[dict]:
    """
    Opens a PDF and extracts every text element with its position.
    """
    results = []
    doc = fitz.open(pdf_path)

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        page_data = page.get_text("dict")

        for block in page_data["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text:
                        continue
                    bbox = span["bbox"]
                    results.append({
                        "text": text,
                        "page": page_number,
                        "x0": bbox[0],
                        "y0": bbox[1],
                        "x1": bbox[2],
                        "y1": bbox[3],
                    })

    doc.close()
    return results


def is_scanned_pdf(pdf_path: str, min_chars: int = 20) -> bool:
    """
    Returns True if the PDF appears to be a scanned image rather than a
    digital/vector drawing.

    A scanned PDF contains no extractable text — just pixel images.
    We check by counting total characters across all pages. If fewer than
    min_chars are found, it's almost certainly a scanned document.

    min_chars=20 is a conservative threshold — even the simplest digital
    drawing title block will have far more than 20 characters.
    """
    doc = fitz.open(pdf_path)
    total_chars = 0
    for page in doc:
        total_chars += len(page.get_text("text").strip())
        if total_chars >= min_chars:
            doc.close()
            return False
    doc.close()
    return total_chars < min_chars


def find_component_instances(
    pdf_path: str,
    search_code: Optional[str] = None
) -> dict:
    """
    Extracts all component codes from a PDF, optionally filtered by search_code.

    Handles:
      - Plain code:      "FD101-160"    → 1 instance
      - Multiplied code: "2xFD101-160"  → 2 instances
      - Truncated code:  "LD" + "02-200/1100" nearby → flagged as warning
    """
    all_text_elements = extract_text_with_positions(pdf_path)

    # Matches a plain component code: TD201-160, RL1, VFD101-250 etc.
    COMPONENT_PATTERN = re.compile(r'^[A-Z]{1,4}\d{1,4}(?:[-/]\S+)*$')

    # Matches a multiplied code: "2xFD101-160", "3xSP201-200" etc.
    MULTIPLIER_PATTERN = re.compile(
        r'^(\d+)[xX]([A-Z]{1,4}\d{1,4}(?:[-/]\S+)*)$',
        re.IGNORECASE
    )

    # Matches the TAIL of a broken component code — digits or /digits that
    # would be the continuation of something like "LD102-200/1100".
    # Examples of tails: "02-200/1100", "101-160", "/1100"
    # This is what appears next to the truncated "LD" on the same line.
    CODE_TAIL_PATTERN = re.compile(r'^\d{1,4}[-/]')

    # Common Swedish drawing abbreviations that appear in title blocks, room labels,
    # and signature fields. These should never be flagged as truncated component codes
    # regardless of what text appears nearby on the same line.
    DRAWING_ABBREVIATION_BLOCKLIST = {
        # Signature/role abbreviations
        "K", "AK", "PS", "A", "E", "VVS", "VS", "BR", "EL", "ELC",
        # Single letters that are never component codes on their own
        "U", "T", "F", "G", "H", "I", "J", "M", "N", "O", "P",
        "Q", "R", "S", "W", "X", "Y", "Z",
        # Room type abbreviations
        "WC", "RWC", "ST", "HWC", "KÖK", "KK", "TV",
        # Drawing/document abbreviations
        "NR", "BET", "REV", "ANT", "SIGN", "DATUM", "SKALA",
        # Compass/direction
        "NO", "NV", "SO", "SV",
    }

    # Y-axis proximity threshold (PDF points) to detect same-line fragments
    SAME_LINE_THRESHOLD = 5

    components: dict[str, list] = {}
    warnings: list[dict] = []

    for element in all_text_elements:
        text = element["text"]

        # --- Multiplied code (e.g. "2xFD101-160") ---
        multiplier_match = MULTIPLIER_PATTERN.match(text)
        if multiplier_match:
            quantity = int(multiplier_match.group(1))
            code = multiplier_match.group(2).upper()

        # --- Plain component code ---
        elif COMPONENT_PATTERN.match(text):
            quantity = 1
            code = text

        # --- Possible truncated fragment: only uppercase letters, 1-4 chars ---
        # We only flag it as a warning if there is a code-tail fragment on the
        # same line — meaning something like "02-200/1100" sits right next to it.
        # This avoids false warnings for normal abbreviations like "WC", "ST" etc.
        elif re.match(r'^[A-Z]{1,4}$', text):
            # Skip known drawing abbreviations — they are never component codes
            if text in DRAWING_ABBREVIATION_BLOCKLIST:
                continue
            same_line = [
                e for e in all_text_elements
                if e is not element
                and e["page"] == element["page"]
                and abs(e["y0"] - element["y0"]) < SAME_LINE_THRESHOLD
            ]
            # Only warn if a code-tail fragment is nearby on the same line
            has_code_tail = any(CODE_TAIL_PATTERN.match(e["text"]) for e in same_line)
            if has_code_tail:
                nearby_texts = [e["text"] for e in same_line]
                warnings.append({
                    "fragment": text,
                    "page": element["page"],
                    "x0": element["x0"],
                    "y0": element["y0"],
                    "x1": element["x1"],
                    "y1": element["y1"],
                    "nearby_text": nearby_texts,
                    "message": (
                        f"Truncated label '{text}' on page {element['page']} — "
                        f"a drawing line may be obscuring a component code "
                        f"(nearby fragments: {nearby_texts}). Please verify manually."
                    )
                })
            continue

        else:
            continue

        # Base code = everything before the first - or /
        base_code = re.split(r'[-/]', code)[0]

        # Filter by search_code using startswith to avoid false substring matches.
        if search_code:
            search_upper = search_code.upper()
            if not code.upper().startswith(search_upper) and not base_code.upper().startswith(search_upper):
                continue

        if base_code not in components:
            components[base_code] = []

        for _ in range(quantity):
            components[base_code].append({
                "code": code,
                "base_code": base_code,
                "raw_text": text,
                "quantity_from_text": quantity,
                "page": element["page"],
                "x0": element["x0"],
                "y0": element["y0"],
                "x1": element["x1"],
                "y1": element["y1"],
            })

    total = sum(len(v) for v in components.values())

    return {
        "total_found": total,
        "components": components,
        "warnings": warnings,
    }


def get_pdf_page_as_image(pdf_path: str, page_number: int, dpi: int = 150) -> bytes:
    """
    Renders a single PDF page as a PNG image (bytes).
    """
    doc = fitz.open(pdf_path)
    page = doc[page_number - 1]
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix)
    image_bytes = pixmap.tobytes("png")
    doc.close()
    return image_bytes


def get_page_dimensions(pdf_path: str, page_number: int) -> dict:
    """
    Returns the width and height of a PDF page in PDF points.

    Why we need this:
    Component coordinates (x0, y0, x1, y1) from PyMuPDF are in PDF points.
    The frontend displays the page as an image and needs to position highlight
    boxes using percentages. The math is:
        left%  = x0 / page_width  * 100
        top%   = y0 / page_height * 100
        width% = (x1 - x0) / page_width  * 100
        height% = (y1 - y0) / page_height * 100
    The zoom factor (DPI) cancels out, so we only need the raw page dimensions.
    """
    doc = fitz.open(pdf_path)
    page = doc[page_number - 1]
    rect = page.rect
    doc.close()
    return {"width": rect.width, "height": rect.height, "page_number": page_number}