"""
Deterministic Mock Model Provider for Threadback (M8/M11).

Executes deterministic intent-to-tool flows through the real MCP server
over Streamable HTTP without requiring AWS credentials or external LLMs.
Implements Alexa+-style conversational interaction and observability for M11.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.base import ModelProvider
from app.agent.state import (
    ConversationSession,
    is_ambiguous_confirmation,
    is_explicit_confirmation,
)
from app.domain.agent_models import AgentChatResponse, ToolActivity

logger = logging.getLogger(__name__)


def _log_agent_observability(
    conv_id: str,
    decision: str,
    tool: str | None = None,
    result_status: str | None = None,
    next_decision: str | None = None,
) -> None:
    """Structured development/demo observability logger tracing agent decision flow."""
    logger.info(
        "[AGENT_OBSERVABILITY] conv=%s decision='%s' tool=%s result_status=%s next_decision='%s'",
        conv_id,
        decision,
        tool or "NONE",
        result_status or "NONE",
        next_decision or "NONE",
    )


def _resolve_target_thread(
    msg_lower: str,
    session: ConversationSession,
    available_threads: list[dict[str, Any]],
) -> tuple[str | None, str | None, bool, bool]:
    """
    Deterministically resolves the target thread from user message and session continuity.

    Returns:
        (thread_id, title, is_ambiguous, is_unknown)
    """
    # 1. Direct topic match by known keywords
    if "application" in msg_lower or "university" in msg_lower or "grad" in msg_lower:
        return ("thread-university-application", "University Application", False, False)
    if "client" in msg_lower or "report" in msg_lower:
        return ("thread-client-report", "Client Q3 Report", False, False)
    if "dentist" in msg_lower or "dental" in msg_lower or "teeth" in msg_lower:
        return ("thread-dentist-appointment", "Dentist Appointment", False, False)
    if "hackathon" in msg_lower or "aws" in msg_lower:
        return ("thread-aws-hackathon", "AWS Hackathon Project", False, False)
    if "tax" in msg_lower or "taxes" in msg_lower:
        return ("thread-tax-filing", "Tax Filing 2025", False, False)

    # 2. Check for explicit unknown intent mentions
    unknown_terms = [
        "mars",
        "trip",
        "flight",
        "car",
        "recipe",
        "cooking",
        "rocket",
        "vacation",
        "grocery",
        "shopping",
        "workout",
        "gym",
        "unknown",
        "passport",
    ]
    for term in unknown_terms:
        if term in msg_lower:
            return (None, None, False, True)

    # 3. Pronoun / relative reference continuity ("it", "that", "this", "the blocker", "leave off", "where was i")
    has_pronoun = bool(
        re.search(
            r"\b(it|that|this|the thread|the application|the intention|leave off|where was i|where were we|where did i|blocker)\b",
            msg_lower,
        )
        or "why" in msg_lower
        or "finish" in msg_lower
        or "close" in msg_lower
        or "verify" in msg_lower
    )

    if has_pronoun:
        # Check active or pending thread in session
        active_id = session.pending_thread_id or session.active_thread_id
        if active_id:
            title_map = {
                "thread-university-application": "University Application",
                "thread-client-report": "Client Q3 Report",
                "thread-dentist-appointment": "Dentist Appointment",
                "thread-aws-hackathon": "AWS Hackathon Project",
                "thread-tax-filing": "Tax Filing 2025",
            }
            title = title_map.get(active_id)
            if not title:
                for t in available_threads:
                    if t.get("id") == active_id:
                        title = t.get("title", active_id)
                        break
            return (active_id, title or active_id, False, False)

        # No active thread set in session: check available threads
        if len(available_threads) > 1:
            return (None, None, True, False)
        elif len(available_threads) == 1:
            return (
                available_threads[0]["id"],
                available_threads[0].get("title"),
                False,
                False,
            )
        else:
            return (None, None, False, True)

    # 4. Fallback to active thread if present
    if session.active_thread_id:
        return (session.active_thread_id, "University Application", False, False)

    return (None, None, False, False)


class MockModelProvider(ModelProvider):
    """
    Deterministic Mock Provider that uses the MCP client to satisfy
    Threadback workflows for tests, CI, and local Alexa+ demos.
    """

    async def process_message(
        self,
        user_message: str,
        session: ConversationSession,
        mcp_client: ThreadbackMCPClient,
    ) -> AgentChatResponse:
        activities: list[ToolActivity] = []
        msg_lower = user_message.strip().lower()

        # -------------------------------------------------------------------
        # 1. Check for Pending Confirmation Flow (Safety Gate)
        # -------------------------------------------------------------------
        if session.pending_confirmation and session.pending_proposal_id:
            proposal_id = session.pending_proposal_id

            # Explicit affirmative confirmation
            if is_explicit_confirmation(user_message):
                _log_agent_observability(
                    session.conversation_id,
                    decision="execute_confirmed_action",
                    tool="execute_action",
                    next_decision="report_simulated_execution",
                )
                activities.append(
                    ToolActivity(
                        tool_name="execute_action",
                        summary=f"Executing simulation for proposal {proposal_id}...",
                    )
                )

                exec_result = await mcp_client.execute_action(
                    proposal_id=proposal_id,
                    confirmed=True,
                    execution_mode="SIMULATED",
                )

                exec_status = exec_result.get("execution_status", "EXECUTED")
                exec_mode = exec_result.get("execution_mode", "SIMULATED")
                event_id = exec_result.get("event_id", "evt-simulated")
                result_msg = exec_result.get(
                    "message", "Action simulated successfully."
                )

                _log_agent_observability(
                    session.conversation_id,
                    decision="execute_action_completed",
                    tool="execute_action",
                    result_status=exec_status,
                )

                session.clear_pending()

                if exec_status == "ALREADY_EXECUTED":
                    explanation = (
                        "This action proposal has already been executed in simulation mode. "
                        "No duplicate action was performed."
                    )
                else:
                    explanation = (
                        f"I executed the follow-up action in SIMULATION mode.\n\n"
                        f"• Status: {exec_status}\n"
                        f"• Execution Mode: {exec_mode} (No real external messages, emails, or calls were made)\n"
                        f"• Proposal ID: {proposal_id}\n"
                        f"• Audit Event ID: {event_id}\n"
                        f"• Details: {result_msg}\n\n"
                        f"Your thread state and audit log have been updated with this simulated event."
                    )

                return AgentChatResponse(
                    message=explanation,
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                    execution_status=exec_status,
                    execution_mode=exec_mode,
                )

            # Ambiguous or inquisitive responses: NEVER EXECUTE
            if is_ambiguous_confirmation(user_message):
                _log_agent_observability(
                    session.conversation_id,
                    decision="reject_ambiguous_confirmation",
                    next_decision="request_explicit_authorization",
                )
                return AgentChatResponse(
                    message=(
                        f"Action execution requires explicit authorization before proceeding.\n\n"
                        f"I have a prepared action proposal ({proposal_id}) on standby. "
                        f"Please note that execution will be strictly SIMULATED — no actual email or external communication will be sent.\n\n"
                        f"Would you like me to proceed with the simulation? Please answer 'Yes' or 'Go ahead' to authorize."
                    ),
                    conversation_id=session.conversation_id,
                    pending_confirmation=True,
                    proposal_id=proposal_id,
                    thread_id=session.pending_thread_id,
                    activities=activities,
                )

            # Cancellation or rejection
            if "no" in msg_lower or "cancel" in msg_lower or "stop" in msg_lower:
                _log_agent_observability(
                    session.conversation_id,
                    decision="cancel_pending_proposal",
                )
                session.clear_pending()
                return AgentChatResponse(
                    message=f"Understood. I have cancelled the pending execution for proposal {proposal_id}.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

        # Explicit confirmation when NO pending proposal exists
        if is_explicit_confirmation(user_message) and not session.pending_confirmation:
            _log_agent_observability(
                session.conversation_id,
                decision="unsolicited_confirmation",
            )
            return AgentChatResponse(
                message="There is no action proposal currently awaiting confirmation. What intention or thread would you like me to help you with?",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 1. Conversational Greeting Flow ("hello", "hi", "hey", etc.)
        # -------------------------------------------------------------------
        clean_msg = re.sub(r"[^\w\s]", "", msg_lower).strip()
        is_greeting = clean_msg in {
            "hello",
            "hi",
            "hey",
            "greetings",
            "good morning",
            "good afternoon",
            "good evening",
            "hello there",
            "hi there",
        } or any(clean_msg.startswith(g + " ") for g in ["hello", "hi", "hey"])
        has_task_intent = any(
            k in msg_lower
            for k in [
                "forget",
                "what",
                "where",
                "why",
                "how",
                "finish",
                "close",
                "status",
                "thread",
                "application",
                "action",
                "do",
                "help",
            ]
        )
        if is_greeting and not has_task_intent:
            _log_agent_observability(
                session.conversation_id,
                decision="conversational_greeting",
            )
            return AgentChatResponse(
                message=(
                    "Hello! I am Threadback, your personal context and intention recovery agent. "
                    "I help you recover open commitments, identify blockers, and safely resolve unfinished intentions. "
                    "You can ask me what you might be forgetting, where you left off, or how to move a commitment forward."
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # Fetch current available threads for disambiguation & context
        # -------------------------------------------------------------------
        disc_res = await mcp_client.discover_unfinished_threads()
        available_threads = disc_res.get("threads", [])

        # -------------------------------------------------------------------
        # 2. Lifecycle Closure Flow (Phase 9 / M10 / M11): "Close it" / "Close the thread"
        # -------------------------------------------------------------------
        is_closure_query = (
            (
                "close" in msg_lower
                and (
                    "thread" in msg_lower
                    or "it" in msg_lower
                    or "application" in msg_lower
                    or "report" in msg_lower
                )
            )
            or "close the thread" in msg_lower
            or "close thread" in msg_lower
            or "close it" in msg_lower
            or "mark it as finished" in msg_lower
            or "mark as finished" in msg_lower
            or "mark as complete" in msg_lower
            or "mark it complete" in msg_lower
        )
        if is_closure_query:
            target_id, title, is_ambiguous, is_unknown = _resolve_target_thread(
                msg_lower, session, available_threads
            )
            if is_unknown:
                return AgentChatResponse(
                    message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            if is_ambiguous or not target_id:
                return AgentChatResponse(
                    message="I found multiple unfinished intentions. Which thread would you like to close?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            # Invariant: verify_thread_completion MUST be called before close_thread
            _log_agent_observability(
                session.conversation_id,
                decision="verify_before_closure",
                tool="verify_thread_completion",
            )
            activities.append(
                ToolActivity(
                    tool_name="verify_thread_completion",
                    summary=f"Verifying completion criteria before closing thread '{target_id}'...",
                )
            )
            ver_res = await mcp_client.verify_thread_completion(target_id)
            verified = ver_res.get("verified", False)
            reason = ver_res.get("reason", "")

            _log_agent_observability(
                session.conversation_id,
                decision="closure_verification_result",
                tool="verify_thread_completion",
                result_status="VERIFIED" if verified else "NOT_VERIFIED",
            )

            if not verified:
                return AgentChatResponse(
                    message=(
                        f"I cannot close the thread because completion has not been verified.\n\n"
                        f"• Reason: {reason}\n\n"
                        f"Threadback safety invariants require that a thread cannot be closed without verified evidence."
                    ),
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                    thread_id=target_id,
                )

            # Verification succeeded: call close_thread
            _log_agent_observability(
                session.conversation_id,
                decision="execute_closure",
                tool="close_thread",
            )
            activities.append(
                ToolActivity(
                    tool_name="close_thread",
                    summary=f"Closing thread '{target_id}' after successful verification...",
                )
            )
            close_res = await mcp_client.close_thread(target_id)
            closure_status = close_res.get("closure_status", "COMPLETED")
            event_id = close_res.get("event_id", "evt-closed")

            thread_title = title or (
                "University Application" if "university" in target_id else target_id
            )
            msg = (
                f"Your {thread_title.lower()} thread is complete. "
                f"The recommendation-letter blocker was resolved and completion was verified.\n\n"
                f"• Status: {closure_status}\n"
                f"• Audit Event: {event_id}\n\n"
                f"The lifecycle loop for this intention is now successfully closed."
            )

            session.active_thread_id = target_id
            return AgentChatResponse(
                message=msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
                thread_id=target_id,
            )

        # -------------------------------------------------------------------
        # 3. Blocker Investigation (Phase 3): "Why haven't I finished it?" / "Why is this still unfinished?" / "What is blocking me?"
        # -------------------------------------------------------------------
        is_blocker_query = (
            "why haven't i finished" in msg_lower
            or "why is this still unfinished" in msg_lower
            or "why is it still unfinished" in msg_lower
            or "why is it unfinished" in msg_lower
            or "why haven't i" in msg_lower
            or "why is it blocked" in msg_lower
            or "why haven't you finished" in msg_lower
            or "what is blocking me" in msg_lower
            or "what is blocking" in msg_lower
            or "what's blocking" in msg_lower
            or "blocker" in msg_lower
            or "blockers" in msg_lower
            or (
                bool(re.search(r"\bwhy\b", msg_lower))
                and bool(
                    re.search(r"\b(unfinished|finished|blocked|pending)\b", msg_lower)
                )
            )
        )
        if is_blocker_query:
            target_id, title, is_ambiguous, is_unknown = _resolve_target_thread(
                msg_lower, session, available_threads
            )
            if is_unknown:
                return AgentChatResponse(
                    message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            # If user asks generally "What is blocking me?" with no active thread
            if not target_id and (
                "what is blocking" in msg_lower
                or "what's blocking" in msg_lower
                or "blockers" in msg_lower
            ):
                blocked_reports: list[str] = []
                for t in available_threads:
                    activities.append(
                        ToolActivity(
                            tool_name="find_thread_blockers",
                            summary=f"Checking blockers for {t['title']}...",
                        )
                    )
                    blocker_res = await mcp_client.find_thread_blockers(t["id"])
                    if blocker_res.get("blocking_status") == "BLOCKED":
                        blist = blocker_res.get("blockers", [])
                        desc = ", ".join(
                            b.get("description", b.get("title", "")) for b in blist
                        )
                        blocked_reports.append(
                            f"• {t['title']} (Priority: {t['priority']}): Blocked by {desc}"
                        )

                if blocked_reports:
                    msg = "Here are your currently blocked threads:\n\n" + "\n".join(
                        blocked_reports
                    )
                else:
                    msg = "None of your active threads are currently blocked."

                return AgentChatResponse(
                    message=msg,
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            if is_ambiguous or not target_id:
                return AgentChatResponse(
                    message="I found multiple unfinished intentions (such as your University Application and Client Report). Which one would you like to check blockers for?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            # Specific thread blocker investigation
            _log_agent_observability(
                session.conversation_id,
                decision="investigate_blocker",
                tool="find_thread_blockers",
            )
            activities.append(
                ToolActivity(
                    tool_name="find_thread_blockers",
                    summary=f"Finding blockers for '{target_id}'...",
                )
            )
            blocker_res = await mcp_client.find_thread_blockers(target_id)
            blist = blocker_res.get("blockers", [])
            session.active_thread_id = target_id

            activities.append(
                ToolActivity(
                    tool_name="analyze_thread",
                    summary=f"Analyzing status for '{target_id}'...",
                )
            )
            await mcp_client.analyze_thread(target_id)

            thread_title = title or (
                "University Application" if "university" in target_id else target_id
            )
            if blist:
                blocker_desc = ", ".join(
                    b.get("description", b.get("title", "unresolved dependency"))
                    for b in blist
                )
                msg = (
                    f"Your {thread_title} is still blocked because {blocker_desc} hasn't been resolved yet.\n\n"
                    f"Would you like me to prepare a recommended next action to move it forward?"
                )
            else:
                msg = (
                    f"Your {thread_title} does not have any active blockers. "
                    f"Would you like me to check what should be done next?"
                )

            return AgentChatResponse(
                message=msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
                thread_id=target_id,
            )

        # -------------------------------------------------------------------
        # 4. Verification Flow (Phase 8 / M10 / M11): "Is it actually finished?" / "Did I finish it?"
        # -------------------------------------------------------------------
        is_verification_query = (
            "is it actually finished" in msg_lower
            or "is it finished" in msg_lower
            or "did i finish" in msg_lower
            or "is the application complete" in msg_lower
            or "is it complete" in msg_lower
            or "verify completion" in msg_lower
            or "verify thread" in msg_lower
            or "actually finished" in msg_lower
            or (
                bool(re.search(r"\b(is|did)\b.*\b(finished|complete)\b", msg_lower))
                and not bool(re.search(r"\bwhy\b", msg_lower))
            )
        )
        if is_verification_query:
            target_id, title, is_ambiguous, is_unknown = _resolve_target_thread(
                msg_lower, session, available_threads
            )
            if is_unknown:
                return AgentChatResponse(
                    message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            if is_ambiguous or not target_id:
                return AgentChatResponse(
                    message="I found multiple unfinished intentions. Which one would you like to verify?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            _log_agent_observability(
                session.conversation_id,
                decision="verify_completion",
                tool="verify_thread_completion",
            )
            activities.append(
                ToolActivity(
                    tool_name="verify_thread_completion",
                    summary=f"Deterministically verifying completion for thread '{target_id}'...",
                )
            )

            ver_res = await mcp_client.verify_thread_completion(target_id)
            verified = ver_res.get("verified", False)
            confidence = ver_res.get("confidence", 0.0)
            reason = ver_res.get("reason", "")
            matched = ver_res.get("matched_evidence", [])
            missing = ver_res.get("missing_evidence", [])

            _log_agent_observability(
                session.conversation_id,
                decision="verification_evaluation",
                tool="verify_thread_completion",
                result_status="VERIFIED" if verified else "NOT_VERIFIED",
            )

            session.active_thread_id = target_id

            if verified:
                matched_str = (
                    ", ".join(matched) if matched else "All required evidence present"
                )
                msg = (
                    f"The available evidence indicates that your thread is complete.\n\n"
                    f"• Verification Status: VERIFIED\n"
                    f"• Confidence: {confidence * 100:.0f}%\n"
                    f"• Reason: {reason}\n"
                    f"• Matched Evidence: {matched_str}\n\n"
                    f"Would you like me to close this thread?"
                )
            else:
                missing_str = (
                    ", ".join(missing) if missing else "Unresolved blocker or evidence"
                )
                msg = (
                    f"Not yet. {reason}\n\n"
                    f"• Verification Status: NOT VERIFIED\n"
                    f"• Confidence: {confidence * 100:.0f}%\n"
                    f"• Missing Evidence / Blocker: {missing_str}\n\n"
                    f"The thread remains open and cannot be closed until all blocking conditions are satisfied."
                )

            return AgentChatResponse(
                message=msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
                thread_id=target_id,
            )

        # -------------------------------------------------------------------
        # 5. Action Preparation (Phase 5): "Help me finish it" / "prepare action"
        # -------------------------------------------------------------------
        is_prep_query = (
            "help me finish" in msg_lower
            or "finish the application" in msg_lower
            or "prepare action" in msg_lower
            or "take action" in msg_lower
            or "proceed with application" in msg_lower
            or "help me finish it" in msg_lower
        )
        if is_prep_query:
            target_id: str | None = None
            search_term: str | None = None

            # Check if specific topic is mentioned in query
            if "application" in msg_lower or "university" in msg_lower:
                search_term = "application"
            elif "client" in msg_lower or "report" in msg_lower:
                search_term = "client"
            elif "dentist" in msg_lower:
                search_term = "dentist"
            elif "hackathon" in msg_lower:
                search_term = "hackathon"
            else:
                match = re.search(
                    r"finish\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\-]+)", msg_lower
                )
                if match:
                    extracted = match.group(1).strip()
                    if extracted not in ("it", "this", "that", "the", "action"):
                        search_term = extracted

            # Fast path: if session already knows thread and user didn't specify a new specific topic
            if not search_term and (
                session.pending_thread_id or session.active_thread_id
            ):
                target_id = session.pending_thread_id or session.active_thread_id
            else:
                activities.append(
                    ToolActivity(
                        tool_name="discover_unfinished_threads",
                        summary=(
                            f"Checking unfinished threads for '{search_term}'..."
                            if search_term
                            else "Discovering unfinished threads..."
                        ),
                    )
                )
                disc_res = await mcp_client.discover_unfinished_threads(
                    query=search_term
                )
                threads = disc_res.get("threads", [])
                if not threads and search_term in (None, "project", "task", "thread"):
                    disc_res = await mcp_client.discover_unfinished_threads()
                    threads = disc_res.get("threads", [])

                if not threads:
                    return AgentChatResponse(
                        message="I could not find an unfinished thread matching your request. Can you give me a little more context?",
                        conversation_id=session.conversation_id,
                        pending_confirmation=False,
                        activities=activities,
                    )
                target_id = threads[0]["id"]

            _log_agent_observability(
                session.conversation_id,
                decision="suggest_and_prepare_action",
                tool="suggest_next_action",
                next_decision="prepare_action",
            )
            activities.append(
                ToolActivity(
                    tool_name="suggest_next_action",
                    summary=f"Evaluating recommended next action for '{target_id}'...",
                )
            )
            sugg_res = await mcp_client.suggest_next_action(target_id)
            suggestion = sugg_res.get("suggestion", {})

            activities.append(
                ToolActivity(
                    tool_name="prepare_action",
                    summary="Preparing structured action proposal...",
                )
            )
            prep_res = await mcp_client.prepare_action(target_id)
            proposal = prep_res.get("proposal", {})
            proposal_id = proposal.get("id")
            if not proposal_id:
                return AgentChatResponse(
                    message=f"No action could be prepared for thread '{target_id}'.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            req_confirm = proposal.get("requires_confirmation", True)
            session.set_pending_proposal(proposal_id, target_id)
            session.active_thread_id = target_id

            _log_agent_observability(
                session.conversation_id,
                decision="proposal_prepared_awaiting_confirmation",
                tool="prepare_action",
                result_status=proposal_id,
                next_decision="request_explicit_confirmation",
            )

            action_type = proposal.get(
                "action_type", suggestion.get("action_type", "UNBLOCKER_ACTION")
            )
            description = proposal.get(
                "description",
                suggestion.get("reason", "Follow up with recommendation letter"),
            )
            risk_level = proposal.get("risk_level", "MEDIUM")
            thread_title = (
                "University Application"
                if "university" in target_id
                else (
                    "Client Q3 Report"
                    if "client" in target_id
                    else (
                        "Delta Quantum Synthesis"
                        if "delta" in target_id or "synthetic" in target_id
                        else target_id
                    )
                )
            )
            for t in available_threads:
                if t.get("id") == target_id:
                    thread_title = t.get("title", thread_title)
                    break

            response_msg = (
                f"I reviewed your {thread_title} thread and prepared a recommended next action:\n\n"
                f"• Proposal ID: {proposal_id}\n"
                f"• Type: {action_type}\n"
                f"• Description: {description}\n"
                f"• Risk Level: {risk_level}\n"
                f"• Confirmation Required: Yes\n\n"
                f"⚠️ Safety Notice: Execution in Threadback is strictly SIMULATED. No actual email or external communication will be sent.\n\n"
                f"Would you like me to execute this simulated action? (Reply 'Yes' or 'Go ahead' to confirm)"
            )

            return AgentChatResponse(
                message=response_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=req_confirm,
                proposal_id=proposal_id,
                thread_id=target_id,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 6. Next Action Flow (Phase 4): "What should I do next?" / "What should I do?"
        # -------------------------------------------------------------------
        is_next_action_query = (
            "what should i do next" in msg_lower
            or "what should i do" in msg_lower
            or "what to do next" in msg_lower
            or "next step" in msg_lower
            or "next action" in msg_lower
        )
        if is_next_action_query:
            target_id, title, is_ambiguous, is_unknown = _resolve_target_thread(
                msg_lower, session, available_threads
            )
            if not target_id:
                # If no specific active thread, pick highest priority unfinished thread
                disc_prio = await mcp_client.discover_unfinished_threads(
                    min_priority="HIGH"
                )
                prio_threads = disc_prio.get("threads", [])
                if prio_threads:
                    target_id = prio_threads[0]["id"]
                    title = prio_threads[0].get("title", target_id)
                elif available_threads:
                    target_id = available_threads[0]["id"]
                    title = available_threads[0].get("title", target_id)

            if target_id:
                _log_agent_observability(
                    session.conversation_id,
                    decision="suggest_next_action",
                    tool="suggest_next_action",
                )
                activities.append(
                    ToolActivity(
                        tool_name="suggest_next_action",
                        summary=f"Determining next action for {title or target_id}...",
                    )
                )
                sugg_res = await mcp_client.suggest_next_action(target_id)
                suggestion = sugg_res.get("suggestion", {})
                action_type = suggestion.get("action_type", "NEXT_ACTION")
                reason = suggestion.get(
                    "reason", "Continue progress on open commitment"
                )

                session.active_thread_id = target_id

                msg = (
                    f"Based on your intention {title or target_id}, here is your recommended next action:\n\n"
                    f"• Recommended Action: {action_type}\n"
                    f"• Reason: {reason}\n"
                    f"• Requires Confirmation: {'Yes' if suggestion.get('requires_confirmation') else 'No'}\n\n"
                    f"Would you like me to prepare this action?"
                )
                return AgentChatResponse(
                    message=msg,
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    thread_id=target_id,
                    activities=activities,
                )

        # -------------------------------------------------------------------
        # 7. Context Reconstruction (Phase 2): "Where did I leave off..."
        # -------------------------------------------------------------------
        is_context_query = (
            "where did i leave off" in msg_lower
            or "where was i" in msg_lower
            or "where were we" in msg_lower
            or "leave off" in msg_lower
            or "where did we leave off" in msg_lower
            or "status of my application" in msg_lower
            or "status of the application" in msg_lower
            or "what's the status" in msg_lower
        )
        if is_context_query:
            target_id, title, is_ambiguous, is_unknown = _resolve_target_thread(
                msg_lower, session, available_threads
            )
            if is_unknown:
                return AgentChatResponse(
                    message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            if is_ambiguous and not target_id:
                return AgentChatResponse(
                    message="I found multiple unfinished intentions. Are you asking about your University Application, Client Report, or Dentist Appointment?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            # Step 1: Discover / identify target thread
            activities.append(
                ToolActivity(
                    tool_name="discover_unfinished_threads",
                    summary="Searching for unfinished thread...",
                )
            )
            disc_search = "application" if "application" in msg_lower else None
            disc_res = await mcp_client.discover_unfinished_threads(query=disc_search)

            if not target_id:
                disc_threads = disc_res.get("threads", [])
                if disc_threads:
                    target_id = disc_threads[0]["id"]
                    title = disc_threads[0].get("title", target_id)
                elif available_threads:
                    target_id = available_threads[0]["id"]
                    title = available_threads[0].get("title", "University Application")
                else:
                    target_id = "thread-university-application"
                    title = "University Application"

            _log_agent_observability(
                session.conversation_id,
                decision="reconstruct_context",
                tool="get_thread_context",
                next_decision="analyze_thread",
            )
            activities.append(
                ToolActivity(
                    tool_name="get_thread_context",
                    summary=f"Retrieving context for thread '{target_id}'...",
                )
            )
            ctx = await mcp_client.get_thread_context(target_id)

            activities.append(
                ToolActivity(
                    tool_name="analyze_thread",
                    summary=f"Analyzing attention and confidence for '{target_id}'...",
                )
            )
            analysis_res = await mcp_client.analyze_thread(target_id)
            analysis = analysis_res.get("analysis", {})

            thread_title = title or ctx.get("title", target_id)
            status = ctx.get("status", analysis.get("current_status", "BLOCKED"))
            commitments = ctx.get("commitments", [])
            com_text = (
                ", ".join(
                    f"{c.get('description', c.get('title', c.get('id')))} (due: {c.get('due_at', c.get('due_date', 'N/A'))})"
                    for c in commitments
                )
                or "None"
            )

            dependencies = ctx.get("dependencies", [])
            blockers = [d for d in dependencies if d.get("blocking")]
            blocker_text = (
                ", ".join(
                    f"{b.get('description', b.get('title', b.get('id')))}"
                    for b in blockers
                )
                if blockers
                else "No active blockers."
            )

            evidence = ctx.get("evidence", [])
            ev_text = (
                "; ".join(
                    f"{e.get('type')}: {e.get('description')}" for e in evidence[:2]
                )
                if evidence
                else "None recorded."
            )

            attention_level = analysis.get("attention", {}).get("level", "HIGH")
            confidence = analysis.get("confidence", 0.85)

            if blockers:
                blocker_summary = (
                    f"The thread is currently blocked waiting on: {blocker_text}."
                )
            else:
                blocker_summary = (
                    "There are currently no active blockers on this thread."
                )

            response_msg = (
                f"Here is where you left off with {thread_title}:\n\n"
                f"• Current Status: {status} (Attention: {attention_level}, Confidence: {confidence * 100:.0f}%)\n"
                f"• Commitments: {com_text}\n"
                f"• Blockers: {blocker_text}\n"
                f"• Recent Evidence: {ev_text}\n\n"
                f"{blocker_summary} Would you like me to prepare a recommended next action?"
            )

            session.active_thread_id = target_id
            session.pending_thread_id = target_id

            return AgentChatResponse(
                message=response_msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
                thread_id=target_id,
            )

        # -------------------------------------------------------------------
        # 8. Unknown Thread Direct Check
        # -------------------------------------------------------------------
        _, _, _, is_unknown = _resolve_target_thread(
            msg_lower, session, available_threads
        )
        if is_unknown:
            return AgentChatResponse(
                message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 9. General Discovery Flow (Phase 1 / Demo A): "What am I forgetting?"
        # -------------------------------------------------------------------
        _log_agent_observability(
            session.conversation_id,
            decision="discover_unfinished_threads",
            tool="discover_unfinished_threads",
        )
        activities.append(
            ToolActivity(
                tool_name="discover_unfinished_threads",
                summary="Discovering unfinished intent threads...",
            )
        )

        if not available_threads:
            return AgentChatResponse(
                message="You have no unfinished intentions or open threads at the moment. All caught up!",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        thread_summaries: list[str] = []
        for t in available_threads[:4]:
            activities.append(
                ToolActivity(
                    tool_name="analyze_thread",
                    summary=f"Analyzing thread '{t['title']}'...",
                )
            )
            analysis_res = await mcp_client.analyze_thread(t["id"])
            analysis = analysis_res.get("analysis", {})
            att = analysis.get("attention", {}).get("level", "NORMAL")
            reasons = ", ".join(
                r.replace("_", " ").title()
                for r in analysis.get("unfinished_reasons", [])
            )
            thread_summaries.append(
                f"• {t['title']} (Priority: {t['priority']}, Attention: {att})\n"
                f"  Status: {t['status']} — Needs attention because: {reasons or 'Pending completion'}"
            )

        # Set the top/first thread as active context for conversational continuity
        if available_threads:
            session.active_thread_id = available_threads[0]["id"]

        summary_msg = (
            "Here are the unfinished intentions you might be forgetting:\n\n"
            + "\n\n".join(thread_summaries)
            + "\n\nWhich of these would you like to review or move forward?"
        )

        return AgentChatResponse(
            message=summary_msg,
            conversation_id=session.conversation_id,
            pending_confirmation=False,
            activities=activities,
            thread_id=session.active_thread_id,
        )
