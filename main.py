from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from database import engine, Base
import models.drawing

from routers import drawings, projects, chat
from routers import auth as auth_router
from services.auth import get_current_user

app = FastAPI(title="KalkylPal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://kalkylpal.se",
        "https://www.kalkylpal.se",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

# Auth router — no protection needed (login is the entry point)
app.include_router(auth_router.router)

# All other routers require a valid JWT
# Image endpoint is excluded via a public sub-router (see drawings.py)
app.include_router(projects.router, dependencies=[Depends(get_current_user)])
app.include_router(drawings.router, dependencies=[Depends(get_current_user)])
app.include_router(chat.router, dependencies=[Depends(get_current_user)])

# Public image endpoint (can't send auth headers from <img src>)
from fastapi import Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import get_db
from models.drawing import Drawing
from services.pdf_parser import get_pdf_page_as_image
import os

@app.get("/public/drawings/{drawing_id}/page/{page_number}/image")
def get_page_image_public(
    drawing_id: int,
    page_number: int,
    dpi: int = Query(150, ge=72, le=300),
    db: Session = Depends(get_db)
):
    """Public image endpoint — used by <img src> which cannot send auth headers."""
    drawing = db.query(Drawing).filter(Drawing.id == drawing_id).first()
    if not drawing:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Drawing not found")
    try:
        image_bytes = get_pdf_page_as_image(drawing.file_path, page_number, dpi)
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=image_bytes, media_type="image/png")


@app.get("/")
def health_check():
    return {"status": "ok", "app": "KalkylPal", "version": "1.0.0"}