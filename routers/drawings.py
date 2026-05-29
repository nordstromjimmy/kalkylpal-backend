"""
routers/drawings.py — All HTTP endpoints related to drawings.
"""

import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.drawing import Drawing, ComponentInstance, Project, ManualItem
from services.pdf_parser import find_component_instances, get_pdf_page_as_image, is_scanned_pdf

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

router = APIRouter(prefix="/drawings", tags=["drawings"])


# ── Pydantic schema for manual item creation ──────────────────────────────────

class ManualItemCreate(BaseModel):
    code: str
    base_code: str
    page: int = 1
    x0: Optional[float] = None
    y0: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_drawing(
    file: UploadFile = File(...),
    project_id: int = Query(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = UPLOAD_DIR / unique_filename

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    drawing = Drawing(filename=file.filename, file_path=str(file_path), project_id=project_id)
    db.add(drawing)
    db.commit()
    db.refresh(drawing)

    return {"id": drawing.id, "filename": drawing.filename, "project_id": drawing.project_id}


# ── Scan ──────────────────────────────────────────────────────────────────────

@router.post("/{drawing_id}/scan")
def scan_drawing(
    drawing_id: int,
    search_code: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Scans a drawing, saves ComponentInstances to DB, returns the scan result.
    Re-scanning replaces all previous ComponentInstances for this drawing.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    scanned = is_scanned_pdf(drawing.file_path)
    result = find_component_instances(drawing.file_path, search_code=search_code)

    # Additive scan: when searching for a specific code, only replace instances
    # for that code family — keeping results for other codes intact.
    # This lets users scan TD201, then FD201, and have both stored simultaneously.
    # When no search_code (scan all), replace everything.
    if search_code:
        search_upper = search_code.upper()
        db.query(ComponentInstance).filter(
            ComponentInstance.drawing_id == drawing_id,
            ComponentInstance.base_code.like(f"{search_upper}%")
        ).delete(synchronize_session=False)
    else:
        db.query(ComponentInstance).filter(
            ComponentInstance.drawing_id == drawing_id
        ).delete(synchronize_session=False)

    for base_code, instances in result["components"].items():
        for instance in instances:
            db.add(ComponentInstance(
                code=instance["code"],
                base_code=instance["base_code"],
                page_number=instance["page"],
                x0=instance["x0"], y0=instance["y0"],
                x1=instance["x1"], y1=instance["y1"],
                drawing_id=drawing_id,
            ))
    db.commit()

    # Only return warnings relevant to the search code.
    # If searching for "TD201", warnings about "LD" in other parts of the
    # drawing are not actionable and shouldn't show up.
    all_warnings = result["warnings"]
    if search_code:
        search_upper = search_code.upper()
        relevant_warnings = [
            w for w in all_warnings
            if w["fragment"].upper().startswith(search_upper)
        ]
    else:
        relevant_warnings = all_warnings

    return {
        "drawing_id": drawing_id,
        "filename": drawing.filename,
        "search_code": search_code,
        "is_scanned": scanned,
        "total_found": result["total_found"],
        "components": result["components"],
        "warnings": relevant_warnings,
    }


# ── Restore saved scan result ─────────────────────────────────────────────────

@router.get("/{drawing_id}/scan-result")
def get_scan_result(drawing_id: int, db: Session = Depends(get_db)):
    """
    Reconstructs a scan result from stored ComponentInstances.
    Returns null-equivalent (204) if no scan has been run yet.

    This is how the frontend restores state on page load — the data is already
    in the database from the last scan, we just reshape it to match the scan
    response format the frontend expects.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    instances = db.query(ComponentInstance).filter(
        ComponentInstance.drawing_id == drawing_id
    ).all()

    if not instances:
        # No scan has been run — return 204 so frontend knows to start empty
        return Response(status_code=204)

    # Reshape into the same structure as the scan endpoint returns
    components: dict = {}
    for inst in instances:
        if inst.base_code not in components:
            components[inst.base_code] = []
        components[inst.base_code].append({
            "code": inst.code,
            "base_code": inst.base_code,
            "raw_text": inst.code,      # not stored, use code as fallback
            "quantity_from_text": 1,    # not stored, default to 1
            "page": inst.page_number,
            "x0": inst.x0, "y0": inst.y0,
            "x1": inst.x1, "y1": inst.y1,
        })

    return {
        "drawing_id": drawing_id,
        "is_scanned": False,
        "total_found": len(instances),
        "components": components,
        "warnings": [],  # warnings are not persisted — they're re-generated on next scan
    }


# ── Manual items ──────────────────────────────────────────────────────────────

@router.post("/{drawing_id}/manual-items")
def add_manual_item(drawing_id: int, payload: ManualItemCreate, db: Session = Depends(get_db)):
    """Saves a manually added component to the database."""
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    item = ManualItem(
        code=payload.code.upper(),
        base_code=payload.base_code.upper(),
        page_number=payload.page,
        x0=payload.x0, y0=payload.y0,
        x1=payload.x1, y1=payload.y1,
        drawing_id=drawing_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {
        "id": item.id,
        "code": item.code,
        "base_code": item.base_code,
        "page": item.page_number,
        "x0": item.x0, "y0": item.y0,
        "x1": item.x1, "y1": item.y1,
    }


@router.get("/{drawing_id}/manual-items")
def get_manual_items(drawing_id: int, db: Session = Depends(get_db)):
    """Returns all manually added components for a drawing."""
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    items = db.query(ManualItem).filter(ManualItem.drawing_id == drawing_id).all()

    return [
        {
            "id": item.id,
            "code": item.code,
            "base_code": item.base_code,
            "page": item.page_number,
            "x0": item.x0, "y0": item.y0,
            "x1": item.x1, "y1": item.y1,
        }
        for item in items
    ]


@router.delete("/{drawing_id}/manual-items/{item_id}")
def delete_manual_item(drawing_id: int, item_id: int, db: Session = Depends(get_db)):
    """Deletes a single manually added component."""
    item = db.query(ManualItem).filter(
        ManualItem.id == item_id,
        ManualItem.drawing_id == drawing_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Manual item not found")
    db.delete(item)
    db.commit()
    return {"deleted": True, "item_id": item_id}


# ── Clear all scan data for a drawing ─────────────────────────────────────────

@router.delete("/{drawing_id}/clear-data")
def clear_drawing_data(drawing_id: int, db: Session = Depends(get_db)):
    """
    Deletes all ComponentInstances and ManualItems for a drawing.
    Called when the user clicks 'Rensa' in the UI.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    db.query(ComponentInstance).filter(ComponentInstance.drawing_id == drawing_id).delete()
    db.query(ManualItem).filter(ManualItem.drawing_id == drawing_id).delete()
    db.commit()

    return {"cleared": True, "drawing_id": drawing_id}


# ── Image / info endpoints ────────────────────────────────────────────────────

@router.get("/{drawing_id}/components")
def get_components(drawing_id: int, base_code: Optional[str] = Query(None), db: Session = Depends(get_db)):
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    query = db.query(ComponentInstance).filter(ComponentInstance.drawing_id == drawing_id)
    if base_code:
        query = query.filter(ComponentInstance.base_code == base_code.upper())

    instances = query.all()
    return {
        "drawing_id": drawing_id,
        "count": len(instances),
        "instances": [
            {"id": i.id, "code": i.code, "base_code": i.base_code,
             "page": i.page_number, "x0": i.x0, "y0": i.y0, "x1": i.x1, "y1": i.y1}
            for i in instances
        ]
    }


@router.get("/{drawing_id}/page/{page_number}/image")
def get_page_image(drawing_id: int, page_number: int, dpi: int = Query(150, ge=72, le=300), db: Session = Depends(get_db)):
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    try:
        image_bytes = get_pdf_page_as_image(drawing.file_path, page_number, dpi)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not render page: {str(e)}")
    return Response(content=image_bytes, media_type="image/png")


@router.get("/{drawing_id}/page/{page_number}/info")
def get_page_info(drawing_id: int, page_number: int, db: Session = Depends(get_db)):
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    from services.pdf_parser import get_page_dimensions
    return get_page_dimensions(drawing.file_path, page_number)


# ── Delete drawing ────────────────────────────────────────────────────────────

@router.delete("/{drawing_id}")
def delete_drawing(drawing_id: int, db: Session = Depends(get_db)):
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    db.query(ComponentInstance).filter(ComponentInstance.drawing_id == drawing_id).delete()
    db.query(ManualItem).filter(ManualItem.drawing_id == drawing_id).delete()

    try:
        if os.path.exists(drawing.file_path):
            os.remove(drawing.file_path)
    except Exception:
        pass

    db.delete(drawing)
    db.commit()

    return {"deleted": True, "drawing_id": drawing_id}