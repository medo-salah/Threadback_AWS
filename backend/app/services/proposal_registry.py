"""
Proposal Registry for Threadback (M7/M10).

Preserves exact ActionProposal objects produced during action preparation,
allowing execute_action to validate and execute proposals by deterministic ID
without reconstructing or modifying them.

Supports in-memory caching and optional persistence via BaseThreadRepository (M10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models import ActionProposal
    from app.repositories.base import BaseThreadRepository


class ProposalRegistry:
    """Registry for ActionProposals with in-memory caching and repository persistence."""

    def __init__(self, repository: BaseThreadRepository | None = None) -> None:
        self._proposals: dict[str, ActionProposal] = {}
        self._repository = repository

    def register(self, proposal: ActionProposal) -> ActionProposal:
        """Register an ActionProposal by its authoritative deterministic ID.

        Stores the exact proposal object without mutation or ID regeneration.
        Persists to repository if configured.
        """
        self._proposals[proposal.id] = proposal
        if self._repository is not None:
            self._repository.save_proposal(proposal)
        return proposal

    def get(self, proposal_id: str) -> ActionProposal | None:
        """Retrieve a registered ActionProposal by its ID.

        Returns None if the proposal is not registered.
        """
        if proposal_id in self._proposals:
            return self._proposals[proposal_id]
        if self._repository is not None:
            p = self._repository.get_proposal(proposal_id)
            if p is not None:
                self._proposals[p.id] = p
                return p
        return None

    def list_all(self) -> list[ActionProposal]:
        """Return a list of all currently registered proposals."""
        if self._repository is not None:
            persisted = self._repository.list_proposals()
            for p in persisted:
                self._proposals[p.id] = p
        return list(self._proposals.values())

    def clear(self) -> None:
        """Clear all in-memory registered proposals."""
        self._proposals.clear()

    def __contains__(self, proposal_id: str) -> bool:
        return self.get(proposal_id) is not None

    def __len__(self) -> int:
        return len(self.list_all())
