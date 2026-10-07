"""
Systematic natural-language intent classifier for Threadback Alexa+ agent.

Provides structured intent classification across general conversation,
confirmation flows, and domain intention lifecycle stages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.agent.state import is_ambiguous_confirmation, is_explicit_confirmation


class IntentType(str, Enum):
    # Non-domain / General conversation (MUST NOT invoke MCP tools)
    GREETING = "greeting"
    THANKS = "thanks"
    CAPABILITIES = "capabilities"
    OUT_OF_SCOPE = "out_of_scope"

    # Confirmation safety flows
    EXPLICIT_CONFIRMATION = "explicit_confirmation"
    AMBIGUOUS_CONFIRMATION = "ambiguous_confirmation"
    CANCELLATION = "cancellation"

    # Domain lifecycle intents (M3–M10)
    DISCOVERY = "discovery"
    CONTEXT_RECONSTRUCTION = "context_reconstruction"
    BLOCKER_INVESTIGATION = "blocker_investigation"
    NEXT_ACTION = "next_action"
    PREPARE_ACTION = "prepare_action"
    VERIFICATION = "verification"
    CLOSURE = "closure"

    # M13 Intent Intelligence & Persistent Memory
    INTENT_RADAR = "intent_radar"
    INTENT_DECAY = "intent_decay"
    WHAT_CHANGED = "what_changed"
    INTENT_EVOLUTION = "intent_evolution"
    AMBIGUOUS_INTENT_EVOLUTION = "ambiguous_intent_evolution"
    LIFECYCLE_DEFER = "lifecycle_defer"
    LIFECYCLE_RESUME = "lifecycle_resume"
    LIFECYCLE_ABANDON = "lifecycle_abandon"
    INTENT_SUMMARY = "intent_summary"

    # M14 Proactive Intent Intelligence
    PROACTIVE_ATTENTION = "proactive_attention"
    PROACTIVE_WHY_NOW = "proactive_why_now"
    PROACTIVE_BRIEFING = "proactive_briefing"
    PROACTIVE_CONFLICTS = "proactive_conflicts"
    PROACTIVE_RESUMABLE = "proactive_resumable"

    # M15 Intent Copilot & Proactive Agent Experience
    COPILOT_PRIORITIZE = "copilot_prioritize"
    COPILOT_WHY_IMPORTANT = "copilot_why_important"
    COPILOT_WHAT_IF = "copilot_what_if"
    COPILOT_TIME_BUDGET = "copilot_time_budget"
    COPILOT_RESUME_WHERE_LEFT_OFF = "copilot_resume_where_left_off"
    COPILOT_SAFE_CLOSURE = "copilot_safe_closure"
    COPILOT_WHAT_BLOCKING = "copilot_what_blocking"
    COPILOT_HELP_DEAL = "copilot_help_deal"
    COPILOT_OPTIONS = "copilot_options"

    # Fallback / Clarification
    UNKNOWN = "unknown"


@dataclass
class ClassifiedIntent:
    intent: IntentType
    confidence: float = 1.0
    extracted_topic: str | None = None
    is_unknown: bool = False
    has_pronoun: bool = False
    raw_message: str = ""
    parameters: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {}


# ---------------------------------------------------------------------------
# Compiled regex patterns for systematic classification
# ---------------------------------------------------------------------------

GREETING_WORDS = {
    "hello",
    "hi",
    "hey",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
    "hiya",
    "hello there",
    "hi there",
}

THANKS_PATTERNS = [
    r"^\s*(thanks|thank\s+you|many\s+thanks|thx|appreciate\s+it|thank\s+you\s+so\s+much|thanks\s+a\s+lot|thanks\s+for\s+(your\s+)?help)\b",
]

CAPABILITIES_PATTERNS = [
    r"\b(what\s+is\s+threadback|who\s+are\s+you|what\s+are\s+you|what\s+can\s+you\s+do|what\s+can\s+you\s+help\s+(me\s+)?with|how\s+can\s+you\s+help|what\s+do\s+you\s+do|how\s+does\s+threadback\s+work|how\s+do\s+you\s+work|what\s+are\s+your\s+capabilities|what\s+features\s+do\s+you\s+have)\b",
    r"^\s*(help|help\s+me|what\s+can\s+i\s+ask|commands|options)\s*[\.\?!]?$",
]

OUT_OF_SCOPE_PATTERNS = [
    r"\b(weather|temperature|forecast|rain\s+today|tell\s+me\s+a\s+joke|who\s+is\s+president|capital\s+of|how\s+tall\s+is|sing\s+a\s+song|meaning\s+of\s+life|play\s+music)\b",
]

CLOSURE_PATTERNS = [
    r"^\s*close\s+(it|this|that|the\s+thread|the\s+application|the\s+report)\s*[\.\?!]?$",
    r"^\s*(i'm|im|i\s+am|we're|we\s+are)\s+done\s+with\s+(it|this|that|the\s+thread|the\s+application|the\s+report)\s*[\.\?!]?$",
    r"\b(close|wrap\s+up)\b.*(\bit\b|\bthat\b|\bthis\b|\bthread\b|\btask\b|\bapplication\b|\breport\b)",
    r"\bmark\s+(it\s+)?(as\s+)?(finished|complete|completed|done)\b",
    r"\b(i'm|im|i\s+am|we're|we\s+are)\s+done\s+with\b",
]

VERIFICATION_PATTERNS = [
    r"\b(is|did|has)\b.*(actually|really)?\s+\b(finished|completed|complete|done)\b",
    r"\bverify\b.*(completion|thread|status|finished)?",
    r"\bactually\s+finished\b",
    r"\b(did\s+i|have\s+i)\s+(actually\s+)?(finish|complete)\b",
    r"\bcheck\s+if\s+(it|this|that|the\s+application)\s+is\s+(done|finished|complete)\b",
]

BLOCKER_PATTERNS = [
    r"\bwhy\b.*(isn't|is\s+not|haven't|have\s+not|not|unfinished|blocked|pending|holding|stuck)\b",
    r"\bwhat('?s|\s+is|\s+are)\s+(holding\s+(this|it|us|things)\s+up|blocking|the\s+blocker|the\s+blockers|the\s+holdup|stopping)\b",
    r"\bwhat('?s|\s+is)\s+holding\s+this\s+up\b",
    r"\bwhy\s+isn't\s+it\s+finished\b",
    r"\bwhy\s+is\s+(this|that|it|my\s+[a-z]+|the\s+[a-z]+)\s+still\s+unfinished\b",
    r"\bwhy\s+is\s+it\s+unfinished\b",
    r"\bwhat('?s|\s+is)\s+blocking\s+me\b",
    r"\b(blocker|blockers|holdup)\b",
]

PREPARE_ACTION_PATTERNS = [
    r"\b(can\s+you\s+)?help\s+(me\s+)?(to\s+)?(finish|do\s+that|resolve|take\s+care|proceed)\b",
    r"\blet('?s|\s+us)\s+(take\s+care\s+of\s+it|do\s+that|do\s+it|resolve\s+this|handle\s+it|proceed)\b",
    r"\bprepare\s+(the\s+|an\s+)?action\b",
    r"\btake\s+care\s+of\s+(it|that|this)\b",
    r"\bhelp\s+me\s+finish\b",
    r"\bproceed\s+with\s+(application|report|thread|task)\b",
    r"\bhelp\s+me\s+do\s+that\b",
]

NEXT_ACTION_PATTERNS = [
    r"\bwhat\s+(should|can|do)\s+(i|we)\s+do\s*(now|next)?\b",
    r"\bwhat('?s|\s+is)\s+(my\s+|the\s+)?next\s+(step|action|move)\b",
    r"\bwhat\s+to\s+do\s+next\b",
    r"\bwhere\s+do\s+we\s+go\s+from\s+here\b",
    r"\bnext\s+(step|action)\b",
]

CONTEXT_PATTERNS = [
    r"\bwhere\s+(did|was|were)\s+(i|we)\s*(leave\s+off)?\b",
    r"\bwhere\s+was\s+i\s+(with|on)\b",
    r"\b(can\s+you\s+)?remind\s+me\s+(what\s+i\s+had\s+done|where\s+i\s+was|about)\b",
    r"\bwhat\s+happened\s+(with|to)\s+(that|the|my)\b",
    r"\bleave\s+off\b",
    r"\bwhat('?s|\s+is)\s+the\s+status\s+of\b",
    r"\bstatus\s+of\s+(my|the)\b",
    r"\bcatch\s+me\s+up\b",
]

DISCOVERY_PATTERNS = [
    r"\bwhat\s+(am\s+i|did\s+i)\s+forgetting\b",
    r"\bwhat\s+did\s+i\s+forget\b",
    r"\bdid\s+i\s+leave\s+anything\s+unfinished\b",
    r"\bis\s+there\s+anything\s+(i\s+)?(still\s+)?need\s+to\s+(deal\s+with|finish|do)\b",
    r"\b(is\s+there\s+)?anything\s+(i\s+)?(forgot|forgetting)\b",
    r"\b(do\s+i\s+have\s+)?(any\s+)?open\s+(commitments|threads|tasks|items|intentions)\b",
    r"\bwhat('?s|\s+is)\s+(open|pending|unfinished)\b",
    r"\bwhat\s+needs\s+my\s+attention\b",
    r"\bwhat('?s|\s+is)\s+on\s+my\s+plate\b",
    r"\bshow\s+(me\s+)?(my\s+)?(open|unfinished)\s+(threads|commitments|intentions|tasks)\b",
    r"\banything\s+unfinished\b",
    r"\banything\s+i\s+still\s+need\s+to\s+deal\s+with\b",
    r"\b(forget|forgot|forgetting)\b",
]

# ---------------------------------------------------------------------------
# M13 Intent Intelligence & Persistent Memory Patterns
# ---------------------------------------------------------------------------

RADAR_PATTERNS = [
    r"\b(intent\s+radar|radar\s+scan|scan\s+(my\s+)?radar|show\s+(my\s+)?radar|radar\s+report)\b",
    r"\b(what\s+should\s+i\s+focus\s+on|top\s+focus|top\s+priority|where\s+should\s+i\s+focus)\b",
    r"\b(prioritize\s+my\s+(intentions|threads|commitments))\b",
]

DECAY_PATTERNS = [
    r"\b(decay|decaying|decay\s+state|decay\s+signal|stale|stale\s+intentions|decaying\s+intentions)\b",
    r"\b(which|are\s+any)\s+(intentions|threads|tasks)\s+(are\s+)?(decaying|stale|neglected|forgotten|idle)\b",
    r"\bcheck\s+decay\b",
]

WHAT_CHANGED_PATTERNS = [
    r"\bwhat\s+(has\s+)?changed(\s+since)?\b",
    r"\bwhat('?s|\s+is)\s+new\b",
    r"\b(state\s+diff|what\s+changed|recent\s+changes|any\s+updates\s+to\s+my\s+intentions)\b",
    r"\bwhat\s+changed\s+since\s+(yesterday|last\s+week|checkpoint|last\s+time)\b",
    r"\b(anything\s+important\s+since\s+(i\s+last\s+checked|last\s+time)|anything\s+changed)\b",
]

AMBIGUOUS_EVOLUTION_PATTERNS = [
    r"\b(i\s+might\s+want\s+to\s+change|maybe\s+i\s+should\s+change|thinking\s+about\s+changing|not\s+sure\s+if\s+i\s+want\s+to\s+change|could\s+we\s+possibly\s+change)\b",
    r"\b(might\s+change\s+my\s+mind|wondering\s+if\s+i\s+should\s+switch)\b",
]

EVOLUTION_PATTERNS = [
    r"\b(update|change|evolve|revise|modify|switch)\s+(?:(?:my|the)\s+)?(?:[a-z0-9_-]+\s+)?(goal|objective|intention)\b",
    r"\b(my\s+goal\s+is\s+now|my\s+new\s+goal\s+is|evolve\s+goal\s+to|evolve\s+intention\s+to)\b",
    r"\binstead\s+of\s+.*,\s*(let's|i\s+want\s+to|now)\b",
    r"\bnew\s+goal\s+for\b",
]

DEFER_PATTERNS = [
    r"\b(defer|postpone|put\s+on\s+hold|delay|snooze)\b",
    r"\b(pause|hold\s+off\s+on)\s+(the\s+|this\s+|my\s+)?([a-z\s]+)\b",
]

RESUME_PATTERNS = [
    r"\b(resume|reactivate|unpause|un-defer|bring\s+back)\b",
    r"\b(pick\s+up\s+where\s+i\s+left\s+off\s+on\s+(the\s+|my\s+)?deferred)\b",
]

ABANDON_PATTERNS = [
    r"\b(abandon|drop\s+the\s+goal|abandon\s+the\s+thread|forget\s+about\s+(the\s+|this\s+)?(goal|thread|intention))\b",
    r"\b(give\s+up\s+on|no\s+longer\s+pursuing|stop\s+tracking)\b",
]

SUMMARY_PATTERNS = [
    r"\b(summarize|summary\s+of|overview\s+of)\s+(my\s+|the\s+)?(intentions|intention|goals|thread)\b",
    r"\bintent\s+summary\b",
]

# ---------------------------------------------------------------------------
# M14 Proactive Intent Intelligence Patterns
# ---------------------------------------------------------------------------

PROACTIVE_ATTENTION_PATTERNS = [
    r"\b(what\s+deserves\s+(my\s+)?attention|what\s+needs\s+(my\s+)?attention|what\s+requires\s+(my\s+)?attention|attention\s+candidates|attention\s+items|what\s+should\s+i\s+pay\s+attention\s+to|what\s+deserves\s+attention)\b",
]

PROACTIVE_WHY_NOW_PATTERNS = [
    r"\b(why\s+(should\s+i\s+)?care\s+(about\s+this\s+)?now|why\s+now|why\s+does\s+this\s+deserve\s+attention|why\s+this\s+now|why\s+care\s+now)\b",
]

PROACTIVE_BRIEFING_PATTERNS = [
    r"\b(give\s+me\s+a\s+briefing|proactive\s+briefing|daily\s+briefing|morning\s+briefing|intent\s+briefing|executive\s+briefing|briefing\s+please|give\s+me\s+a\s+proactive\s+briefing|briefing)\b",
]

PROACTIVE_CONFLICTS_PATTERNS = [
    r"\b(do\s+any\s+of\s+my\s+intentions\s+conflict|intent\s+conflicts|check\s+conflicts|any\s+conflicts|competing\s+intentions|conflicting\s+intentions|conflicting\s+goals|conflicting\s+commitments|do\s+any\s+intentions\s+conflict)\b",
]

PROACTIVE_RESUMABLE_PATTERNS = [
    r"\b(can\s+i\s+resume|what\s+can\s+i\s+resume|is\s+anything\s+resumable|resumable\s+intentions|resumable\s+threads|check\s+resumable|eligible\s+to\s+resume|can\s+i\s+resume\s+anything)\b",
]

# ---------------------------------------------------------------------------
# M15 Intent Copilot & Agent Experience Patterns
# ---------------------------------------------------------------------------

COPILOT_WHAT_IF_PATTERNS = [
    r"\b(what\s+(?:if|happens\s+if)\s+(?:i\s+)?(?:ignore|postpone|delay|defer|put\s+off|resolve|change|fix))\b",
    r"\bwhat\s+can\s+i\s+safely\s+postpone\b",
    r"\bwhat\s+if\s+i\s+postpone\b",
    r"\bwhat\s+if\s+i\s+resolve\s+the\s+blocker\b",
    r"\bwhat\s+happens\s+if\s+i\s+ignore\s+(?:this|it)\b",
]

COPILOT_TIME_BUDGET_PATTERNS = [
    r"\bi\s+have\s+(?:\d+|half\s+an?|one|two|three|\d+\s+to\s+\d+)\s+(?:mins?|minutes?|hours?|hrs?)\b",
    r"\bwhat\s+can\s+i\s+(?:realistically\s+)?(?:finish|work\s+on|complete|do)\s+(?:today|now|in\s+\d+\s+min)\b",
]

COPILOT_PRIORITIZE_PATTERNS = [
    r"\b(what\s+should\s+i\s+(?:deal\s+with|do|work\s+on|tackle|handle)\s+first|what\s+to\s+do\s+first|top\s+priority|what\s+first|which\s+(?:one\s+)?should\s+i\s+(?:choose|pick|do\s+first))\b",
]

COPILOT_WHY_IMPORTANT_PATTERNS = [
    r"\b(why\s+is\s+(?:this|it|that)\s+important|why\s+does\s+(?:this|it)\s+rank\s+(?:high|first)|why\s+is\s+(?:this|it)\s+my\s+top\s+priority|why\s+should\s+i\s+care\s+about\s+this)\b",
    r"^\s*why\s*[\?\.]*\s*$",
]

COPILOT_RESUME_WHERE_LEFT_OFF_PATTERNS = [
    r"\b(continue\s+(?:where\s+i\s+(?:left\s+off|stopped)|my\s+[\w\s]+)|continue\s+where\s+i\s+left\s+off|pick\s+up\s+where\s+i\s+left\s+off)\b",
]

COPILOT_SAFE_CLOSURE_PATTERNS = [
    r"\b(can\s+i\s+close\s+anything|is\s+anything\s+ready\s+to\s+close|what\s+can\s+i\s+close|can\s+anything\s+be\s+closed|ready\s+to\s+close)\b",
]

COPILOT_WHAT_BLOCKING_PATTERNS = [
    r"\b(what\s+is\s+blocking\s+me\s+the\s+most|what(?:'s|\s+is)\s+blocking\s+me\s+the\s+most|biggest\s+blocker|main\s+blocker)\b",
]

COPILOT_HELP_DEAL_PATTERNS = [
    r"\b(help\s+me\s+deal\s+with\s+(?:this|it)|help\s+me\s+move\s+(?:this|it)\s+forward|deal\s+with\s+this|how\s+do\s+i\s+deal\s+with\s+this)\b",
]

COPILOT_OPTIONS_PATTERNS = [
    r"\b(what\s+are\s+my\s+options|which\s+one\s+should\s+i\s+choose|show\s+my\s+options|options\s+for\s+this)\b",
]


def extract_time_budget_minutes(msg_lower: str) -> int:
    m_hour = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\b", msg_lower)
    if m_hour:
        return int(m_hour.group(1)) * 60
    if re.search(r"\b(?:an?|one)\s+hour\b", msg_lower):
        return 60
    if re.search(r"\btwo\s+hours\b", msg_lower):
        return 120
    if re.search(r"\bhalf\s+an?\s+hour\b", msg_lower):
        return 30
    m_min = re.search(r"\b(\d+)\s*(?:mins?|minutes?)\b", msg_lower)
    if m_min:
        return int(m_min.group(1))
    return 30


def extract_what_if_scenario(msg_lower: str) -> tuple[str, dict[str, Any]]:
    if "resolve" in msg_lower and "blocker" in msg_lower:
        return ("RESOLVE_BLOCKER", {})
    if "goal" in msg_lower or "change" in msg_lower:
        return ("CHANGE_GOAL", {})
    if "postpone" in msg_lower or "defer" in msg_lower or "delay" in msg_lower:
        m_days = re.search(r"(\d+)\s*(?:days?|weeks?)", msg_lower)
        days = int(m_days.group(1)) if m_days else 7
        if "week" in msg_lower:
            days = days * 7
        return ("POSTPONE", {"days": days})
    m_days = re.search(r"(\d+)\s*(?:days?|weeks?)", msg_lower)
    days = int(m_days.group(1)) if m_days else 7
    if "week" in msg_lower:
        days = days * 7
    return ("IGNORE_TEMPORARILY", {"days": days})


def extract_revised_goal(msg_raw: str) -> str | None:
    patterns = [
        r"(?:update|change|evolve|revise)\s+(?:(?:my|the)\s+)?(?:[a-z0-9_-]+\s+)?(?:goal|intention|objective)\s+(?:for\s+[^,:]+)?\s*(?:to|as)\s*:?\s*[\"']?([^\"'\n]+)[\"']?",
        r"(?:to|is now|new goal is|goal to)\s*:?\s*[\"']?([^\"'\n]+)[\"']?",
    ]
    for p in patterns:
        m = re.search(p, msg_raw, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) > 3:
                return candidate
    return None


def extract_deferred_until(msg_raw: str) -> str | None:
    m = re.search(r"\buntil\s+([a-zA-Z0-9\s]+?)(?:[\.\?!]|$)", msg_raw, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


CANCELLATION_PATTERNS = [
    r"^\s*(no|cancel|stop|abort|don't|dont|nevermind|leave\s+it)\b",
]

KNOWN_TOPIC_KEYWORDS = {
    "application": "thread-university-application",
    "university": "thread-university-application",
    "grad": "thread-university-application",
    "client": "thread-client-report",
    "report": "thread-client-report",
    "dentist": "thread-dentist-appointment",
    "dental": "thread-dentist-appointment",
    "teeth": "thread-dentist-appointment",
    "hackathon": "thread-aws-hackathon",
    "aws": "thread-aws-hackathon",
    "tax": "thread-tax-filing",
    "taxes": "thread-tax-filing",
    "gym": "thread-old-gym-membership",
    "certification": "thread-professional-certification",
    "cert": "thread-professional-certification",
    "pitch": "thread-client-pitch",
    "presentation": "thread-board-presentation",
    "board": "thread-board-presentation",
}

UNKNOWN_TOPIC_KEYWORDS = [
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
    "passport",
]


def extract_topic(msg_lower: str) -> tuple[str | None, bool]:
    """
    Extracts known or unknown topic keywords from user message.
    Returns (topic_name, is_unknown).
    Uses word boundaries to avoid false positives (e.g. 'car' in 'care').
    """
    for kw, topic in KNOWN_TOPIC_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", msg_lower):
            return (topic, False)

    for kw in UNKNOWN_TOPIC_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", msg_lower):
            return (kw, True)

    return (None, False)


def has_pronoun_reference(msg_lower: str) -> bool:
    """Checks if message contains pronoun or relative referential continuity tokens."""
    return bool(
        re.search(
            r"\b(it|that|this|the\s+thread|the\s+application|the\s+intention|leave\s+off|where\s+was\s+i|where\s+were\s+we|where\s+did\s+i|blocker)\b",
            msg_lower,
        )
    )


def classify_intent(
    message: str,
    has_pending_confirmation: bool = False,
) -> ClassifiedIntent:
    """
    Systematically classifies user message into an IntentType with deterministic precision.
    """
    msg_raw = message.strip()
    msg_lower = msg_raw.lower()
    clean_msg = re.sub(r"[^\w\s]", "", msg_lower).strip()

    topic, is_unknown = extract_topic(msg_lower)
    has_pronoun = has_pronoun_reference(msg_lower)

    # 1. Pending Confirmation Gate
    if has_pending_confirmation:
        if is_explicit_confirmation(msg_raw):
            return ClassifiedIntent(
                intent=IntentType.EXPLICIT_CONFIRMATION,
                raw_message=msg_raw,
                has_pronoun=has_pronoun,
            )
        if is_ambiguous_confirmation(msg_raw):
            return ClassifiedIntent(
                intent=IntentType.AMBIGUOUS_CONFIRMATION,
                raw_message=msg_raw,
                has_pronoun=has_pronoun,
            )
        for pattern in CANCELLATION_PATTERNS:
            if re.search(pattern, msg_lower):
                return ClassifiedIntent(
                    intent=IntentType.CANCELLATION,
                    raw_message=msg_raw,
                    has_pronoun=has_pronoun,
                )

    # 2. Explicit Confirmation when NO pending confirmation exists
    if not has_pending_confirmation and is_explicit_confirmation(msg_raw):
        return ClassifiedIntent(
            intent=IntentType.EXPLICIT_CONFIRMATION,
            raw_message=msg_raw,
            has_pronoun=has_pronoun,
        )

    # 3-m15a. What-If Simulation: "What if I postpone this?", "What happens if I ignore this?"
    for pattern in COPILOT_WHAT_IF_PATTERNS:
        if re.search(pattern, msg_lower):
            scenario_name, params = extract_what_if_scenario(msg_lower)
            return ClassifiedIntent(
                intent=IntentType.COPILOT_WHAT_IF,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
                parameters={"scenario": scenario_name, **params},
            )

    # 3-m15b. Time-Budget Planning: "I have 30 minutes", "What can I realistically finish?"
    for pattern in COPILOT_TIME_BUDGET_PATTERNS:
        if re.search(pattern, msg_lower):
            mins = extract_time_budget_minutes(msg_lower)
            return ClassifiedIntent(
                intent=IntentType.COPILOT_TIME_BUDGET,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
                parameters={"available_minutes": str(mins)},
            )

    # 3-m15c. Explainable Prioritization: "What should I deal with first?", "What to do first?"
    for pattern in COPILOT_PRIORITIZE_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_PRIORITIZE,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m15d. Why Important / Why Ranking: "Why is this important?", "Why?"
    for pattern in COPILOT_WHY_IMPORTANT_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_WHY_IMPORTANT,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m15e. Resume Where I Left Off: "Continue where I left off", "Continue my certification"
    for pattern in COPILOT_RESUME_WHERE_LEFT_OFF_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_RESUME_WHERE_LEFT_OFF,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m15f. Safe Closure: "Can I close anything?", "Is anything ready to close?"
    for pattern in COPILOT_SAFE_CLOSURE_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_SAFE_CLOSURE,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m15g. What Is Blocking: "What is blocking me the most?"
    for pattern in COPILOT_WHAT_BLOCKING_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_WHAT_BLOCKING,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m15h. Help Deal With This: "Help me deal with this"
    for pattern in COPILOT_HELP_DEAL_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_HELP_DEAL,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m15i. Options / Decision: "What are my options?"
    for pattern in COPILOT_OPTIONS_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.COPILOT_OPTIONS,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m14a. Proactive Briefing: "Give me a briefing", "Briefing"
    for pattern in PROACTIVE_BRIEFING_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.PROACTIVE_BRIEFING,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m14b. Proactive Attention: "What deserves my attention?"
    for pattern in PROACTIVE_ATTENTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.PROACTIVE_ATTENTION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m14c. Why Now: "Why should I care about this now?", "Why now?"
    for pattern in PROACTIVE_WHY_NOW_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.PROACTIVE_WHY_NOW,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m14d. Conflicts: "Do any of my intentions conflict?"
    for pattern in PROACTIVE_CONFLICTS_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.PROACTIVE_CONFLICTS,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m14e. Resumable check (read-only): "Can I resume anything?", "What can I resume?"
    for pattern in PROACTIVE_RESUMABLE_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.PROACTIVE_RESUMABLE,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13a. Abandon: "Abandon this intention", "Give up on the goal"
    for pattern in ABANDON_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.LIFECYCLE_ABANDON,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13b. Defer: "Defer this intention", "Postpone the dentist appointment"
    for pattern in DEFER_PATTERNS:
        if re.search(pattern, msg_lower):
            until_val = extract_deferred_until(msg_raw)
            return ClassifiedIntent(
                intent=IntentType.LIFECYCLE_DEFER,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
                parameters={"deferred_until": until_val} if until_val else {},
            )

    # 3-m13c. Resume: "Resume this intention", "Reactivate the thread"
    for pattern in RESUME_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.LIFECYCLE_RESUME,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13d. Ambiguous Evolution (Safety invariant: must never mutate state)
    for pattern in AMBIGUOUS_EVOLUTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.AMBIGUOUS_INTENT_EVOLUTION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13e. Intent Evolution: "Update my goal to...", "My goal is now..."
    for pattern in EVOLUTION_PATTERNS:
        if re.search(pattern, msg_lower):
            revised_goal = extract_revised_goal(msg_raw)
            return ClassifiedIntent(
                intent=IntentType.INTENT_EVOLUTION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
                parameters={"new_goal": revised_goal} if revised_goal else {},
            )

    # 3-m13f. Intent Radar: "Scan my intent radar", "What should I focus on?"
    for pattern in RADAR_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.INTENT_RADAR,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13g. Intent Decay: "Which intentions are decaying?", "Check decay"
    for pattern in DECAY_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.INTENT_DECAY,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13h. What Changed: "What changed since yesterday?", "State diff"
    for pattern in WHAT_CHANGED_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.WHAT_CHANGED,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3-m13i. Intent Summary: "Summarize my intention", "Intent summary"
    for pattern in SUMMARY_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.INTENT_SUMMARY,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3a. Closure: "Close it", "I'm done with it", "mark as finished"
    for pattern in CLOSURE_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.CLOSURE,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3b. Blocker Investigation (takes precedence over verification if "why" or "holding up" is present)
    for pattern in BLOCKER_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.BLOCKER_INVESTIGATION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3c. Verification: "Is it actually finished?", "Did I complete it?"
    for pattern in VERIFICATION_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.VERIFICATION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3d. Action Preparation: "Help me finish it", "Let's take care of it", "Can you help me do that?"
    for pattern in PREPARE_ACTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.PREPARE_ACTION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3e. Next Action: "What should I do now?", "What's my next step?"
    for pattern in NEXT_ACTION_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.NEXT_ACTION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3f. Context Reconstruction: "Where was I with my application?", "Can you remind me what I had done?"
    for pattern in CONTEXT_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.CONTEXT_RECONSTRUCTION,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 3g. Discovery: "What am I forgetting?", "Did I leave anything unfinished?", "Is there anything I still need to deal with?"
    for pattern in DISCOVERY_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.DISCOVERY,
                extracted_topic=topic,
                is_unknown=is_unknown,
                has_pronoun=has_pronoun,
                raw_message=msg_raw,
            )

    # 4. Non-domain / General Conversation (Zero MCP Tools)

    # 4a. Greeting
    is_greeting = clean_msg in GREETING_WORDS or any(
        clean_msg.startswith(g + " ") for g in ["hello", "hi", "hey"]
    )
    if is_greeting:
        return ClassifiedIntent(
            intent=IntentType.GREETING,
            raw_message=msg_raw,
        )

    # 4b. Thanks
    for pattern in THANKS_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.THANKS,
                raw_message=msg_raw,
            )

    # 4c. Capabilities / Identity / Help with Threadback
    for pattern in CAPABILITIES_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.CAPABILITIES,
                raw_message=msg_raw,
            )

    # 4d. Out of scope / Chitchat
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, msg_lower):
            return ClassifiedIntent(
                intent=IntentType.OUT_OF_SCOPE,
                raw_message=msg_raw,
            )

    # 5. Direct topic or unknown entity mentioned without clear lifecycle verb
    if is_unknown:
        return ClassifiedIntent(
            intent=IntentType.UNKNOWN,
            extracted_topic=topic,
            has_pronoun=has_pronoun,
            raw_message=msg_raw,
        )

    if topic:
        # If user just said "The university application" or "Client report"
        return ClassifiedIntent(
            intent=IntentType.CONTEXT_RECONSTRUCTION,
            extracted_topic=topic,
            has_pronoun=has_pronoun,
            raw_message=msg_raw,
        )

    # 6. Fallback: transparent out-of-scope response
    return ClassifiedIntent(
        intent=IntentType.OUT_OF_SCOPE,
        raw_message=msg_raw,
    )
