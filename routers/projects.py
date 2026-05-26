"""
routers/projects.py — HTTP endpoints for managing projects.

Projects are the top-level container. Everything belongs to a project.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models.drawing import Project, ComponentInstance

router = APIRouter(prefix="/projects", tags=["projects"])


# Pydantic models define the shape of request/response data.
# FastAPI uses these to validate incoming JSON and generate API docs.
class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


@router.post("/")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    """Creates a new project."""
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"id": project.id, "name": project.name, "description": project.description}


@router.get("/")
def list_projects(db: Session = Depends(get_db)):
    """Returns all projects."""
    projects = db.query(Project).all()
    return [
        {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at}
        for p in projects
    ]


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Returns a single project with all its drawings."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "drawings": [
            {"id": d.id, "filename": d.filename, "uploaded_at": d.uploaded_at}
            for d in project.drawings
        ]
    }


@router.get("/{project_id}/summary")
def get_project_summary(project_id: int, db: Session = Depends(get_db)):
    """
    Returns a component count summary across ALL drawings in a project.
    This is the key feature — 'how many TD201 across all 10 drawings?'
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    drawing_ids = [d.id for d in project.drawings]

    if not drawing_ids:
        return {"project": project.name, "total_components": 0, "summary": {}}

    # Get all component instances across all drawings in this project
    instances = db.query(ComponentInstance).filter(
        ComponentInstance.drawing_id.in_(drawing_ids)
    ).all()

    # Build a summary: base_code → {total, per_drawing}
    summary: dict = {}
    for inst in instances:
        if inst.base_code not in summary:
            summary[inst.base_code] = {"total": 0, "per_drawing": {}}

        summary[inst.base_code]["total"] += 1

        drawing_name = next(d.filename for d in project.drawings if d.id == inst.drawing_id)
        if drawing_name not in summary[inst.base_code]["per_drawing"]:
            summary[inst.base_code]["per_drawing"][drawing_name] = 0
        summary[inst.base_code]["per_drawing"][drawing_name] += 1

    return {
        "project": project.name,
        "drawing_count": len(drawing_ids),
        "total_component_instances": len(instances),
        "summary": summary
    }


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """
    Deletes a project and everything under it:
      1. All ComponentInstance rows for every drawing in the project
      2. All Drawing rows (+ their PDF files on disk)
      3. The Project row itself

    Must delete in this order due to foreign key constraints:
    ComponentInstance → Drawing → Project
    """
    from models.drawing import Drawing, ComponentInstance
    import os

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt hittades inte")

    drawings = db.query(Drawing).filter(Drawing.drawing_id == project_id).all() \
        if False else project.drawings  # use the relationship

    for drawing in drawings:
        # Delete component instances for this drawing
        db.query(ComponentInstance).filter(
            ComponentInstance.drawing_id == drawing.id
        ).delete()

        # Delete PDF file from disk
        try:
            if os.path.exists(drawing.file_path):
                os.remove(drawing.file_path)
        except Exception:
            pass

        db.delete(drawing)

    db.delete(project)
    db.commit()

    return {"deleted": True, "project_id": project_id}