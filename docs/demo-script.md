# Threadback — Final 3-Minute Hackathon Video Pitch Script

**Format:** High-Impact Pitch Video (NOT a Tutorial)  
**Strict Maximum:** **3:00**  
**Spoken Content Target:** **2:34–2:45** (at 135–145 WPM)  
**Total Video Target:** **2:44–2:55** (with ~10s visual/title buffer)  
**Audience:** Hackathon Evaluators & Judges  
**Core Thesis:** *"People don't forget tasks. They forget intentions."*  
**Exact Spoken Word Count:** **371 words** (UI labels and visual callouts are not counted)

---

## 1. Timing & Pacing Calculation

The global duration is derived directly from the verified **371 spoken words**, with approximately 10 seconds reserved for visual pauses and UI animations:

| Speaking Pace | Spoken Duration | Visual Pauses & Transitions | Total Demonstrated Runtime | Safety Buffer Remaining (Before 3:00) |
| :---: | :---: | :---: | :---: | :---: |
| **135 WPM** (Deliberate) | 2 min 45 sec (164.9s) | 10 sec | **2 min 55 sec** (174.9s) | **5 seconds buffer** |
| **140 WPM** (Natural Pitch) | 2 min 39 sec (159.0s) | 10 sec | **2 min 49 sec** (169.0s) | **11 seconds buffer** |
| **145 WPM** (Brisk Delivery) | 2 min 34 sec (153.5s) | 10 sec | **2 min 44 sec** (163.5s) | **16 seconds buffer** |

> **Methodology Note:** The segment timestamps below represent the intended **Target Recording Window** for the demo workflow—including spoken narration, user clicks, UI transitions, and visual pauses—rather than an isolated spoken-duration calculation per individual segment. Global runtime is strictly governed by the verified 371 spoken words.

---

## 2. Segment-by-Segment Storyboard

| Target Recording Window | Segment | Spoken Words | UI Action & On-Screen Visuals |
| :---: | :--- | :---: | :--- |
| **0:00–0:20** | **Hook / The Problem** | 52 | Ambient web UI; checkbox vs. 9-stage lifecycle graphic. |
| **0:20–0:48** | **Discovery & Context** | 62 | Surfaces University Application (`BLOCKED`); pronoun resolution. **MCP Drawer opens**. |
| **0:48–1:15** | **Intent Intelligence / Why Now** | 55 | Attention Radar view; Urgency vs. Attention; Why Now explanation badge. |
| **1:15–1:45** | **Intent Copilot / What-If** | 57 | Counterfactual simulation card; **`SIMULATION — NO STATE CHANGED`** badge; 30m plan. |
| **1:45–2:15** | **Safe Action Execution** | 63 | Action Proposal pause; confirmation gate; **`SIMULATED EXTERNAL ACTION`** badge. |
| **2:15–2:38** | **Verification & Safe Closure** | 51 | Admissions portal proof arrives; Rule D **`VERIFIED`** badge; safe transition to **`COMPLETED`**. |
| **2:38–2:50** | **MCP Track Callout & Close** | 31 | Highlights `/mcp`, Streamable HTTP, Protocol `2025-11-25`, exactly 9 canonical tools. |
| **2:50–3:00** | **Visual Closing & Safety Margin** | 0 | Title card: Logo, GitHub URL, AWS Hackathon / Alexa+ Track badge. |

---

## 3. Word-for-Word Pitch Narration & Visual Actions

### Segment 1: The Hook & The Problem (0:00–0:20)
*Target Recording Window: 20 seconds · 52 spoken words*

#### Spoken Narration
> "People don’t forget tasks. They forget intentions.  
> Traditional to-do apps fail because checklists can’t capture context. When life intervenes, a checkbox cannot capture why an effort stalled, where you left off, or what's blocking you.  
> Threadback reconstructs the living intention thread, turning forgotten open loops into clear, verified next steps."

#### On-Screen Visual Action (Visual-Only)
* Open on Threadback’s ambient interface in dark mode.
* Display a brief graphic overlay: a static to-do checkbox (*"Submit Application"*) dissolving into Threadback's continuous 9-stage lifecycle:  
  `Conversation → Intent → Commitment → Dependency → Unfinished State → Next Action → Evidence → Verification → Closure`.

---

