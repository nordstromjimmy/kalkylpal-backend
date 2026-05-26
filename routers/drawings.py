"""
routers/drawings.py — All HTTP endpoints related to drawings.

A "router" in FastAPI is like a mini-app that handles a group of related endpoints.
We keep drawings endpoints here, projects endpoints in their own file, etc.
This keeps the codebase organized as it grows.

HTTP basics for each endpoint:
    POST   = create something new
    GET    = read/retrieve something
    DELETE = remove something
"""

import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models.drawing import Drawing, ComponentInstance, Project
from services.pdf_parser import find_component_instances, get_pdf_page_as_image

# UPLOAD_DIR is where we store uploaded PDFs on disk
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# APIRouter groups these endpoints together.
# prefix="/drawings" means all routes here start with /drawings
router = APIRouter(prefix="/drawings", tags=["drawings"])


@router.post("/upload")
async def upload_drawing(
    file: UploadFile = File(...),
    project_id: int = Query(..., description="Which project this drawing belongs to"),
    db: Session = Depends(get_db)
):
    """
    Accepts a PDF upload, saves it to disk, stores metadata in the database.

    UploadFile = FastAPI's way of receiving file uploads
    Depends(get_db) = FastAPI automatically runs get_db() and gives us a db session
    """
    # Validate it's a PDF
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Check the project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # Give the file a unique name on disk to avoid collisions
    # uuid4() generates a random unique ID like: a3f2b1c4-...
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = UPLOAD_DIR / unique_filename

    # Read and save the file
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Save metadata to database
    drawing = Drawing(
        filename=file.filename,
        file_path=str(file_path),
        project_id=project_id,
    )
    db.add(drawing)
    db.commit()
    db.refresh(drawing)  # refresh to get the auto-generated id

    return {
        "id": drawing.id,
        "filename": drawing.filename,
        "project_id": drawing.project_id,
        "message": "Drawing uploaded successfully"
    }


@router.post("/{drawing_id}/scan")
def scan_drawing(
    drawing_id: int,
    search_code: Optional[str] = Query(None, description="Filter by component code, e.g. 'TD201'"),
    db: Session = Depends(get_db)
):
    """
    Scans a drawing for component codes and saves the results to the database.

    Steps:
    1. Load the drawing from DB to get the file path
    2. Run the PDF parser
    3. Save all found ComponentInstances to the database
    4. Return the summary

    If search_code is provided (e.g. "TD201"), only that component is returned.
    If not, all detected components are returned.
    """
    # 1. Get drawing from DB
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    # 2. Run the parser
    result = find_component_instances(drawing.file_path, search_code=search_code)

    # 3. Save results to database
    # First delete old results for this drawing (re-scanning replaces previous results)
    db.query(ComponentInstance).filter(
        ComponentInstance.drawing_id == drawing_id
    ).delete()

    new_instances = []
    for base_code, instances in result["components"].items():
        for instance in instances:
            db_instance = ComponentInstance(
                code=instance["code"],
                base_code=instance["base_code"],
                page_number=instance["page"],
                x0=instance["x0"],
                y0=instance["y0"],
                x1=instance["x1"],
                y1=instance["y1"],
                drawing_id=drawing_id,
            )
            db.add(db_instance)
            new_instances.append(instance)

    db.commit()

    # 4. Return summary
    return {
        "drawing_id": drawing_id,
        "filename": drawing.filename,
        "search_code": search_code,
        "total_found": result["total_found"],
        "components": result["components"],
    }


@router.get("/{drawing_id}/components")
def get_components(
    drawing_id: int,
    base_code: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Returns all stored component instances for a drawing.
    Optionally filter by base_code (e.g. "TD201").

    This reads from the database (previously scanned results),
    so it's fast — no PDF processing happens here.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    query = db.query(ComponentInstance).filter(
        ComponentInstance.drawing_id == drawing_id
    )

    if base_code:
        query = query.filter(
            ComponentInstance.base_code == base_code.upper()
        )

    instances = query.all()

    return {
        "drawing_id": drawing_id,
        "count": len(instances),
        "instances": [
            {
                "id": i.id,
                "code": i.code,
                "base_code": i.base_code,
                "page": i.page_number,
                "x0": i.x0, "y0": i.y0,
                "x1": i.x1, "y1": i.y1,
            }
            for i in instances
        ]
    }


@router.get("/{drawing_id}/page/{page_number}/image")
def get_page_image(
    drawing_id: int,
    page_number: int,
    dpi: int = Query(150, ge=72, le=300),
    db: Session = Depends(get_db)
):
    """
    Returns a specific page of a drawing as a PNG image.
    The frontend uses this to display the drawing.

    dpi parameter lets the frontend request higher quality if needed.
    ge=72 means minimum 72 DPI, le=300 means maximum 300 DPI.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    try:
        image_bytes = get_pdf_page_as_image(drawing.file_path, page_number, dpi)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not render page: {str(e)}")

    # Response with media_type tells the browser this is an image
    return Response(content=image_bytes, media_type="image/png")


@router.get("/{drawing_id}/page/{page_number}/info")
def get_page_info(
    drawing_id: int,
    page_number: int,
    db: Session = Depends(get_db)
):
    """
    Returns the dimensions of a PDF page in PDF points.
    The frontend uses this to convert component coordinates to percentage
    positions for the highlight overlay on top of the displayed image.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    from services.pdf_parser import get_page_dimensions
    return get_page_dimensions(drawing.file_path, page_number)


@router.delete("/{drawing_id}")
def delete_drawing(drawing_id: int, db: Session = Depends(get_db)):
    """
    Deletes a drawing and everything associated with it:
      1. All ComponentInstance rows for this drawing (database)
      2. The Drawing row itself (database)
      3. The PDF file on disk

    Order matters — delete child rows (ComponentInstance) before
    the parent (Drawing), otherwise the foreign key constraint will
    reject the deletion.
    """
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # 1. Delete all detected components for this drawing
    db.query(ComponentInstance).filter(
        ComponentInstance.drawing_id == drawing_id
    ).delete()

    # 2. Delete the PDF file from disk (best-effort — don't crash if missing)
    try:
        if os.path.exists(drawing.file_path):
            os.remove(drawing.file_path)
    except Exception:
        pass  # File already gone — that's fine

    # 3. Delete the drawing record from the database
    db.delete(drawing)
    db.commit()

    return {"deleted": True, "drawing_id": drawing_id}