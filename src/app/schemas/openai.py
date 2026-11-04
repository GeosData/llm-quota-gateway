from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[Any]
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: str | list[str] | None = None
    user: str | None = None

    model_config = {"extra": "allow"}


class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChoiceMessage(BaseModel):
    role: str
    content: str | None


class Choice(BaseModel):
    index: int
    message: ChoiceMessage
    finish_reason: str | None


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: UsageInfo
    system_fingerprint: str | None = None

    model_config = {"extra": "allow"}


class QuotaStatusResponse(BaseModel):
    tenant_id: str
    used_tokens: int
    limit: int
    remaining: int
    window_resets_in: int = Field(description="Seconds until the current window resets")
