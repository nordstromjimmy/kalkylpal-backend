"""
routers/chat.py — AI chat endpoints for VVS assistant.

Uses Claude claude-sonnet-4-20250514 with web search to answer VVS-related questions.
History is persisted per project in the chat_messages table.
"""

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.drawing import Project, ChatMessage

router = APIRouter(prefix="/projects", tags=["chat"])

SYSTEM_PROMPT = """Du är en expert på VVS (värme, ventilation och sanitet) och hjälper yrkesverksamma rörmokare, ventilationsmontörer och VVS-kalkylatorer i Sverige.

Du hjälper med:
- Tekniska frågor om komponenter, don, armaturer och aggregat
- Installation, dimensionering och injustering
- Produkter från tillverkare som Swegon, Systemair, Lindab, Tour & Andersson, Belimo, IMI Hydronic, Fläktgroup m.fl.
- Svenska regelverk och standarder (BBR, AFS, Boverkets regler, SS-EN)
- Kalkylering, materialval och monteringsanvisningar

Svara alltid på svenska. Anta att användaren har yrkeserfarenhet inom VVS — använd branschterminologi och var konkret och praktisk. Om du söker produktinformation, prioritera tillverkarens egna datablad och monteringsanvisningar."""


class ChatRequest(BaseModel):
    message: str


@router.post("/{project_id}/chat")
def send_message(project_id: int, payload: ChatRequest, db: Session = Depends(get_db)):
    """
    Sends a user message, calls Claude with web search, saves both messages
    to DB and returns the assistant reply.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured on the server")

    # Load existing history to give Claude conversation context
    history = db.query(ChatMessage).filter(
        ChatMessage.project_id == project_id
    ).order_by(ChatMessage.created_at).all()

    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": payload.message})

    # Save user message before calling API
    db.add(ChatMessage(project_id=project_id, role="user", content=payload.message))
    db.commit()

    # Call Claude with web search enabled
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    # Extract text blocks from response (web search may produce tool_use blocks too)
    answer = "".join(
        block.text for block in response.content if block.type == "text"
    )
    if not answer:
        answer = "Tyvärr kunde jag inte generera ett svar. Försök igen."

    # Save assistant reply
    db.add(ChatMessage(project_id=project_id, role="assistant", content=answer))
    db.commit()

    return {"role": "assistant", "content": answer}


@router.get("/{project_id}/chat")
def get_history(project_id: int, db: Session = Depends(get_db)):
    """Returns the full chat history for a project."""
    messages = db.query(ChatMessage).filter(
        ChatMessage.project_id == project_id
    ).order_by(ChatMessage.created_at).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": str(m.created_at)}
        for m in messages
    ]


@router.delete("/{project_id}/chat")
def clear_history(project_id: int, db: Session = Depends(get_db)):
    """Deletes all chat messages for a project."""
    db.query(ChatMessage).filter(ChatMessage.project_id == project_id).delete()
    db.commit()
    return {"cleared": True}