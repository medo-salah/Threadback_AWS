"""
Deterministic demo dataset for Threadback M3 / M13.

Provides in-memory, reproducible IntentThread data representing realistic
personal-context scenarios specified across M0–M13.

All identifiers, timestamps, confidence scores, and dependency relations
are fixed and deterministic across runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.enums import (
    CommitmentStatus,
    DependencyStatus,
    EvidenceType,
    Priority,
    ThreadEventType,
    ThreadStatus,
)
from app.domain.models import (
    Commitment,
    Dependency,
    Event,
    Evidence,
    IntentEvolution,
    IntentThread,
    ThreadEvent,
)

# ---------------------------------------------------------------------------
# Deterministic timestamp anchors (fixed UTC datetimes)
# ---------------------------------------------------------------------------
_T1 = datetime(2026, 9, 15, 9, 0, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 9, 18, 11, 0, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
_T4 = datetime(2026, 9, 21, 8, 30, 0, tzinfo=timezone.utc)
_T5 = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
_T6 = datetime(2026, 9, 25, 14, 30, 0, tzinfo=timezone.utc)
_T7 = datetime(2026, 9, 26, 11, 15, 0, tzinfo=timezone.utc)
_T8 = datetime(2026, 9, 27, 18, 0, 0, tzinfo=timezone.utc)
_T9 = datetime(2026, 9, 28, 15, 0, 0, tzinfo=timezone.utc)

# Due dates
_DUE_OCT_12 = datetime(2026, 10, 12, 23, 59, 0, tzinfo=timezone.utc)
_DUE_OCT_05 = datetime(2026, 10, 5, 17, 0, 0, tzinfo=timezone.utc)
_DUE_OCT_02 = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
_DUE_OCT_01 = datetime(2026, 10, 1, 23, 59, 0, tzinfo=timezone.utc)
_DUE_NOV_15 = datetime(2026, 11, 15, 0, 0, 0, tzinfo=timezone.utc)


def _build_demo_threads() -> list[IntentThread]:
    """Construct a fresh list of deterministic demo IntentThread instances."""
    return [
        # Scenario 1: University Application (BLOCKED by recommendation letter)
        IntentThread(
            id="thread-university-application",
            title="University Application",
            description="Fall graduate school application requiring letters of recommendation and transcripts",
            original_goal="Submit fall graduate school application packet with recommendations and personal statement",
            current_goal="Submit fall graduate school application packet with recommendations and personal statement",
            status=ThreadStatus.BLOCKED,
            priority=Priority.HIGH,
            created_at=_T1,
            updated_at=_T6,
            last_activity_at=_T6,
            last_interaction_at=_T6,
            confidence=0.94,
            commitments=[
                Commitment(
                    id="com-uni-submit",
                    description="Submit completed application packet",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_12,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-uni-1",
                    type=EvidenceType.CONVERSATION,
                    description="Conversation with Ahmed regarding academic recommendation letter",
                    source="Slack chat #academic-advising",
                    created_at=_T2,
                    confidence=0.95,
                ),
                Evidence(
                    id="evi-uni-2",
                    type=EvidenceType.DOCUMENT,
                    description="Draft personal statement saved in Google Docs",
                    source="Google Drive / Admissions / SOP_v2.docx",
                    created_at=_T3,
                    confidence=0.90,
                ),
            ],
            dependencies=[
                Dependency(
                    id="dep-uni-rec-letter",
                    description="Recommendation letter from Ahmed",
                    type="PERSON",
                    status=DependencyStatus.OPEN,
                    blocking=True,
                ),
            ],
            events=[
                Event(
                    id="evt-uni-1",
                    type="APPLICATION_STARTED",
                    description="Started application portal submission",
                    timestamp=_T1,
                ),
                Event(
                    id="evt-uni-2",
                    type="REMINDER_SENT",
                    description="Followed up with Ahmed about recommendation letter",
                    timestamp=_T6,
                ),
            ],
        ),
        # Scenario 3: Client Report (WAITING on client response, decay signal demo)
        IntentThread(
            id="thread-client-report",
            title="Client Report",
            description="Q3 client analytics report and deliverables for Acme Corp",
            original_goal="Deliver finalized Q3 analytics slide deck and deliverables for Acme Corp",
            current_goal="Deliver finalized Q3 analytics slide deck and deliverables for Acme Corp",
            status=ThreadStatus.WAITING,
            priority=Priority.MEDIUM,
            created_at=_T1,
            updated_at=_T7,
            last_activity_at=_T7,
            last_interaction_at=_T7,
            confidence=0.88,
            commitments=[
                Commitment(
                    id="com-client-deliver",
                    description="Deliver finalized Q3 analytics slide deck",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_05,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-client-1",
                    type=EvidenceType.MESSAGE,
                    description="Email sent to Acme Corp requesting data sign-off",
                    source="Work Email (thread #4481)",
                    created_at=_T7,
                    confidence=0.92,
                ),
                Evidence(
                    id="evi-client-2",
                    type=EvidenceType.DOCUMENT,
                    description="Preliminary Q3 analytics report slide deck delivered to Acme Corp",
                    source="Google Drive / Acme Corp / Deliverables / Q3_Report_v1.pdf",
                    created_at=_T5,
                    confidence=0.88,
                ),
            ],
            dependencies=[
                Dependency(
                    id="dep-client-response",
                    description="Client response and data sign-off on Q3 deliverables",
                    type="CLIENT",
                    status=DependencyStatus.OPEN,
                    blocking=True,
                ),
            ],
            events=[
                Event(
                    id="evt-client-1",
                    type="DRAFT_DELIVERED",
                    description="Shared preliminary draft with client team",
                    timestamp=_T5,
                ),
                Event(
                    id="evt-client-2",
                    type="AWAITING_CLIENT",
                    description="Awaiting client confirmation",
                    timestamp=_T7,
                ),
            ],
        ),
        # Scenario 3: Dentist Appointment (ACTIVE, with INTENT EVOLUTION, M13)
        IntentThread(
            id="thread-dentist-appointment",
            title="Dentist Appointment",
            description="Routine dental checkup and teeth cleaning schedule",
            original_goal="Schedule routine dental checkup",
            current_goal="Schedule dental checkup and teeth cleaning with Dr. Smith",
            status=ThreadStatus.ACTIVE,
            priority=Priority.MEDIUM,
            created_at=_T4,
            updated_at=_T5,
            last_activity_at=_T5,
            last_interaction_at=_T5,
            confidence=0.82,
            commitments=[
                Commitment(
                    id="com-dentist-confirm",
                    description="Call clinic to confirm Friday appointment time",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_02,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-dentist-1",
                    type=EvidenceType.NOTE,
                    description="Reminder note to reschedule dental cleaning",
                    source="Apple Notes",
                    created_at=_T4,
                    confidence=0.85,
                ),
            ],
            dependencies=[
                Dependency(
                    id="dep-dentist-schedule",
                    description="Clinic schedule availability check",
                    type="CALENDAR",
                    status=DependencyStatus.RESOLVED,
                    blocking=False,
                ),
            ],
            evolutions=[
                IntentEvolution(
                    id="evo-dentist-1",
                    thread_id="thread-dentist-appointment",
                    previous_goal="Schedule routine dental checkup",
                    revised_goal="Schedule dental checkup and teeth cleaning with Dr. Smith",
                    reason="User decided to include comprehensive cleaning with Dr. Smith",
                    timestamp=_T5,
                    trigger_event_id="evt-dentist-evolve-1",
                ),
            ],
            events=[
                Event(
                    id="evt-dentist-1",
                    type="NOTE_CREATED",
                    description="Noted need for dental checkup",
                    timestamp=_T4,
                ),
                ThreadEvent(
                    id="evt-dentist-evolve-1",
                    thread_id="thread-dentist-appointment",
                    event_type=ThreadEventType.INTENTION_EVOLVED,
                    type=ThreadEventType.INTENTION_EVOLVED.value,
                    description="Intention evolved: 'Schedule routine dental checkup' → 'Schedule dental checkup and teeth cleaning with Dr. Smith'",
                    timestamp=_T5,
                    actor="user",
                    source="conversational_agent",
                    payload={
                        "previous_goal": "Schedule routine dental checkup",
                        "revised_goal": "Schedule dental checkup and teeth cleaning with Dr. Smith",
                        "reason": "User decided to include comprehensive cleaning with Dr. Smith",
                    },
                ),
            ],
        ),
        # Scenario 5: AWS Hackathon (ACTIVE, HIGH priority, Top Focus demo)
        IntentThread(
            id="thread-aws-hackathon",
            title="AWS Hackathon",
            description="Build and submit Threadback prototype for the Alexa+ hackathon track",
            original_goal="Build and submit Threadback prototype for the Alexa+ hackathon track",
            current_goal="Build and submit Threadback prototype for the Alexa+ hackathon track",
            status=ThreadStatus.ACTIVE,
            priority=Priority.HIGH,
            created_at=_T3,
            updated_at=_T9,
            last_activity_at=_T9,
            last_interaction_at=_T9,
            confidence=0.96,
            commitments=[
                Commitment(
                    id="com-aws-m3",
                    description="Complete M3 domain layer and MCP tools implementation",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_01,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-aws-1",
                    type=EvidenceType.CONVERSATION,
                    description="Team architectural alignment on MCP streamable HTTP contract",
                    source="Hackathon Discord #dev",
                    created_at=_T8,
                    confidence=0.98,
                ),
                Evidence(
                    id="evi-aws-2",
                    type=EvidenceType.DOCUMENT,
                    description="Threadback specification and architectural roadmap",
                    source="docs/architecture.md",
                    created_at=_T3,
                    confidence=0.95,
                ),
            ],
            dependencies=[],
            events=[
                Event(
                    id="evt-aws-1",
                    type="PROJECT_INITIALIZED",
                    description="Repository created and M1 foundation laid",
                    timestamp=_T3,
                ),
                Event(
                    id="evt-aws-2",
                    type="M2_VERIFIED",
                    description="MCP Streamable HTTP foundation verified",
                    timestamp=_T8,
                ),
                Event(
                    id="evt-aws-3",
                    type="M3_STARTED",
                    description="M3 domain layer implementation authorized",
                    timestamp=_T9,
                ),
            ],
        ),
        # Scenario 5: Historical Completed Thread (for testing exclusion and terminal handling)
        IntentThread(
            id="thread-tax-filing-2025",
            title="Tax Filing 2025",
            description="Annual tax return submission for fiscal year 2025",
            original_goal="Annual tax return submission for fiscal year 2025",
            current_goal="Annual tax return submission for fiscal year 2025",
            status=ThreadStatus.COMPLETED,
            priority=Priority.HIGH,
            created_at=_T1,
            updated_at=_T6,
            last_activity_at=_T6,
            last_interaction_at=_T6,
            confidence=0.99,
            commitments=[
                Commitment(
                    id="com-tax-submit",
                    description="File electronic tax return with revenue authority",
                    status=CommitmentStatus.COMPLETED,
                    due_at=_DUE_OCT_01,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-tax-1",
                    type=EvidenceType.DOCUMENT,
                    description="Tax return confirmation receipt",
                    source="Revenue Portal",
                    created_at=_T6,
                    confidence=1.0,
                ),
            ],
            dependencies=[
                Dependency(
                    id="dep-tax-forms",
                    description="W2 and interest statements",
                    type="DOCUMENT",
                    status=DependencyStatus.RESOLVED,
                    blocking=False,
                ),
            ],
            events=[
                Event(
                    id="evt-tax-1",
                    type="TAX_FILED",
                    description="Tax return accepted by authority",
                    timestamp=_T6,
                ),
                ThreadEvent(
                    id="evt-tax-close-1",
                    thread_id="thread-tax-filing-2025",
                    event_type=ThreadEventType.THREAD_COMPLETED,
                    type=ThreadEventType.THREAD_COMPLETED.value,
                    description="Annual tax return submission completed and verified",
                    timestamp=_T6,
                    actor="system",
                    source="deterministic_engine",
                ),
            ],
        ),
        # Scenario 6: Historical Abandoned Thread (for testing exclusion and preservation)
        IntentThread(
            id="thread-old-gym-membership",
            title="Old Gym Membership",
            description="Explore renewing discontinued downtown gym membership",
            original_goal="Explore renewing discontinued downtown gym membership",
            current_goal="Explore renewing discontinued downtown gym membership",
            status=ThreadStatus.ABANDONED,
            priority=Priority.LOW,
            created_at=_T1,
            updated_at=_T4,
            last_activity_at=_T4,
            last_interaction_at=_T4,
            abandoned_reason="Decided to work out from home instead",
            confidence=0.60,
            commitments=[
                Commitment(
                    id="com-gym-visit",
                    description="Visit gym facility for tour",
                    status=CommitmentStatus.CANCELLED,
                ),
            ],
            evidence=[],
            dependencies=[],
            events=[
                Event(
                    id="evt-gym-1",
                    type="THREAD_ABANDONED",
                    description="Decided to work out from home instead",
                    timestamp=_T4,
                ),
            ],
        ),
        # Scenario 7: Professional Certification (DEFERRED, eligible for RESUME, M14)
        IntentThread(
            id="thread-professional-certification",
            title="Professional Certification",
            description="AWS Solutions Architect Professional certification exam preparation",
            original_goal="Complete practice exams and pass AWS Solutions Architect Professional exam",
            current_goal="Complete practice exams and pass AWS Solutions Architect Professional exam",
            status=ThreadStatus.DEFERRED,
            priority=Priority.HIGH,
            created_at=_T1,
            updated_at=_T7,
            last_activity_at=_T7,
            last_interaction_at=_T7,
            deferred_until=_T6,  # Elapsed deferral timestamp -> RESUMABLE!
            confidence=0.92,
            commitments=[
                Commitment(
                    id="com-cert-exam",
                    description="Schedule exam session at authorized testing center",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_12,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-cert-study",
                    type=EvidenceType.DOCUMENT,
                    description="Completed 5 full practice exam simulations with >85% score",
                    source="AWS Skill Builder Portal",
                    created_at=_T7,
                    confidence=0.95,
                ),
            ],
            dependencies=[],
            events=[
                Event(
                    id="evt-cert-1",
                    type="PREPARATION_STARTED",
                    description="Purchased certification study guide and practice tests",
                    timestamp=_T1,
                ),
                ThreadEvent(
                    id="evt-cert-defer-1",
                    thread_id="thread-professional-certification",
                    event_type=ThreadEventType.THREAD_DEFERRED,
                    type=ThreadEventType.THREAD_DEFERRED.value,
                    description="Deferred exam preparation until September 25",
                    timestamp=_T5,
                    actor="user",
                    source="conversational_agent",
                    payload={"deferred_until": _T6.isoformat()},
                ),
            ],
        ),
    ]


def _build_m14_conflict_threads() -> list[IntentThread]:
    """Additional deterministic threads for M14 cross-thread conflict and briefing scenarios."""
    return [
        # Scenario 8: Executive Client Pitch (ACTIVE, HIGH priority, CONFLICT with Board Presentation, M14)
        IntentThread(
            id="thread-client-pitch",
            title="Executive Client Pitch",
            description="Present enterprise transformation proposal to Acme Corp leadership",
            original_goal="Deliver executive presentation and secure sign-off on enterprise proposal",
            current_goal="Deliver executive presentation and secure sign-off on enterprise proposal",
            status=ThreadStatus.ACTIVE,
            priority=Priority.HIGH,
            created_at=_T3,
            updated_at=_T8,
            last_activity_at=_T8,
            last_interaction_at=_T8,
            confidence=0.94,
            commitments=[
                Commitment(
                    id="com-pitch-rehearsal",
                    description="Full-day executive committee presentation and Q&A session",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_01,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-pitch-deck",
                    type=EvidenceType.DOCUMENT,
                    description="Acme Corp Executive Pitch Deck v3.2 finalized",
                    source="Google Drive / Executive / Pitch.pdf",
                    created_at=_T8,
                    confidence=0.96,
                ),
            ],
            dependencies=[
                Dependency(
                    id="dep-pitch-boardroom",
                    description="Executive Boardroom Alpha [EXCLUSIVE_RESOURCE: Executive Boardroom Alpha]",
                    type="EXCLUSIVE_RESOURCE",
                    status=DependencyStatus.OPEN,
                    blocking=True,
                ),
            ],
            events=[
                Event(
                    id="evt-pitch-1",
                    type="PITCH_SCHEDULED",
                    description="Executive committee agreed to scheduled pitch session",
                    timestamp=_T8,
                ),
            ],
        ),
        # Scenario 9: Board Presentation (ACTIVE, HIGH priority, CONFLICT with Client Pitch, M14)
        IntentThread(
            id="thread-board-presentation",
            title="Board Presentation",
            description="Annual strategic investment review presentation with board of directors",
            original_goal="Present annual strategic review and budget expansion to the board",
            current_goal="Present annual strategic review and budget expansion to the board",
            status=ThreadStatus.ACTIVE,
            priority=Priority.HIGH,
            created_at=_T3,
            updated_at=_T8,
            last_activity_at=_T8,
            last_interaction_at=_T8,
            confidence=0.95,
            commitments=[
                Commitment(
                    id="com-board-review",
                    description="Full-day board of directors annual strategy review session",
                    status=CommitmentStatus.OPEN,
                    due_at=_DUE_OCT_01,
                ),
            ],
            evidence=[
                Evidence(
                    id="evi-board-deck",
                    type=EvidenceType.DOCUMENT,
                    description="Board Strategy Review Briefing Pack v1.0",
                    source="Google Drive / Board / Strategy_Review.pdf",
                    created_at=_T8,
                    confidence=0.98,
                ),
            ],
            dependencies=[
                Dependency(
                    id="dep-board-boardroom",
                    description="Executive Boardroom Alpha [EXCLUSIVE_RESOURCE: Executive Boardroom Alpha]",
                    type="EXCLUSIVE_RESOURCE",
                    status=DependencyStatus.OPEN,
                    blocking=True,
                ),
            ],
            events=[
                Event(
                    id="evt-board-1",
                    type="BOARD_MEETING_CALLED",
                    description="Board meeting scheduled for annual investment review",
                    timestamp=_T8,
                ),
            ],
        ),
    ]


def get_demo_threads() -> list[IntentThread]:
    """
    Return a fresh list of deterministic demo IntentThread instances (M0-M13 canonical baseline).
    """
    return _build_demo_threads()


def get_m14_demo_threads() -> list[IntentThread]:
    """
    Return the comprehensive set of deterministic demo IntentThread instances for M14 scenarios,
    including defer/resume, deadline/resource conflicts, and multi-thread briefing aggregation.
    """
    return _build_demo_threads() + _build_m14_conflict_threads()
