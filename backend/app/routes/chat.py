"""Chat API: POST /api/chat, GET /api/chat/history."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from app import db
from app.llm import handle_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


@router.post("")
async def post_chat(body: ChatRequest, request: Request) -> dict:
    state = request.app.state
    return await handle_chat(body.message, state.price_cache, state.market_source)


@router.get("/history")
def get_chat_history(limit: int = 100) -> dict:
    return {"messages": db.get_chat_messages(limit=limit)}
