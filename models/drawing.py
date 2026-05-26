"""
models/drawing.py — Database table definitions.

Each class here = one table in the database.
Each class attribute = one column in that table.

SQLAlchemy reads these classes and creates the actual
database tables automatically when the app starts.
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Project(Base):
    """
    A Project groups multiple drawings together.
    Example: "Skola Knivsta" contains 10 drawings across different floors.
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # "relationship" tells SQLAlchemy that one Project has many Drawings.
    # This lets us do project.drawings to get all drawings in a project.
    drawings = relationship("Drawing", back_populates="project")


class Drawing(Base):
    """
    A single uploaded PDF drawing.
    Belongs to a Project.
    """
    __tablename__ = "drawings"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)        # original filename
    file_path = Column(String, nullable=False)       # where we stored it on disk
    page_count = Column(Integer, nullable=True)      # how many pages in the PDF
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Foreign key: each Drawing belongs to one Project
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    project = relationship("Project", back_populates="drawings")

    # One Drawing has many detected ComponentInstances
    components = relationship("ComponentInstance", back_populates="drawing")


class ComponentInstance(Base):
    """
    A single detected component on a drawing.
    Example: one instance of "TD201-160" found on page 1 at position (x=234, y=567).

    We store the exact position so we can draw a highlight box on the drawing later.
    """
    __tablename__ = "component_instances"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False)        # e.g. "TD201-160"
    base_code = Column(String, nullable=False)   # e.g. "TD201" (without size suffix)
    page_number = Column(Integer, nullable=False)

    # Position on the page — these come directly from PyMuPDF
    # x0, y0 = top-left corner of the text bounding box
    # x1, y1 = bottom-right corner
    x0 = Column(Float, nullable=False)
    y0 = Column(Float, nullable=False)
    x1 = Column(Float, nullable=False)
    y1 = Column(Float, nullable=False)

    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    drawing = relationship("Drawing", back_populates="components")