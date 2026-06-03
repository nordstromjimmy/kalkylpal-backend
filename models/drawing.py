"""
models/drawing.py — Database table definitions.
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    client = Column(String, nullable=True)
    project_number = Column(String, nullable=True)
    location = Column(String, nullable=True)
    tender_deadline = Column(String, nullable=True)
    contact_person = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    drawings = relationship("Drawing", back_populates="project")
    batch_result = relationship("ProjectBatchResult", back_populates="project", uselist=False)


class ProjectBatchResult(Base):
    """
    Stores the last batch scan result for a project as a JSON blob.
    One row per project (upsert pattern).
    Allows restoring batchState on page refresh without re-scanning.
    """
    __tablename__ = "project_batch_results"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), unique=True, nullable=False)
    data = Column(Text, nullable=False)  # JSON string of the full batchState
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", back_populates="batch_result")


class Drawing(Base):
    __tablename__ = "drawings"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    page_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    project = relationship("Project", back_populates="drawings")
    components = relationship("ComponentInstance", back_populates="drawing")
    manual_items = relationship("ManualItem", back_populates="drawing")


class ComponentInstance(Base):
    """A single detected component on a drawing, stored during scan."""
    __tablename__ = "component_instances"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False)
    base_code = Column(String, nullable=False)
    page_number = Column(Integer, nullable=False)
    x0 = Column(Float, nullable=False)
    y0 = Column(Float, nullable=False)
    x1 = Column(Float, nullable=False)
    y1 = Column(Float, nullable=False)

    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    drawing = relationship("Drawing", back_populates="components")


class ManualItem(Base):
    """A component manually added by the user, persisted across sessions."""
    __tablename__ = "manual_items"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False)
    base_code = Column(String, nullable=False)
    page_number = Column(Integer, nullable=False, default=1)
    x0 = Column(Float, nullable=True)
    y0 = Column(Float, nullable=True)
    x1 = Column(Float, nullable=True)
    y1 = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    drawing = relationship("Drawing", back_populates="manual_items")