### Segment 2: Discovery & Context Reconstruction (0:20–0:48)
*Target Recording Window: 28 seconds · 62 spoken words*

#### Spoken Narration
> "Asking Threadback *'What am I forgetting?'* instantly surfaces our open loop: the University Application, currently blocked.  
> When we follow up with *'Where did I leave off?'*, Threadback resolves the pronoun and reconstructs the full story: the deadline is in five days, transcripts are received, but progress stalled waiting on Professor Smith's recommendation letter. Notice the live MCP activity drawer orchestrating discovery."

#### On-Screen Visual Action (Visual-Only)
* **Action 1:** Click chip: **`Phase 1: What am I forgetting?`**.  
  *Visual:* Assistant highlights the University Application thread (Priority: `HIGH`, Status: `BLOCKED`).
* **Visual Telemetry:** Slide-out drawer visibly tags: **`MCP → discover_unfinished_threads`** and **`MCP → analyze_thread`**.
* **Action 2:** Click chip: **`Phase 2: Where did I leave off?`**.  
  *Visual:* Context card displays commitments, transcripts evidence, and active blocker (`dep-rec-letter`).

---

### Segment 3: Intent Intelligence — Why Now & Radar (0:48–1:15)
*Target Recording Window: 27 seconds · 55 spoken words*

#### Spoken Narration
> "Threadback doesn't just sort tasks—it explains them.  
> On the Intent Intelligence radar, Threadback separates deadline urgency from attention need. It provides explainable 'Why Now' reasoning: this application has an impending deadline and an active external dependency. It also diffs what changed since yesterday, flags cross-thread conflicts, and identifies whether stalled intentions have become resumable."

#### On-Screen Visual Action (Visual-Only)
* **Action:** Click navigation tab: **`Intent Intelligence`**.
* **Visual:** The proactive dashboard populates:
  * **Attention Radar**: University Application ranked at `CRITICAL` attention.
  * **Urgency vs. Attention Matrix**: Visual score gauges contrasting urgency (0.85) and attention (0.95).
  * **Why Now Explanation**: Highlight badge: *"Impending deadline in 5 days; stalled on external blocker (Professor recommendation letter)."*
  * **Multi-Horizon Change Diff**: Shows recent changes and unblocked status.

---

### Segment 4: Intent Copilot — What-If & Time Budget (1:15–1:45)
*Target Recording Window: 30 seconds · 57 spoken words*

#### Spoken Narration
> "With the Intent Copilot, you can explore decisions before committing.  
> Asking *'What if I postpone this?'* triggers a counterfactual simulation. Look at the badge: `SIMULATION — NO STATE CHANGED`. It projects downstream consequences with zero database mutation.  
> Asking *'I have 30 minutes'* allocates a focused time-budget plan, recommending the single highest-leverage action to move forward."

#### On-Screen Visual Action (Visual-Only)
* **Action 1:** Switch to **`Intent Copilot`** tab or click chip: **`🔮 What if I postpone it?`**.  
  *Visual:* Consequence breakdown card appears.
* **On-Screen Badge Highlight:** Prominently displays: **`🔮 SIMULATION — NO STATE CHANGED`** (zero database mutation guarantee).
* **Action 2:** Click chip: **`⏱️ I have 30 minutes`**.  
  *Visual:* Time budget allocation card renders 15-minute follow-up action.

---

### Segment 5: Safe Action Execution & Confirmation Gate (1:45–2:15)
*Target Recording Window: 30 seconds · 63 spoken words*

#### Spoken Narration
> "When ready to act, asking *'Help me finish it'* activates Threadback's safety gate.  
> Execution pauses, preparing a structured proposal that requires explicit confirmation. Ambiguous replies like 'sounds good' are rejected.  
> Once confirmed with *'Yes, go ahead'*, Threadback executes under `SIMULATED EXTERNAL ACTION`. No real email was sent; the simulated inquiry is safely logged while the intention remains open in persistent memory."

#### On-Screen Visual Action (Visual-Only)
* **Action 1:** Click chip: **`Phase 5: Prepare Action`** (*"Help me finish it."*).  
  *Visual:* `ActionProposal` card renders (`proposal-uni-follow-up-1`, Risk: `MEDIUM`). Status: `CONFIRMATION REQUIRED`. Execution pauses.
