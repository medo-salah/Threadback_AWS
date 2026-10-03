"""
Threadback MCP Server — M10 Intent Memory & Lifecycle Closure.

Exposes a Streamable HTTP MCP endpoint at /mcp with Threadback's
nine canonical domain tools:
  - discover_unfinished_threads  (M3)
  - get_thread_context           (M3)
  - find_thread_blockers         (M3)
  - analyze_thread               (M4)
  - suggest_next_action          (M5)
  - prepare_action               (M6)
  - execute_action               (M7)
  - verify_thread_completion     (M10)
  - close_thread                 (M10)

Protocol: MCP 2025-11-25 (Streamable HTTP)
Transport: Streamable HTTP
Tools: Exactly 9 canonical tools

Architecture boundary
---------------------
MCP tools
    |
Thread service / Analysis service / Next Action service / Action Preparation service
    |
Domain models / repository
    |
Demo data
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.applications import Starlette

from app.config import settings
from app.domain.models import (
    ActionProposalResponse,
    CloseThreadResponse,
    DiscoverThreadsResponse,
    ExecutionResultResponse,
    NextActionResponse,
    ThreadAnalysisResponse,
    ThreadBlockersResponse,
    ThreadContextResponse,
    ThreadVerificationResponse,
)
from app.services.action_preparation_service import ActionPreparationService
from app.services.analysis_service import AnalysisService
from app.services.execution_service import ExecutionService
from app.services.lifecycle_service import LifecycleService
from app.services.next_action_service import NextActionService
from app.services.proposal_registry import ProposalRegistry
from app.services.thread_service import ThreadNotFoundError, ThreadService
from app.services.verification_service import VerificationService

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp_server = MCPServer(
    name=settings.app_name,
    title="Threadback",
    description=(
        "Agentic personal-context system that discovers unfinished intentions, "
        "reconstructs their context, identifies blockers, and helps close open loops."
    ),
    version=settings.app_version,
)

# ---------------------------------------------------------------------------
# Domain service instances
# ---------------------------------------------------------------------------

thread_service = ThreadService()
analysis_service = AnalysisService()
next_action_service = NextActionService(analysis_service)
proposal_registry = ProposalRegistry(repository=thread_service.repository)
action_preparation_service = ActionPreparationService(registry=proposal_registry)
execution_service = ExecutionService(
    proposal_registry=proposal_registry,
    thread_service=thread_service,
)
verification_service = VerificationService(thread_service=thread_service)
lifecycle_service = LifecycleService(
    thread_service=thread_service,
    verification_service=verification_service,
)

# ---------------------------------------------------------------------------
# Tool 1: discover_unfinished_threads (READ-ONLY)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def discover_unfinished_threads(
    status: str | None = None,
    limit: int | None = None,
) -> DiscoverThreadsResponse:
    """Find active, blocked, waiting, or otherwise unfinished intent threads.

    Queries the thread repository for open intent threads that require attention or
    action. Completed and abandoned threads are excluded from discovery.

    Args:
        status: Optional filter by thread status (e.g. 'ACTIVE', 'BLOCKED', 'WAITING').
                Only unfinished statuses match; completed and abandoned are excluded.
        limit: Optional maximum number of threads to return. Must be non-negative.

    Returns:
        DiscoverThreadsResponse containing a list of thread summaries with ID, title,
        status, priority, confidence score, last activity timestamp, open commitments
        count, and open blockers count.

    Limitations:
        Does not return COMPLETED or ABANDONED threads. Read-only operation.
    """
    try:
        threads = thread_service.list_threads(status=status, limit=limit)
    except ValueError as err:
        raise ToolError(str(err)) from err

    summaries = [t.to_summary() for t in threads]
    return DiscoverThreadsResponse(threads=summaries)


# ---------------------------------------------------------------------------
# Tool 2: get_thread_context (READ-ONLY)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def get_thread_context(
    thread_id: str,
) -> ThreadContextResponse:
    """Retrieve the complete structured context of a specific intent thread.

    Fetches the full domain representation of the requested thread, including metadata,
    commitments, evidence items, dependencies, and chronological events.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        ThreadContextResponse containing the complete thread object and all associated
        commitments, evidence records, dependencies, and event history.

    Limitations:
        Returns a tool error if the thread ID does not exist. Read-only operation.
    """
    try:
        thread = thread_service.get_thread(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err

    return ThreadContextResponse.from_thread(thread)


# ---------------------------------------------------------------------------
# Tool 3: find_thread_blockers (READ-ONLY)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def find_thread_blockers(
    thread_id: str,
) -> ThreadBlockersResponse:
    """Inspect blockers and dependencies for a specific intent thread.

    Identifies active blockers for the specified thread. A dependency is considered
    an active blocker only when structured metadata confirms blocking=True and
    status=OPEN. Non-blocking or resolved dependencies are excluded.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        ThreadBlockersResponse containing the thread ID, the list of active blockers,
        and an overall blocking status ('BLOCKED' if active blockers exist, 'UNBLOCKED' otherwise).

    Limitations:
        Blockers are evaluated strictly from structured dependency records, not inferred
        from prose descriptions. Returns an empty blocker list if no active blockers exist.
        Read-only operation.
    """
    try:
        blockers = thread_service.find_blockers(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err

    blocking_status = "BLOCKED" if blockers else "UNBLOCKED"
    return ThreadBlockersResponse(
        thread_id=thread_id,
        blockers=blockers,
        blocking_status=blocking_status,
    )


# ---------------------------------------------------------------------------
# Tool 4: analyze_thread (READ-ONLY, M4)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def analyze_thread(
    thread_id: str,
) -> ThreadAnalysisResponse:
    """Analyze an IntentThread deterministically and return a structured explanation.

    Produces a complete deterministic analysis of the specified thread including:
    evidence aggregation, commitment analysis, blocker identification, unfinished
    reasoning, attention signal calculation, and confidence scoring.

    All analysis is derived strictly from structured domain data. No LLM, no
    external APIs, no probabilistic inference.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        ThreadAnalysisResponse containing a complete ThreadAnalysis with:
        current status, explanation, unfinished reasons, open commitments,
        active blockers with supporting evidence, evidence summary with
        confidence bands, deterministic attention signal, and overall confidence.

    Limitations:
        Analysis is deterministic and pre-LLM. Confidence scores are derived from
        structured evidence records, not from language model interpretation.
        Read-only operation.
    """
    try:
        thread = thread_service.get_thread(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err

    analysis = analysis_service.analyze(thread)
    return ThreadAnalysisResponse(analysis=analysis)


# ---------------------------------------------------------------------------
# Tool 5: suggest_next_action (READ-ONLY / PLANNING, M5)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def suggest_next_action(
    thread_id: str,
) -> NextActionResponse:
    """Recommend the deterministic next action for an unfinished IntentThread.

    Evaluates the structured thread data and M4 analysis to recommend a concrete,
    explainable next step. Follows a strict deterministic decision order:
      1. Terminal threads (COMPLETED/ABANDONED) → NO_ACTION
      2. Insufficient evidence → GATHER_EVIDENCE_ACTION
      3. Active blocker → UNBLOCKER_ACTION
      4. Waiting dependency → FOLLOW_UP_ACTION
      5. Open commitment → DIRECT_NEXT_ACTION
      6. Thread-level review → DIRECT_NEXT_ACTION
      7. Fallback → NO_ACTION

    Planning only — does NOT execute actions. All recommendations are derived
    strictly from structured domain data without an LLM.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        NextActionResponse containing the NextActionSuggestion with:
        action_type, action description, structured rationale, confidence score,
        supporting source IDs (evidence, commitments, dependencies),
        preconditions, and confirmation requirement flag.

    Limitations:
        Does not execute actions. Recommends planning steps only. Read-only operation.
    """
    try:
        thread = thread_service.get_thread(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err

    analysis = analysis_service.analyze(thread)
    suggestion = next_action_service.suggest_action(thread, analysis)
    return NextActionResponse(suggestion=suggestion)


# ---------------------------------------------------------------------------
# Tool 6: prepare_action (PLANNING / PREPARATION, M6)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def prepare_action(
    thread_id: str,
) -> ActionProposalResponse:
    """Prepare a structured, reviewable action proposal for an IntentThread.

    Converts the deterministic next action suggestion into an explicit, transparent
    ActionProposal specifying:
      - title and detailed description
      - rationale
      - review status (READY, CONFIRMATION_REQUIRED, or BLOCKED)
      - risk level (LOW, MEDIUM, or HIGH)
      - required inputs and preconditions
      - confirmation reason (if external side effects would occur)
      - supporting source IDs (evidence, commitments, dependencies)

    Pre-execution only — does NOT execute actions, send messages, call external
    APIs, or mutate state. Actual execution is reserved for future milestones.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        ActionProposalResponse containing the structured ActionProposal ready
        for human review.

    Limitations:
        Does not execute actions. If essential information (such as recipient)
        is missing, the proposal is marked BLOCKED rather than guessing or fabricating.
        Read-only preparation artifact.
    """
    try:
        thread = thread_service.get_thread(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err

    analysis = analysis_service.analyze(thread)
    suggestion = next_action_service.suggest_action(thread, analysis)
    proposal = action_preparation_service.prepare_action(thread, suggestion)
    proposal_registry.register(proposal)
    return ActionProposalResponse(proposal=proposal)


# ---------------------------------------------------------------------------
# Tool 7: execute_action (CONTROLLED EXECUTION / SIMULATED, M7)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def execute_action(
    proposal_id: str,
    confirmed: bool = False,
    execution_mode: str = "SIMULATED",
) -> ExecutionResultResponse:
    """Execute a prepared action proposal in controlled simulation mode (M7).

    Validates and executes an existing ActionProposal registered by prepare_action.
    Follows a strict 7-step validation pipeline:
      1. Proposal existence: proposal must be registered in the in-memory ProposalRegistry.
      2. Proposal status: BLOCKED proposals are rejected immediately.
      3. Explicit confirmation: proposals requiring confirmation must have confirmed=True.
         Confirmation is NEVER inferred from context, status, or tool invocation.
      4. Preconditions: all proposal preconditions must be satisfied by current thread state.
      5. Source thread existence: the thread must exist in ThreadService.
      6. Terminal thread protection: COMPLETED or ABANDONED threads cannot be acted upon.
      7. Idempotency: re-executing an already executed proposal returns ALREADY_EXECUTED
         without generating duplicate audit events.

    Execution boundary:
      Controlled SIMULATED mode only. Does NOT send emails, SMS, messages, make calls,
      book appointments, process payments, invoke browser automation, or contact
      external APIs. Successful simulation creates an auditable internal Event on the thread.

    Args:
        proposal_id: The deterministic ID of the prepared ActionProposal
                     (e.g. 'proposal-d8e12f6a9c40b3e7').
        confirmed: Explicit boolean confirmation. Required if proposal.requires_confirmation is True.
                   Defaults to False.
        execution_mode: Execution mode string. Must be 'SIMULATED'. Other modes are rejected.

    Returns:
        ExecutionResultResponse containing the outcome status (EXECUTED, REJECTED,
        BLOCKED, or ALREADY_EXECUTED), simulation message, and recorded event_id.
    """
    result = execution_service.execute_action(
        proposal_id=proposal_id,
        confirmed=confirmed,
        execution_mode=execution_mode,
    )
    return ExecutionResultResponse.from_result(result)


# ---------------------------------------------------------------------------
# Tool 8: verify_thread_completion (DETERMINISTIC VERIFICATION, M10)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def verify_thread_completion(
    thread_id: str,
) -> ThreadVerificationResponse:
    """Determine whether an IntentThread has sufficient deterministic evidence to be considered complete (M10).

    Evaluates structured facts against 5 deterministic verification rules:
      - Rule A: No evidence -> not verified
      - Rule B: Blocking dependency -> not verified
      - Rule C: Open commitment -> not verified
      - Rule D: Completion evidence present & no blockers -> verified
      - Rule E: Contradictory evidence -> not verified

    The verification engine uses only structured domain data and evidence records.
    Never uses an LLM to decide completion.
    Does NOT mutate thread status. Verification and closure remain separate operations.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        ThreadVerificationResponse containing verified boolean, confidence score,
        structured explanation reason, matched evidence IDs, and missing evidence items.

    Limitations:
        Does not mutate thread status. Verification is a pre-closure inspection.
    """
    try:
        verification = verification_service.verify_thread(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err

    return ThreadVerificationResponse.from_verification(verification)


# ---------------------------------------------------------------------------
# Tool 9: close_thread (LIFECYCLE CLOSURE, M10)
# ---------------------------------------------------------------------------


@mcp_server.tool()
def close_thread(
    thread_id: str,
) -> CloseThreadResponse:
    """Safely transition a verified IntentThread into COMPLETED status (M10).

    Validates all 7 closure safety rules:
      1. Thread exists.
      2. Thread is not already abandoned.
      3. Thread is not already completed (idempotent result, no duplicate events).
      4. A valid prior verification record exists.
      5. Verification succeeded (verified == True).
      6. Required completion evidence remains valid.
      7. No blocking condition has appeared after verification.

    Close Safety Invariant:
      close_thread cannot bypass verify_thread_completion.
      If any condition fails, the transition is REJECTED and no status mutation occurs.

    Args:
        thread_id: The unique stable identifier of the intent thread
                   (e.g. 'thread-university-application').

    Returns:
        CloseThreadResponse containing thread_id, current status, closure outcome
        (COMPLETED, REJECTED, or ALREADY_COMPLETED), and recorded audit event ID.

    Limitations:
        Cannot be called without prior successful verification.
    """
    try:
        return lifecycle_service.close_thread(thread_id)
    except ThreadNotFoundError as err:
        raise ToolError(f"Thread '{thread_id}' was not found.") from err


# ---------------------------------------------------------------------------
# ASGI application builder
# ---------------------------------------------------------------------------


def build_mcp_app() -> Starlette:
    """Construct and return the MCP Streamable HTTP ASGI application.

    The returned Starlette app is mounted into FastAPI at /mcp.

    streamable_http_path="/" registers the MCP route at the root of the
    sub-app. Combined with FastAPI's mount prefix of /mcp, the public
    endpoint becomes exactly:

        http://localhost:8000/mcp
    """
    return mcp_server.streamable_http_app(
        streamable_http_path="/",
        host="0.0.0.0",
    )
