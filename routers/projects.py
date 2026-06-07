import json
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models.drawing import Project, ComponentInstance, ManualItem, ProjectBatchResult

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    client: str | None = None
    project_number: str | None = None
    location: str | None = None
    tender_deadline: str | None = None
    contact_person: str | None = None
    notes: str | None = None


@router.post("/")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"id": project.id, "name": project.name, "description": project.description}


@router.get("/")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return [
        {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at}
        for p in projects
    ]


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "client": project.client,
        "project_number": project.project_number,
        "location": project.location,
        "tender_deadline": project.tender_deadline,
        "contact_person": project.contact_person,
        "notes": project.notes,
        "created_at": project.created_at,
        "drawings": [
            {"id": d.id, "filename": d.filename, "uploaded_at": d.uploaded_at}
            for d in project.drawings
        ]
    }


@router.put("/{project_id}")
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    """Updates editable project info fields."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "client": project.client,
        "project_number": project.project_number,
        "location": project.location,
        "tender_deadline": project.tender_deadline,
        "contact_person": project.contact_person,
        "notes": project.notes,
    }

@router.get("/{project_id}/summary")
def get_project_summary(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    drawing_ids = [d.id for d in project.drawings]
    if not drawing_ids:
        return {"project": project.name, "total_components": 0, "summary": {}}

    instances = db.query(ComponentInstance).filter(
        ComponentInstance.drawing_id.in_(drawing_ids)
    ).all()

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


# ── Batch result persistence ──────────────────────────────────────────────────

@router.post("/{project_id}/batch-result")
def save_batch_result(project_id: int, request: dict = Body(...), db: Session = Depends(get_db)):
    """
    Saves (or replaces) the batch scan state for a project.
    Uses upsert: one row per project, overwritten on each save.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = db.query(ProjectBatchResult).filter(
        ProjectBatchResult.project_id == project_id
    ).first()

    data_json = json.dumps(request)

    if existing:
        existing.data = data_json
    else:
        db.add(ProjectBatchResult(project_id=project_id, data=data_json))

    db.commit()
    return {"saved": True}


@router.get("/{project_id}/batch-result")
def get_batch_result(project_id: int, db: Session = Depends(get_db)):
    """
    Returns the saved batch result for a project, or 204 if none exists.
    """
    row = db.query(ProjectBatchResult).filter(
        ProjectBatchResult.project_id == project_id
    ).first()

    if not row:
        return Response(status_code=204)

    return json.loads(row.data)


# ── Delete project ────────────────────────────────────────────────────────────

@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    import os
    from models.drawing import Drawing

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projekt hittades inte")

    for drawing in project.drawings:
        db.query(ComponentInstance).filter(ComponentInstance.drawing_id == drawing.id).delete()
        db.query(ManualItem).filter(ManualItem.drawing_id == drawing.id).delete()
        try:
            if os.path.exists(drawing.file_path):
                os.remove(drawing.file_path)
        except Exception:
            pass
        db.delete(drawing)

    # Delete batch result
    db.query(ProjectBatchResult).filter(ProjectBatchResult.project_id == project_id).delete()

    db.delete(project)
    db.commit()
    return {"deleted": True, "project_id": project_id}


@router.delete("/{project_id}/clear-data")
def clear_project_data(project_id: int, db: Session = Depends(get_db)):
    """
    Clears all scan results and manual items for every drawing in the project.
    Also removes the stored batch result.
    Does NOT delete the drawings themselves or their PDF files.
    """
    from models.drawing import Drawing, ManualItem

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    drawing_ids = [d.id for d in project.drawings]

    if drawing_ids:
        db.query(ComponentInstance).filter(
            ComponentInstance.drawing_id.in_(drawing_ids)
        ).delete(synchronize_session=False)
        db.query(ManualItem).filter(
            ManualItem.drawing_id.in_(drawing_ids)
        ).delete(synchronize_session=False)

    db.query(ProjectBatchResult).filter(
        ProjectBatchResult.project_id == project_id
    ).delete(synchronize_session=False)

    db.commit()
    return {"cleared": True, "project_id": project_id, "drawings_cleared": len(drawing_ids)}