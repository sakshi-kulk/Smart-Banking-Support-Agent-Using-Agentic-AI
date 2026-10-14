"""Per-invocation context used to enforce the chat confirmation boundary."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolRunContext:
    customer_id: str
    confirmation_authorized: bool = False
    candidate: dict[str, Any] | None = None
    idempotency_key: str | None = None
    results: dict[str, Any] = field(default_factory=dict)


current_tool_context: ContextVar[ToolRunContext | None] = ContextVar("banking_tool_context", default=None)