* **Action 2:** Click chip: **`Phase 6: Confirm Action`** (*"Yes, go ahead."*).  
  *Visual Telemetry:* Telemetry drawer tags: **`MCP → execute_action`**.
* **On-Screen Badge Highlight:** Prominently displays: **`⚡ SIMULATED ACTION EXECUTED (SIMULATED ACTION ≠ COMPLETION)`**. Thread status remains `BLOCKED`.

---

### Segment 6: Deterministic Verification & Safe Closure (2:15–2:38)
*Target Recording Window: 23 seconds · 51 spoken words*

#### Spoken Narration
> "Here is our core trust boundary: **Execution success does not equal completion.**  
> Later, independent evidence arrives from the admissions portal.  
> Asking *'Is it actually finished?'* invokes deterministic verification. Rule D validates the proof.  
> Only after verified evidence can the user close the thread, safely completing the open loop."

#### On-Screen Visual Action (Visual-Only)
* **Visual Context:** Factual portal evidence arrives in memory (`"Recommendation letter received via Admissions Portal"`).
* **Action 1:** Click chip: **`Phase 8: Verify Completion`** (*"Is it actually finished?"*).  
  *Visual:* Badge displays: **`🔍 DETERMINISTIC VERIFICATION: VERIFIED (Rule D satisfied)`**.
* **Action 2:** Click chip: **`Phase 9: Close Thread`** (*"Close it."*).  
  *Visual:* Status transitions to **`🏁 INTENT THREAD COMPLETED`**. The 10-step Chronological Lifecycle timeline appears on screen.

---

### Segment 7: Required Track Callout & Closing (2:38–2:50)
*Target Recording Window: 12 seconds · 31 spoken words*

#### Spoken Narration
> "Threadback is built around the Model Context Protocol, exposing exactly nine canonical tools over Streamable HTTP at `/mcp`, using protocol version `2025-11-25`.  
> Threadback turns forgotten intentions into explainable, verified progress."

#### On-Screen Visual Action (Visual-Only)
* **Visual:** Pan/zoom to the live **MCP Activity Drawer** showing:
  * Protocol: `2025-11-25`
  * Transport: `Streamable HTTP`
  * Endpoint: `/mcp`
  * Advertised Tools: Exactly 9 canonical domain tools.

---

### Segment 8: Visual Closing & Safety Buffer (2:50–3:00)
*Target Recording Window: 10 seconds · 0 spoken words*

#### On-Screen Visual Action (Visual-Only)
* **Closing Title Card:** Threadback Logo · *"People don't forget tasks. They forget intentions."* · Built for AWS Hackathon / Alexa+ Track · GitHub Repository link.
* **Music / Ambient Fade:** 5–10 seconds of safety margin ensuring clean video cutoff before 3:00.

---

## 4. Technical Invariants & Claim Boundaries

1. **Required Track Technology**:
   * Model Context Protocol (MCP) protocol `2025-11-25` over Streamable HTTP at `/mcp` with 9 canonical tools.
2. **Three Core Safety Pillars**:
   * **`SIMULATED EXTERNAL ACTION`**: Operational actions (emails, applications) are simulated and audit-logged; zero external side effects occur.
   * **`PERSISTENT THREADBACK MUTATION`**: Internal state mutations persist durably to SQLite via domain services only after explicit user confirmation.
   * **`VERIFIED COMPLETION`**: `EXECUTION_SUCCESS ≠ COMPLETION`. Completion is strictly verification-gated by deterministic evidence rules.
3. **Truthful Boundary Claims**:
   * Local MCP server and conversational parity are **Verified Working**.
   * Amazon Bedrock + Strands provider is **Integration-Ready**.
   * Amazon Bedrock AgentCore deployment is **Integration-Ready (Cloud Provisioning Blocked by Sandbox IAM `ViewOnlyAccess`)**.
   * Amazon Alexa+ Add-on is **Integration-Ready (Pending Partner Toolkit Access)**.
   * Zero claims of live cloud registry deployment, live Echo hardware testing, or real email/SMS dispatch.

---

## 5. 1-Click Demo Reset (For Evaluator Retesting)

To reset the scenario to its initial state for a fresh recording take:
1. Click the **`Reset Demo`** button in the top navigation bar, or
2. Send: `curl -X POST http://localhost:8000/api/agent/demo-reset -H "Content-Type: application/json" -d '{"conversation_id": "session-default"}'`.
