"""
In-memory conversation state management and confirmation detection for M8.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ChatMessage:
    """A single message in a conversation session."""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationSession:
    """
    Ephemeral in-memory conversation state.
    Resets when the backend process restarts.
    """

    conversation_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    pending_proposal_id: str | None = None
    pending_thread_id: str | None = None
    active_thread_id: str | None = None
    pending_confirmation: bool = False

    def add_message(self, role: str, content: str, **metadata: Any) -> None:
        self.messages.append(ChatMessage(role=role, content=content, metadata=metadata))

    def set_pending_proposal(
        self, proposal_id: str, thread_id: str | None = None
    ) -> None:
        self.pending_proposal_id = proposal_id
        self.pending_thread_id = thread_id
        if thread_id:
            self.active_thread_id = thread_id
        self.pending_confirmation = True

    def clear_pending(self) -> None:
        self.pending_proposal_id = None
        self.pending_thread_id = None
        self.pending_confirmation = False


class ConversationManager:
    """Manager for in-memory conversation sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get_or_create(self, conversation_id: str | None = None) -> ConversationSession:
        if not conversation_id:
            conversation_id = f"conv-{uuid.uuid4().hex[:12]}"

        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = ConversationSession(
                conversation_id=conversation_id
            )

        return self._sessions[conversation_id]

    def get(self, conversation_id: str) -> ConversationSession | None:
        return self._sessions.get(conversation_id)

    def reset(self, conversation_id: str) -> bool:
        if conversation_id in self._sessions:
            del self._sessions[conversation_id]
            return True
        return False

    def clear_all(self) -> None:
        self._sessions.clear()


# Patterns for confirmation checking
EXPLICIT_CONFIRMATION_PATTERNS = [
    r"^\s*yes\b",
    r"^\s*yes,?\s+(do it|proceed|go ahead|execute|please|execute it)\b",
    r"^\s*go ahead\b",
    r"^\s*execute\b",
    r"^\s*execute it\b",
    r"^\s*proceed\b",
    r"^\s*confirm\b",
    r"^\s*do it\b",
    r"^\s*sure,?\s+(go ahead|proceed|do it)\b",
    r"^\s*i confirm\b",
    r"^\s*please execute\b",
    r"^\s*please proceed\b",
]

AMBIGUOUS_PATTERNS = [
    r"maybe",
    r"that sounds interesting",
    r"sounds good",
    r"what would happen",
    r"what happens if",
    r"what happens",
    r"tell me more",
    r"okay,?\s+what",
    r"what does that do",
    r"what would that do",
    r"what would it do",
    r"explain",
    r"why",
    r"not sure",
    r"can you clarify",
    r"what happens next",
    r"what if",
]


def is_ambiguous_confirmation(text: str) -> bool:
    """
    Check if the user response is tentative, inquisitive, or vague rather than explicit authorization.
    """
    normalized = text.strip().lower()
    for pattern in AMBIGUOUS_PATTERNS:
        if re.search(pattern, normalized):
            return True

    return False


def is_explicit_confirmation(text: str) -> bool:
    """
    Check if the user response constitutes an explicit affirmative confirmation.
    Must be unambiguous authorization.
    Rejects any input containing ambiguous or inquisitive phrases.
    """
    normalized = text.strip().lower()
    if is_ambiguous_confirmation(normalized):
        return False

    # Check exact single words and standard short phrases
    if normalized in {
        "yes",
        "yes.",
        "yes!",
        "confirm",
        "proceed",
        "go ahead",
        "do it",
        "execute",
        "execute it",
        "yes, go ahead",
        "yes, go ahead.",
        "yes go ahead",
        "yes, proceed",
        "yes proceed",
        "yes, do it",
        "yes do it",
        "please execute",
        "please proceed",
        "i confirm",
        "sure, go ahead",
    }:
        return True

    for pattern in EXPLICIT_CONFIRMATION_PATTERNS:
        if re.search(pattern, normalized):
            return True

    return False
