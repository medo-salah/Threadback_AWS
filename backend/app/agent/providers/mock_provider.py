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

from app.agent.intent_classifier import (
    IntentType,
    classify_intent,
)
from app.agent.mcp_connector import ThreadbackMCPClient
from app.agent.providers.base import ModelProvider
from app.agent.state import (
    ConversationSession,
    is_explicit_confirmation,
)
from app.domain.agent_models import AgentChatResponse, ToolActivity
from app.domain.enums import ResumeEligibility, ThreadStatus
from app.mcp.server import (
    attention_engine,
    intent_copilot_service,
    next_action_service,
    resume_service,
    safe_closure_assistant,
    thread_service,
    time_budget_service,
    what_if_service,
    why_now_service,
)

logger = logging.getLogger(__name__)


TITLE_MAP = {
    "thread-university-application": "University Application",
    "thread-client-report": "Client Q3 Report",
    "thread-dentist-appointment": "Dentist Appointment",
    "thread-aws-hackathon": "AWS Hackathon Project",
    "thread-tax-filing": "Tax Filing 2025",
    "thread-professional-certification": "Professional Certification",
    "thread-portfolio-review": "Portfolio Review",
    "thread-client-pitch": "Executive Client Pitch",
    "thread-board-presentation": "Board Presentation",
}


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
    extracted_topic: str | None = None,
    is_unknown: bool = False,
    has_pronoun: bool = False,
) -> tuple[str | None, str | None, bool, bool]:
    """
    Deterministically resolves the target thread from user message, extracted topic, and session continuity.

    Returns:
        (thread_id, title, is_ambiguous, is_unknown)
    """
    if is_unknown:
        return (None, None, False, True)

    # 1. Direct topic match by extracted topic or known keywords
    target_id = extracted_topic
    if not target_id:
        if (
            "application" in msg_lower
            or "university" in msg_lower
            or "grad" in msg_lower
        ):
            target_id = "thread-university-application"
        elif "client" in msg_lower or "report" in msg_lower:
            target_id = "thread-client-report"
        elif "dentist" in msg_lower or "dental" in msg_lower or "teeth" in msg_lower:
            target_id = "thread-dentist-appointment"
        elif "hackathon" in msg_lower or "aws" in msg_lower:
            target_id = "thread-aws-hackathon"
        elif "tax" in msg_lower or "taxes" in msg_lower:
            target_id = "thread-tax-filing"

    if target_id:
        title = TITLE_MAP.get(target_id)
        if not title:
            for t in available_threads:
                if t.get("id") == target_id:
                    title = t.get("title", target_id)
                    break
        return (target_id, title or target_id, False, False)

    # 2. Check for explicit unknown intent mentions if not already flagged
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
        "passport",
    ]
    for term in unknown_terms:
        if re.search(rf"\b{re.escape(term)}\b", msg_lower):
            return (None, None, False, True)

    # 3. Pronoun / relative reference continuity ("it", "that", "this", "the blocker", "leave off", "where was i", etc.)
    has_pronoun_flag = has_pronoun or bool(
        re.search(
            r"\b(it|that|this|the thread|the application|the intention|leave off|where was i|where were we|where did i|blocker)\b",
            msg_lower,
        )
        or any(
            k in msg_lower
            for k in [
                "why",
                "finish",
                "close",
                "verify",
                "done",
                "step",
                "action",
            ]
        )
    )

    if has_pronoun_flag:
        active_id = session.pending_thread_id or session.active_thread_id
        if active_id:
            title = TITLE_MAP.get(active_id)
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
        active_id = session.active_thread_id
        title = TITLE_MAP.get(active_id)
        if not title:
            for t in available_threads:
                if t.get("id") == active_id:
                    title = t.get("title", active_id)
                    break
        return (active_id, title or active_id, False, False)

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
        # 1. Systematic Intent Classification
        # -------------------------------------------------------------------
        has_pending = bool(session.pending_confirmation and session.pending_proposal_id)
        classified = classify_intent(user_message, has_pending_confirmation=has_pending)

        # -------------------------------------------------------------------
        # 2. Check for Pending Confirmation Flow (Safety Gate)
        # -------------------------------------------------------------------
        if has_pending:
            proposal_id = session.pending_proposal_id
            assert proposal_id is not None

            # Explicit affirmative confirmation
            if classified.intent == IntentType.EXPLICIT_CONFIRMATION:
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

                session.last_executed_proposal_id = proposal_id
                session.last_executed_mode = exec_mode
                session.clear_pending()

                if exec_mode == "PERSISTENT_MUTATION":
                    if exec_status == "ALREADY_EXECUTED":
                        explanation = (
                            f"This state mutation proposal ({proposal_id}) has already been applied. "
                            "Persistent Threadback state was preserved without duplicate mutation."
                        )
                    else:
                        explanation = (
                            f"I have applied this persistent Threadback state mutation.\n\n"
                            f"• Status: {exec_status}\n"
                            f"• Execution Mode: {exec_mode} (Durable internal Threadback state mutated)\n"
                            f"• Proposal ID: {proposal_id}\n"
                            f"• Audit Event ID: {event_id}\n"
                            f"• Details: {result_msg}\n\n"
                            f"Your thread state, database record, and lifecycle event ledger have been permanently updated."
                        )
                else:
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
            if classified.intent == IntentType.AMBIGUOUS_CONFIRMATION:
                _log_agent_observability(
                    session.conversation_id,
                    decision="reject_ambiguous_confirmation",
                    next_decision="request_explicit_authorization",
                )
                if session.pending_action_type in (
                    "EVOLVE_INTENTION",
                    "DEFER_INTENTION",
                    "RESUME_INTENTION",
                    "ABANDON_INTENTION",
                ):
                    mode_notice = "Please note that this will apply a durable internal state mutation to Threadback's records."
                    prompt_notice = "Would you like me to proceed with this state mutation? Please answer 'Yes' or 'Go ahead' to authorize."
                else:
                    mode_notice = "Please note that execution will be strictly SIMULATED — no actual email or external communication will be sent."
                    prompt_notice = "Would you like me to proceed with the simulation? Please answer 'Yes' or 'Go ahead' to authorize."

                return AgentChatResponse(
                    message=(
                        f"Action execution requires explicit authorization before proceeding.\n\n"
                        f"I have a prepared action proposal ({proposal_id}) on standby. "
                        f"{mode_notice}\n\n"
                        f"{prompt_notice}"
                    ),
                    conversation_id=session.conversation_id,
                    pending_confirmation=True,
                    proposal_id=proposal_id,
                    thread_id=session.pending_thread_id,
                    activities=activities,
                )

            # Cancellation or rejection
            if classified.intent == IntentType.CANCELLATION:
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
        if not has_pending and (
            classified.intent == IntentType.EXPLICIT_CONFIRMATION
            or is_explicit_confirmation(user_message)
        ):
            _log_agent_observability(
                session.conversation_id,
                decision="unsolicited_confirmation",
            )
            if session.last_executed_proposal_id:
                if session.last_executed_mode == "PERSISTENT_MUTATION":
                    msg = (
                        "There isn't another action waiting for confirmation. "
                        "The previous persistent state mutation has already been executed. "
                        "What intention would you like to work on next?"
                    )
                else:
                    msg = (
                        "There isn't another action waiting for confirmation. "
                        "The previous action has already been executed in simulation mode. "
                        "Would you like me to check whether the intention is actually complete?"
                    )
            else:
                msg = (
                    "There is no action proposal currently awaiting confirmation. "
                    "What intention or thread would you like me to help you with?"
                )

            return AgentChatResponse(
                message=msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 3. Non-Domain / General Conversation (MUST NOT CALL MCP TOOLS)
        # -------------------------------------------------------------------
        if classified.intent == IntentType.GREETING:
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

        if classified.intent == IntentType.THANKS:
            _log_agent_observability(
                session.conversation_id,
                decision="conversational_thanks",
            )
            return AgentChatResponse(
                message=(
                    "You're welcome! Let me know if you want to check on any other open commitments or need help moving a thread forward."
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        if classified.intent == IntentType.CAPABILITIES:
            _log_agent_observability(
                session.conversation_id,
                decision="conversational_capabilities",
            )
            return AgentChatResponse(
                message=(
                    "I am Threadback, an intelligent intent-recovery agent designed to help you stay on top of open commitments and unfinished intentions.\n\n"
                    "Here is what I can help you with:\n"
                    "• **Discover**: Ask 'What am I forgetting?' to review open commitments across your threads.\n"
                    "• **Reconstruct Context**: Ask 'Where did I leave off?' or 'What happened with my application?' to see recent status and history.\n"
                    "• **Investigate Blockers**: Ask 'Why isn't it finished?' or 'What's blocking me?' to inspect unresolved dependencies.\n"
                    "• **Recommend Next Steps**: Ask 'What should I do next?' to get deterministic recommended actions.\n"
                    "• **Prepare Actions**: Ask 'Help me finish it' to prepare structured, reviewable action proposals.\n"
                    "• **Verify Completion**: Ask 'Is it actually finished?' to check evidence before closing.\n"
                    "• **Close Verified Threads**: Ask 'Close it' once completion criteria are proven."
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        if classified.intent == IntentType.OUT_OF_SCOPE:
            _log_agent_observability(
                session.conversation_id,
                decision="conversational_out_of_scope",
            )
            return AgentChatResponse(
                message=(
                    "I don't have information about that topic. As Threadback, I focus specifically on helping you recover and manage your unfinished intentions, open commitments, blockers, and next actions. "
                    "Would you like to check what tasks you might be forgetting?"
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        if classified.is_unknown or classified.intent == IntentType.UNKNOWN:
            _log_agent_observability(
                session.conversation_id,
                decision="unknown_intention",
            )
            return AgentChatResponse(
                message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 4. Domain Orchestration: Fetch Current Available Threads
        # -------------------------------------------------------------------
        disc_res = await mcp_client.discover_unfinished_threads()
        available_threads = disc_res.get("threads", [])

        target_id, title, is_ambiguous, is_unknown = _resolve_target_thread(
            msg_lower,
            session,
            available_threads,
            extracted_topic=classified.extracted_topic,
            is_unknown=classified.is_unknown,
            has_pronoun=classified.has_pronoun,
        )

        # Ambiguous resolution check for requests requiring a specific thread
        if (
            is_ambiguous
            and not target_id
            and classified.intent
            in (
                IntentType.CONTEXT_RECONSTRUCTION,
                IntentType.NEXT_ACTION,
                IntentType.PREPARE_ACTION,
                IntentType.BLOCKER_INVESTIGATION,
                IntentType.VERIFICATION,
                IntentType.CLOSURE,
                IntentType.COPILOT_HELP_DEAL,
            )
        ):
            return AgentChatResponse(
                message="You have multiple active intentions. Which one would you like to focus on?",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        if is_unknown and classified.intent not in (
            IntentType.COPILOT_PRIORITIZE,
            IntentType.COPILOT_SAFE_CLOSURE,
            IntentType.COPILOT_TIME_BUDGET,
            IntentType.COPILOT_WHAT_BLOCKING,
            IntentType.COPILOT_OPTIONS,
            IntentType.COPILOT_WHAT_IF,
            IntentType.COPILOT_WHY_IMPORTANT,
            IntentType.COPILOT_RESUME_WHERE_LEFT_OFF,
            IntentType.PROACTIVE_BRIEFING,
            IntentType.PROACTIVE_ATTENTION,
            IntentType.PROACTIVE_CONFLICTS,
            IntentType.PROACTIVE_RESUMABLE,
            IntentType.DISCOVERY,
        ):
            return AgentChatResponse(
                message="I couldn't find an unfinished intention matching that. Can you give me a little more context?",
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 4-m15. M15 Intent Copilot & Proactive Agent Experience Handlers
        # -------------------------------------------------------------------

        # 1. COPILOT_PRIORITIZE: "What should I deal with first?", "What to do first?"
        if classified.intent == IntentType.COPILOT_PRIORITIZE:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_prioritize",
            )
            activities.append(
                ToolActivity(
                    tool_name="prioritize_threads",
                    summary="Evaluating priorities distinguishing Urgency from Attention...",
                )
            )
            all_threads = thread_service.list_threads(unfinished_only=True)
            priorities = intent_copilot_service.prioritize_threads(all_threads)

            if not priorities:
                return AgentChatResponse(
                    message="You have no active unfinished intentions requiring work right now.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            top = priorities[0]
            session.active_thread_id = top.thread_id

            lines = [
                f"You should deal with **{top.thread_title}** first.\n",
                f"• **Urgency**: {top.urgency_score:.2f} (Execution & time pressure)",
                f"• **Attention**: {top.attention_score:.2f} (Cognitive importance & change salience)",
                f"• **Why It Ranks High**: {top.why_it_ranks_high}",
                f"• **Recommended Next Step**: {top.recommended_next_step}\n",
            ]
            if len(priorities) > 1:
                lines.append("Next in line:")
                for p in priorities[1:3]:
                    lines.append(
                        f"  #{p.rank} {p.thread_title} (Urgency: {p.urgency_score:.2f}, Attention: {p.attention_score:.2f})"
                    )

            lines.append(
                "\nWould you like me to help you deal with this, or simulate what happens if you postpone it?"
            )
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 2. COPILOT_WHY_IMPORTANT: "Why is this important?", contextual "Why?"
        if classified.intent == IntentType.COPILOT_WHY_IMPORTANT:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_why_important",
            )
            target_id = session.active_thread_id
            if not target_id:
                all_threads = thread_service.list_threads(unfinished_only=True)
                priorities = intent_copilot_service.prioritize_threads(all_threads)
                if priorities:
                    target_id = priorities[0].thread_id

            if not target_id:
                return AgentChatResponse(
                    message="Which intention would you like me to explain?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            target_thread = thread_service.get_thread(target_id)
            if target_thread is None:
                return AgentChatResponse(
                    message=f"I couldn't find thread '{target_id}' to explain.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            session.active_thread_id = target_thread.id
            explanation = why_now_service.explain(target_thread)
            lines = [f"**{target_thread.title}** is important right now because:"]
            if explanation.has_reason:
                lines.append(f"{explanation.concise_alexa_text}\n")
                lines.append("Key contributing signals:")
                for f in explanation.contributing_factors:
                    lines.append(f"• {f}")
            else:
                lines.append(
                    "All signals are currently stable with no overdue commitments or active blockers."
                )
            lines.append(
                "\nWould you like me to prepare the next action or simulate what happens if you postpone it?"
            )
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 3. COPILOT_WHAT_IF: "What if I postpone this?", "What happens if I ignore this?"
        if classified.intent == IntentType.COPILOT_WHAT_IF:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_what_if_simulation",
            )
            activities.append(
                ToolActivity(
                    tool_name="simulate_what_if",
                    summary="Running read-only counterfactual simulation...",
                )
            )
            target_id = session.active_thread_id
            if not target_id and available_threads:
                target_id = available_threads[0].get("id")

            if not target_id:
                all_threads = thread_service.list_threads(unfinished_only=True)
                if all_threads:
                    target_id = all_threads[0].id

            if not target_id:
                return AgentChatResponse(
                    message="Which intention would you like to run a what-if simulation for?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            target_thread = thread_service.get_thread(target_id)
            session.active_thread_id = target_thread.id

            scenario_name = classified.parameters.get("scenario", "POSTPONE")
            sim_params = {
                k: v for k, v in classified.parameters.items() if k != "scenario"
            }
            all_th = thread_service.list_threads(unfinished_only=False)
            sim_res = what_if_service.simulate(
                thread=target_thread,
                scenario=scenario_name,
                parameters=sim_params,
                all_threads=all_th,
            )

            lines = [
                "**[SIMULATION — NO STATE CHANGED]**\n",
                f"Simulating **{scenario_name}** on **{target_thread.title}**:",
                f"• **Urgency**: {sim_res.original_urgency:.2f} → {sim_res.simulated_urgency:.2f} ({sim_res.simulated_urgency - sim_res.original_urgency:+.2f})",
                f"• **Attention**: {sim_res.original_attention:.2f} → {sim_res.simulated_attention:.2f} ({sim_res.simulated_attention - sim_res.original_attention:+.2f})",
                f"• **Decay State**: {sim_res.original_decay_state} → {sim_res.simulated_decay_state}",
                f"• **Deadline Impact**: {sim_res.deadline_impact_description}",
                f"• **Blocker Impact**: {sim_res.blocker_impact_description}",
            ]
            if sim_res.affected_related_thread_ids:
                lines.append(
                    f"• **Affected Threads**: {', '.join(sim_res.affected_related_thread_ids)}"
                )
            lines.append(
                "\n*Note: This was a read-only scenario evaluation. Your persistent Threadback state was not mutated.*"
            )

            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 4. COPILOT_TIME_BUDGET: "I have 30 minutes", "What can I realistically finish?"
        if classified.intent == IntentType.COPILOT_TIME_BUDGET:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_time_budget",
            )
            activities.append(
                ToolActivity(
                    tool_name="time_budget_recommendation",
                    summary="Matching tasks to available time window...",
                )
            )
            mins = int(classified.parameters.get("available_minutes", "30"))
            all_threads = thread_service.list_threads(unfinished_only=True)
            plan = time_budget_service.recommend(all_threads, available_minutes=mins)

            if plan.selected_thread_id != "none":
                session.active_thread_id = plan.selected_thread_id

            lines = [
                f"With **{mins} minutes** available, here is your recommended task:\n",
                f"• **Target Intention**: {plan.selected_thread_title}",
                f"• **Recommended Action**: {plan.expected_next_action}",
                f"• **Estimated Duration**: ~{plan.estimated_duration_minutes} minutes ({'Fits budget' if plan.fits_budget else 'May require partial session'})",
                f"• **Status**: {'Blocked (unblocking action)' if plan.is_blocked else 'Unblocked (ready for direct progress)'}",
                f"\n**Reason**: {plan.reason}\n",
                "Would you like me to prepare this action proposal for you?",
            ]
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 5. COPILOT_RESUME_WHERE_LEFT_OFF: "Continue where I left off", "Continue my certification"
        if classified.intent == IntentType.COPILOT_RESUME_WHERE_LEFT_OFF:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_resume_where_left_off",
            )
            all_threads = thread_service.list_threads(unfinished_only=False)
            target_th = None
            if target_id:
                target_th = thread_service.get_thread(target_id)
            elif session.active_thread_id:
                target_th = thread_service.get_thread(session.active_thread_id)

            if not target_th:
                for t in all_threads:
                    if t.status == ThreadStatus.DEFERRED:
                        r_eval = resume_service.evaluate_thread(t)
                        if r_eval.eligibility == ResumeEligibility.RESUMABLE:
                            target_th = t
                            break

            if not target_th and all_threads:
                target_th = all_threads[0]

            if not target_th:
                return AgentChatResponse(
                    message="You have no tracked intentions to continue right now.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            session.active_thread_id = target_th.id
            resume_text = intent_copilot_service.format_resume_context(target_th)
            return AgentChatResponse(
                message=resume_text,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 6. COPILOT_SAFE_CLOSURE: "Can I close anything?", "Is anything ready to close?"
        if classified.intent == IntentType.COPILOT_SAFE_CLOSURE:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_safe_closure",
            )
            activities.append(
                ToolActivity(
                    tool_name="evaluate_closure_safety",
                    summary="Auditing completion criteria and blockers...",
                )
            )
            all_threads = thread_service.list_threads(unfinished_only=False)
            candidates = safe_closure_assistant.evaluate_threads(all_threads)

            safe = [c for c in candidates if c.is_safe_to_close]
            unverified = [c for c in candidates if not c.is_safe_to_close]

            lines = []
            if safe:
                lines.append("Yes! The following intention is ready for safe closure:")
                for s in safe:
                    lines.append(
                        f"• **{s.thread_title}**: {s.closure_readiness_reason}"
                    )
                lines.append(
                    f"\nTo close '{safe[0].thread_title}', ask me to 'Verify and close {safe[0].thread_title.lower()}'."
                )
            else:
                lines.append(
                    "None of your active intentions are currently eligible for closure.\n"
                )
                if unverified:
                    lines.append("Current status of active intentions:")
                    for u in unverified[:3]:
                        lines.append(
                            f"• **{u.thread_title}**: {u.closure_readiness_reason}"
                        )

            lines.append(
                "\n*Reminder: Threadback never closes intentions automatically. Closure is strictly verification-gated.*"
            )
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 7. COPILOT_WHAT_BLOCKING: "What is blocking me the most?"
        if classified.intent == IntentType.COPILOT_WHAT_BLOCKING:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_what_blocking",
            )
            all_threads = thread_service.list_threads(unfinished_only=True)
            blocked_threads = [t for t in all_threads if t.active_blockers]

            if not blocked_threads:
                return AgentChatResponse(
                    message="You have no active blockers! All your active intentions can move forward directly.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            lines = ["Here are the critical blockers impacting your intentions:"]
            for bt in blocked_threads:
                b = bt.active_blockers[0]
                lines.append(f"• **{bt.title}** is blocked by: '{b.description}'")

            top_b = blocked_threads[0]
            session.active_thread_id = top_b.id
            lines.append(
                f"\nWould you like me to help resolve the blocker on **{top_b.title}**?"
            )
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 8. COPILOT_HELP_DEAL: "Help me deal with this"
        if classified.intent == IntentType.COPILOT_HELP_DEAL:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_help_deal",
            )
            target_th = None
            if session.active_thread_id:
                target_th = thread_service.get_thread(session.active_thread_id)
            if not target_th:
                all_th = thread_service.list_threads(unfinished_only=True)
                if all_th:
                    target_th = all_th[0]

            if not target_th:
                return AgentChatResponse(
                    message="Which intention would you like help moving forward?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            session.active_thread_id = target_th.id
            sug = next_action_service.suggest_action(target_th)
            lines = [
                f"Let's move **{target_th.title}** forward.",
                f"• Recommended action: {sug.action}",
                f"• Action type: {sug.action_type.value}",
                f"• Rationale: {sug.rationale}",
                "\nWould you like me to prepare this action proposal for your review?",
            ]
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # 9. COPILOT_OPTIONS: "What are my options?"
        if classified.intent == IntentType.COPILOT_OPTIONS:
            _log_agent_observability(
                session.conversation_id,
                decision="copilot_options",
            )
            active_info = (
                f" (Active: **{TITLE_MAP.get(session.active_thread_id, session.active_thread_id)}**)"
                if session.active_thread_id
                else ""
            )
            lines = [
                f"Here are the ways I can help you move your intentions forward{active_info}:",
                "1. **Prioritize**: Ask *'What should I do first?'* to see ranked tasks by Urgency vs Attention.",
                "2. **What-If Simulation**: Ask *'What if I postpone this?'* to simulate consequences without altering state.",
                "3. **Time-Budget Planning**: Ask *'I have 30 minutes'* to get a task that fits your schedule.",
                "4. **Continue**: Ask *'Where did I leave off?'* to pick up context on any intention.",
                "5. **Safe Closure**: Ask *'Can I close anything?'* to audit completion criteria.",
                "6. **Action Preparation**: Ask *'Help me finish this'* to prepare a reviewable action proposal.",
            ]
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 4-m14. M14 Proactive Intent Intelligence Handlers
        # -------------------------------------------------------------------

        # Proactive Briefing
        if classified.intent == IntentType.PROACTIVE_BRIEFING:
            _log_agent_observability(
                session.conversation_id,
                decision="proactive_briefing",
            )
            activities.append(
                ToolActivity(
                    tool_name="generate_briefing",
                    summary="Synthesizing proactive intent briefing...",
                )
            )
            all_threads = thread_service.list_threads(unfinished_only=False)
            briefing = attention_engine.generate_briefing(
                threads=all_threads,
                conversation_id=session.conversation_id,
            )
            if briefing.top_attention:
                session.active_thread_id = briefing.top_attention[0].thread_id

            return AgentChatResponse(
                message=briefing.briefing_text,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # Proactive Attention Candidates
        if classified.intent == IntentType.PROACTIVE_ATTENTION:
            _log_agent_observability(
                session.conversation_id,
                decision="proactive_attention_scan",
            )
            activities.append(
                ToolActivity(
                    tool_name="evaluate_attention",
                    summary="Evaluating attention levels across active intentions...",
                )
            )
            threads = thread_service.list_threads(unfinished_only=True)
            candidates = attention_engine.evaluate_threads(threads)
            if not candidates:
                return AgentChatResponse(
                    message="You have no active intentions requiring attention right now.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            top = candidates[0]
            session.active_thread_id = top.thread_id

            lines = [
                "Here are the intentions requiring attention, ranked by AttentionScore:"
            ]
            lines.append("")
            for c in candidates:
                score_pct = int(c.attention_score * 100)
                lines.append(
                    f"• **{c.thread_title}** [{c.attention_level.value}] — Score: {score_pct}/100\n"
                    f"  Why: {c.human_readable_explanation}"
                )
            lines.append(
                "\nWould you like me to help address your top priority or inspect what changed?"
            )
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # Proactive Why Now
        if classified.intent == IntentType.PROACTIVE_WHY_NOW:
            _log_agent_observability(
                session.conversation_id,
                decision="explain_why_now",
            )
            activities.append(
                ToolActivity(
                    tool_name="explain_why_now",
                    summary="Evaluating why thread deserves attention now...",
                )
            )
            all_threads = thread_service.list_threads(unfinished_only=False)
            target_id, target_title, is_ambiguous, is_unknown = _resolve_target_thread(
                msg_lower=msg_lower,
                session=session,
                available_threads=[t.model_dump() for t in all_threads],
                extracted_topic=classified.extracted_topic,
                is_unknown=classified.is_unknown,
                has_pronoun=classified.has_pronoun,
            )
            if not target_id and all_threads:
                if session.active_thread_id:
                    target_id = session.active_thread_id
                else:
                    candidates = attention_engine.evaluate_threads(
                        [
                            t
                            for t in all_threads
                            if t.status
                            in (
                                ThreadStatus.ACTIVE,
                                ThreadStatus.BLOCKED,
                                ThreadStatus.WAITING,
                            )
                        ]
                    )
                    if candidates:
                        target_id = candidates[0].thread_id

            if not target_id:
                return AgentChatResponse(
                    message="Which intention would you like me to analyze for why it needs attention now?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            target_thread = thread_service.get_thread(target_id)
            if target_thread is None:
                return AgentChatResponse(
                    message=f"I couldn't locate thread '{target_id}' to explain why it deserves attention.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            session.active_thread_id = target_thread.id
            explanation = why_now_service.explain(target_thread)

            if explanation.has_reason:
                lines = [f"**Why {target_thread.title} deserves attention now**:"]
                lines.append(f"{explanation.concise_alexa_text}\n")
                lines.append("Contributing factors:")
                for f in explanation.contributing_factors:
                    lines.append(f"• {f}")
                response_text = "\n".join(lines)
            else:
                response_text = f"**{target_thread.title}** currently has no pressing deadlines, blockers, or decay. All signals are normal."

            return AgentChatResponse(
                message=response_text,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # Proactive Conflicts
        if classified.intent == IntentType.PROACTIVE_CONFLICTS:
            _log_agent_observability(
                session.conversation_id,
                decision="detect_cross_thread_conflicts",
            )
            activities.append(
                ToolActivity(
                    tool_name="detect_conflicts",
                    summary="Evaluating conservative cross-thread conflicts...",
                )
            )
            all_threads = thread_service.list_threads(unfinished_only=False)
            conflicts = attention_engine.detect_cross_thread_conflicts(all_threads)

            if conflicts:
                lines = [
                    f"I identified {len(conflicts)} conservative conflict(s) between your intentions:"
                ]
                lines.append("")
                for c in conflicts:
                    lines.append(
                        f"• **{c.conflict_type.value}** ({c.thread_a_title} ↔ {c.thread_b_title}):\n  {c.explanation}"
                    )
                response_text = "\n".join(lines)
            else:
                response_text = "No conflicting intentions were determined based on your scheduled commitments, deadlines, and exclusive resources."

            return AgentChatResponse(
                message=response_text,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # Proactive Resumable Check
        if classified.intent == IntentType.PROACTIVE_RESUMABLE:
            _log_agent_observability(
                session.conversation_id,
                decision="check_resumable_threads",
            )
            activities.append(
                ToolActivity(
                    tool_name="check_resumable",
                    summary="Evaluating deferred threads against resume decision table...",
                )
            )
            deferred = thread_service.list_threads(
                status=ThreadStatus.DEFERRED, unfinished_only=False
            )
            candidates = [attention_engine.evaluate_thread_resume(t) for t in deferred]
            resumables = [
                c for c in candidates if c.eligibility == ResumeEligibility.RESUMABLE
            ]

            if resumables:
                lines = [
                    "The following deferred intention(s) are eligible to be resumed:"
                ]
                lines.append("")
                for r in resumables:
                    lines.append(f"• **{r.thread_title}**: {r.reason}")
                lines.append(
                    "\nNote: Resumption requires your explicit confirmation and is not performed automatically. Would you like me to prepare a resumption action?"
                )
                response_text = "\n".join(lines)
            else:
                response_text = "None of your deferred intentions are currently eligible for resumption."

            return AgentChatResponse(
                message=response_text,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 4a. M13 Persistent Intent Intelligence Handlers
        # -------------------------------------------------------------------

        # Intent Radar Scan
        if classified.intent == IntentType.INTENT_RADAR:
            _log_agent_observability(
                session.conversation_id,
                decision="intent_radar_scan",
                tool="discover_unfinished_threads",
            )
            activities.append(
                ToolActivity(
                    tool_name="discover_unfinished_threads",
                    summary="Scanning Intent Radar across all active threads...",
                )
            )
            threads = available_threads
            if not threads:
                return AgentChatResponse(
                    message="Your Intent Radar is completely clear! You have no open or decaying intentions.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            # Sort by radar_score descending
            sorted_threads = sorted(
                threads,
                key=lambda t: t.get("radar_score", 0),
                reverse=True,
            )
            top_thread = sorted_threads[0]
            session.active_thread_id = top_thread.get("id")

            lines = [
                "Here is your **Intent Radar** scan, prioritized by urgency and attention:"
            ]
            lines.append("")
            lines.append(
                f"🎯 **Top Focus**: **{top_thread.get('title')}** (Urgency: {top_thread.get('radar_score', 0)}/100, Attention: {top_thread.get('attention_level', 'HIGH')})\n"
                f"   • Signal: {top_thread.get('radar_explanation', 'Needs attention')}"
            )
            lines.append("\n**Other Monitored Intentions**:")
            for t in sorted_threads[1:]:
                score = t.get("radar_score", 0)
                decay = t.get("decay_state", "HEALTHY")
                lines.append(
                    f"• **{t.get('title')}** — Score: {score}/100 | State: {decay} | Status: {t.get('status')}"
                )

            lines.append(
                "\nWould you like me to assist with your top priority or inspect what changed?"
            )
            radar_report_payload = {
                "items": [
                    {
                        "thread_id": t.get("id"),
                        "title": t.get("title"),
                        "radar_score": t.get("radar_score", 0),
                        "decay_state": str(t.get("decay_state", "HEALTHY")),
                        "attention_level": str(t.get("attention_level", "LOW")),
                        "explanation": t.get("radar_explanation", ""),
                        "recommended_focus": t.get("id") == top_thread.get("id"),
                    }
                    for t in sorted_threads
                ],
                "top_focus_thread_id": top_thread.get("id"),
            }
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
                radar_report=radar_report_payload,
            )

        # Intent Decay Detection
        if classified.intent == IntentType.INTENT_DECAY:
            _log_agent_observability(
                session.conversation_id,
                decision="check_intent_decay",
                tool="discover_unfinished_threads",
            )
            activities.append(
                ToolActivity(
                    tool_name="discover_unfinished_threads",
                    summary="Inspecting intent decay and inactivity...",
                )
            )
            decaying = [
                t
                for t in available_threads
                if str(t.get("decay_state", "")).upper()
                in ("ATTENTION", "DECAYING", "STALE")
            ]
            if not decaying:
                return AgentChatResponse(
                    message="All your tracked intentions are in a healthy, active state. No decay or staleness detected.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            lines = [
                f"I detected **{len(decaying)} intention(s)** showing signs of decay or inactivity:"
            ]
            for d in decaying:
                lines.append(
                    f"• **{d.get('title')}** (State: {d.get('decay_state')})\n"
                    f"  {d.get('radar_explanation', 'Needs review due to inactivity')}"
                )
            lines.append("\nWould you like me to help you take action on any of these?")
            return AgentChatResponse(
                message="\n".join(lines),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # Ambiguous Intent Evolution (Safety invariant: must never mutate state)
        if classified.intent == IntentType.AMBIGUOUS_INTENT_EVOLUTION:
            _log_agent_observability(
                session.conversation_id,
                decision="ambiguous_intent_evolution_hold",
            )
            target_name = title or "your intention"
            return AgentChatResponse(
                message=(
                    f"It sounds like your goals for {target_name} might be shifting. "
                    "To ensure accuracy and prevent unintended changes, I won't update your goal until you specify a clear objective. "
                    "What specific new outcome or goal would you like to set?"
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # Intent Evolution (Invariant 3 & 6: prepare_action -> execute_action with direct persistence for explicit intent)
        if classified.intent == IntentType.INTENT_EVOLUTION:
            _log_agent_observability(
                session.conversation_id,
                decision="evolve_intent",
                tool="prepare_action -> execute_action",
            )
            if is_ambiguous or not target_id:
                return AgentChatResponse(
                    message="I found multiple open intentions. Which intention would you like to update?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            new_goal = classified.parameters.get("new_goal")
            if not new_goal:
                return AgentChatResponse(
                    message=f"What new goal or objective would you like to set for {title}?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            activities.append(
                ToolActivity(
                    tool_name="prepare_action",
                    summary=f"Preparing goal evolution proposal for {title}...",
                )
            )
            prep_res = await mcp_client.prepare_action(
                thread_id=target_id,
                action_type="EVOLVE_INTENTION",
                parameters={
                    "new_goal": new_goal,
                    "reason": "User requested goal evolution",
                },
            )
            proposal = prep_res.get("proposal", {})
            proposal_id = proposal.get("id")

            activities.append(
                ToolActivity(
                    tool_name="execute_action",
                    summary=f"Applying goal evolution for {title}...",
                )
            )
            await mcp_client.execute_action(
                proposal_id=proposal_id,
                confirmed=True,
                execution_mode="PERSISTENT_MUTATION",
            )

            session.active_thread_id = target_id
            session.last_executed_proposal_id = proposal_id
            session.last_executed_mode = "PERSISTENT_MUTATION"
            return AgentChatResponse(
                message=(
                    f"I have evolved your goal for **{title}**.\n\n"
                    f"• **Current Goal**: {new_goal}\n"
                    f"• **Execution Mode**: PERSISTENT_MUTATION (Durable internal Threadback state mutated)\n"
                    f"• **Audit Event**: Recorded in persistent thread history\n"
                    f"• **Original Goal**: Remains safely preserved and immutable\n\n"
                    "Would you like me to check the next steps or review open commitments for this updated goal?"
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                proposal_id=proposal_id,
                activities=activities,
                execution_status="EXECUTED",
                execution_mode="PERSISTENT_MUTATION",
            )

        # What Changed
        if classified.intent == IntentType.WHAT_CHANGED:
            _log_agent_observability(
                session.conversation_id,
                decision="what_changed_diff",
                tool="get_thread_context",
            )
            diff_target_id = target_id or session.active_thread_id
            if not diff_target_id and available_threads:
                diff_target_id = available_threads[0].get("id")

            if not diff_target_id:
                return AgentChatResponse(
                    message="You have no active threads to inspect changes for.",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )

            thread_title = TITLE_MAP.get(diff_target_id, diff_target_id)
            activities.append(
                ToolActivity(
                    tool_name="get_thread_context",
                    summary=f"Inspecting chronological state changes for {thread_title}...",
                )
            )
            ctx_res = await mcp_client.get_thread_context(diff_target_id)
            thread_data = ctx_res.get("thread", {})

            events = thread_data.get("events", [])
            recent_events = events[-3:] if events else []
            if recent_events:
                changes_summary = "; ".join(
                    e.get("description", "") for e in recent_events
                )
                msg = (
                    f"Here is what changed recently for **{thread_title}**:\n\n"
                    f"• **Summary**: {changes_summary}\n\n"
                    f"All changes are deterministically grounded by your audit events."
                )
            else:
                msg = f"No state changes detected for **{thread_title}** since your last checkpoint."

            return AgentChatResponse(
                message=msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
                diff_summary={
                    "thread_id": diff_target_id,
                    "has_changes": bool(recent_events),
                },
            )

        # Lifecycle Defer
        if classified.intent == IntentType.LIFECYCLE_DEFER:
            if is_ambiguous or not target_id:
                target_id = session.active_thread_id
            if not target_id:
                return AgentChatResponse(
                    message="Which intention would you like to defer?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            deferred_until = classified.parameters.get("deferred_until")
            activities.append(
                ToolActivity(
                    tool_name="prepare_action",
                    summary=f"Preparing defer proposal for {title}...",
                )
            )
            prep = await mcp_client.prepare_action(
                thread_id=target_id,
                action_type="DEFER_INTENTION",
                parameters={
                    "deferred_until": deferred_until,
                    "reason": "Postponed by user",
                },
            )
            proposal_id = prep.get("proposal", {}).get("id")
            activities.append(
                ToolActivity(
                    tool_name="execute_action",
                    summary=f"Applying deferral for {title}...",
                )
            )
            await mcp_client.execute_action(
                proposal_id=proposal_id,
                confirmed=True,
                execution_mode="PERSISTENT_MUTATION",
            )
            session.last_executed_proposal_id = proposal_id
            session.last_executed_mode = "PERSISTENT_MUTATION"
            return AgentChatResponse(
                message=(
                    f"I have placed **{title}** into **DEFERRED** status (until {deferred_until or 'further notice'}).\n\n"
                    "• **Execution Mode**: PERSISTENT_MUTATION (Durable internal Threadback state mutated)\n"
                    "• All commitments, evidence, and history are preserved in your archive.\n"
                    "• The intention will not clutter your active radar until you are ready to resume it."
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                proposal_id=proposal_id,
                activities=activities,
                execution_status="EXECUTED",
                execution_mode="PERSISTENT_MUTATION",
            )

        # Lifecycle Resume
        if classified.intent == IntentType.LIFECYCLE_RESUME:
            if not target_id:
                target_id = session.active_thread_id
            if not target_id:
                return AgentChatResponse(
                    message="Which deferred intention would you like to resume?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            activities.append(
                ToolActivity(
                    tool_name="prepare_action",
                    summary=f"Preparing resume proposal for {title}...",
                )
            )
            prep = await mcp_client.prepare_action(
                thread_id=target_id,
                action_type="RESUME_INTENTION",
            )
            proposal_id = prep.get("proposal", {}).get("id")
            activities.append(
                ToolActivity(
                    tool_name="execute_action",
                    summary=f"Resuming thread {title}...",
                )
            )
            await mcp_client.execute_action(
                proposal_id=proposal_id,
                confirmed=True,
                execution_mode="PERSISTENT_MUTATION",
            )
            session.active_thread_id = target_id
            session.last_executed_proposal_id = proposal_id
            session.last_executed_mode = "PERSISTENT_MUTATION"
            return AgentChatResponse(
                message=(
                    f"I have resumed **{title}** back into your active intentions!\n\n"
                    "• **Execution Mode**: PERSISTENT_MUTATION (Durable internal Threadback state mutated)\n"
                    "• Lifecycle status restored to ACTIVE."
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                proposal_id=proposal_id,
                activities=activities,
                execution_status="EXECUTED",
                execution_mode="PERSISTENT_MUTATION",
            )

        # Lifecycle Abandon
        if classified.intent == IntentType.LIFECYCLE_ABANDON:
            if not target_id:
                target_id = session.active_thread_id
            if not target_id:
                return AgentChatResponse(
                    message="Which intention would you like to abandon?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            activities.append(
                ToolActivity(
                    tool_name="prepare_action",
                    summary=f"Preparing abandonment proposal for {title}...",
                )
            )
            prep = await mcp_client.prepare_action(
                thread_id=target_id,
                action_type="ABANDON_INTENTION",
                parameters={"reason": "User requested abandonment"},
            )
            proposal = prep.get("proposal", {})
            proposal_id = proposal.get("id")
            session.set_pending_proposal(
                proposal_id, target_id, action_type="ABANDON_INTENTION"
            )
            return AgentChatResponse(
                message=(
                    f"Abandoning an intention is an explicit lifecycle termination.\n\n"
                    f"I have prepared an abandonment proposal ({proposal_id}). "
                    f"Crucial invariant: all historical evidence, commitments, and notes for **{title}** will remain preserved in your archive.\n\n"
                    "Are you sure you want to abandon this intention? Please reply 'Yes' or 'Go ahead' to confirm."
                ),
                conversation_id=session.conversation_id,
                pending_confirmation=True,
                proposal_id=proposal_id,
                thread_id=target_id,
                activities=activities,
            )

        # Intent Summary
        if classified.intent == IntentType.INTENT_SUMMARY:
            if not target_id:
                target_id = session.active_thread_id or (
                    available_threads[0].get("id") if available_threads else None
                )
            if not target_id:
                return AgentChatResponse(
                    message="Which intention would you like me to summarize?",
                    conversation_id=session.conversation_id,
                    pending_confirmation=False,
                    activities=activities,
                )
            activities.append(
                ToolActivity(
                    tool_name="get_thread_context",
                    summary=f"Retrieving structured summary for {title}...",
                )
            )
            ctx = await mcp_client.get_thread_context(target_id)
            t = ctx.get("thread", {})
            cur_goal = t.get("current_goal") or t.get("description", "")
            orig_goal = t.get("original_goal") or t.get("description", "")
            status = t.get("status", "")
            comms = t.get("commitments", [])
            open_comms = [c for c in comms if c.get("status") == "OPEN"]
            deps = t.get("dependencies", [])
            blockers = [
                d for d in deps if d.get("blocking") and d.get("status") == "OPEN"
            ]

            msg = (
                f"**Intent Summary for {title}**\n\n"
                f"• **Current Goal**: {cur_goal}\n"
                f"• **Original Goal**: {orig_goal}\n"
                f"• **Status**: {status}\n"
                f"• **Open Commitments**: {len(open_comms)} pending\n"
                f"• **Active Blockers**: {len(blockers)} blocking\n"
            )
            if blockers:
                msg += f"• **Primary Blocker**: {blockers[0].get('description')}\n"
            return AgentChatResponse(
                message=msg,
                conversation_id=session.conversation_id,
                pending_confirmation=False,
                activities=activities,
            )

        # -------------------------------------------------------------------
        # 5. Lifecycle Closure Flow (Phase 9): "Close it" / "I'm done with it"
        # -------------------------------------------------------------------
        if classified.intent == IntentType.CLOSURE:
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
            ver_res = await mcp_client.verify_thread_completion(target_id)
            verified = ver_res.get("verified", False)
            reason = ver_res.get("reason", "")

            _log_agent_observability(
                session.conversation_id,
                decision="closure_verification_result",
                tool="verify_thread_completion",
                result_status="VERIFIED" if verified else "NOT_VERIFIED",
            )
            activities.append(
                ToolActivity(
                    tool_name="verify_thread_completion",
                    summary=(
                        f"Completion criteria evaluated before closing '{target_id}' — VERIFIED"
                        if verified
                        else f"Completion criteria evaluated before closing '{target_id}' — NOT VERIFIED"
                    ),
                )
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
        # 6. Blocker Investigation (Phase 3): "Why isn't it finished?" / "What's holding this up?"
        # -------------------------------------------------------------------
        if classified.intent == IntentType.BLOCKER_INVESTIGATION:
            # If user asks generally "What is blocking me?" with no active thread
            if not target_id and (
                "what is blocking" in msg_lower
                or "what's blocking" in msg_lower
                or "blockers" in msg_lower
                or "holding" in msg_lower
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
        # 7. Verification Flow (Phase 8): "Is it actually finished?" / "Did I complete it?"
        # -------------------------------------------------------------------
        if classified.intent == IntentType.VERIFICATION:
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
            activities.append(
                ToolActivity(
                    tool_name="verify_thread_completion",
                    summary=(
                        f"Completion evidence evaluated for '{target_id}' — VERIFIED"
                        if verified
                        else f"Completion evidence evaluated for '{target_id}' — NOT VERIFIED"
                    ),
                )
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
        # 8. Action Preparation (Phase 5): "Help me finish it" / "Can you help me do that?"
        # -------------------------------------------------------------------
        if classified.intent == IntentType.PREPARE_ACTION:
            target_id = None
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
            elif classified.extracted_topic:
                search_term = classified.extracted_topic
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
                if not threads and search_term in (
                    None,
                    "project",
                    "task",
                    "thread",
                ):
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
        # 9. Next Action Flow (Phase 4): "What should I do now?" / "What's my next step?"
        # -------------------------------------------------------------------
        if classified.intent == IntentType.NEXT_ACTION:
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
        # 10. Context Reconstruction (Phase 2): "Where did I leave off..." / "Where was I with my application?"
        # -------------------------------------------------------------------
        if classified.intent == IntentType.CONTEXT_RECONSTRUCTION:
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
        # 11. General Discovery Flow (Phase 1): "What am I forgetting?"
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
