"""
main.py — The entry point for the FastAPI application.

This file:
1. Creates the FastAPI app instance
2. Sets up CORS (so the React frontend can talk to this backend)
3. Creates database tables
4. Registers all routers
5. Defines a health check endpoint

To start the server, run:
    uvicorn main:app --reload

    main = this file (main.py)
    app = the FastAPI instance below
    --reload = auto-restart when you save changes (dev only)

Then visit:
    http://localhost:8000/docs  ← interactive API documentation (Swagger UI)
    http://localhost:8000       ← health check
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()  # Load .env file so ANTHROPIC_API_KEY is available via os.getenv()

from database import engine, Base
import models.drawing

from routers import drawings, projects
from routers import chat

# Create the FastAPI app
app = FastAPI(
    title="VVS Component Detector",
    description="API for detecting and counting VVS components in PDF drawings",
    version="0.1.0"
)

# CORS = Cross-Origin Resource Sharing.
# Browsers block requests from one domain to another by default.
# Our React frontend (localhost:5173) talks to our backend (localhost:8000).
# These are different "origins", so we need to explicitly allow it.
# In production, replace "*" with your actual frontend domain.
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

app.include_router(projects.router)
app.include_router(drawings.router)
app.include_router(chat.router)


@app.get("/")
def health_check():
    """
    Simple health check endpoint.
    If this returns 200 OK, the server is running.
    Useful later for deployment monitoring.
    """
    return {"status": "ok", "app": "VVS Component Detector", "version": "0.1.0"}