import os
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from services.auth import create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(payload: LoginRequest):
    """
    Validates credentials against ADMIN_USERNAME and ADMIN_PASSWORD from .env.
    Returns a signed JWT on success.
    """
    admin_username = os.getenv("ADMIN_USERNAME", "")
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    if not admin_username or not admin_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server auth not configured — set ADMIN_USERNAME and ADMIN_PASSWORD in .env",
        )

    if payload.username != admin_username or payload.password != admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Felaktigt användarnamn eller lösenord",
        )

    token = create_access_token(payload.username)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    """Returns the currently authenticated user."""
    return {"username": current_user}