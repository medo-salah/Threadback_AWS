# Threadback — Milestone M8: Agent Intelligence & MCP Orchestration

## 1. M8 Architecture

Milestone M8 introduces the conversational agent layer for Threadback. Built on the authoritative, deterministic foundation of M0–M7, the agent acts as an **orchestrator**, translating natural language user intent into precise Model Context Protocol (MCP) tool invocations and synthesizing natural language answers.

```text
User / Frontend
      ↓  (HTTP / WebSocket)
FastAPI Agent API (/api/agent/chat)
      ↓
AgentService
      ↓
ConversationManager (Ephemeral in-memory state)
      ↓
ModelProvider Abstraction (Mock | Bedrock)
      ↓
Strands Agent + MCPClient  /  Deterministic Mock Provider
      ↓  (Streamable HTTP, protocol 2025-11-25)
Threadback MCP Server (/mcp)
      ↓
Deterministic Engine (M3–M7)
  ├── M3: ThreadDomain & Datastore
  ├── M4: Intent & Evidence Engine
  ├── M5: Next Action Engine
  ├── M6: Action Preparation & Confirmation
  └── M7: Controlled Action Execution (SIMULATED)
```

The critical architectural principle: **The LLM/agent is an orchestrator, NOT the source of truth.** The deterministic Threadback engine remains authoritative. The agent never manufactures, hallucinates, or extrapolates domain facts.

### Workflow Evolution
- **Current M8 Workflow (Implemented)**:
  `Discover → Understand → Prioritize → Prepare → Confirm → Simulate`
- **Future Product Workflow (Vision)**:
  `Discover → Understand → Prioritize → Prepare → Confirm → Act → Verify → Close`

---

## 2. Agent Responsibilities

The Threadback Agent is tasked with:
1. **Understanding Natural Language**: Interpreting user inquiries regarding forgotten intentions, commitments, blockers, and next steps.
2. **Discovering Intent Threads**: Querying MCP `discover_unfinished_threads` with semantic or priority filters.
3. **Context Reconstruction**: Retrieving full history, commitments, evidence items, and dependencies via `get_thread_context`.
4. **Analyzing Thread Status**: Evaluating attention levels, confidence bands, and root reasons via `analyze_thread`.
5. **Identifying Blockers**: Pinpointing blocking dependencies via `find_thread_blockers`.
6. **Recommending Next Actions**: Determining deterministic next actions via `suggest_next_action`.
7. **Action Preparation**: Generating reviewable `ActionProposal`s via `prepare_action`.
8. **Confirmation Protocol Enforcement**: Stopping execution when `requires_confirmation = True` and requesting explicit authorization.
9. **Controlled Execution**: Executing actions only via MCP `execute_action` with `confirmed = True` and `execution_mode = "SIMULATED"`.
10. **Truthful Explanation**: Faithfully reporting results, explicitly emphasizing that execution was simulated without external side effects.

---

## 3. MCP Boundary

The agent communicates with Threadback strictly across the Model Context Protocol (MCP) Streamable HTTP boundary at `http://localhost:8000/mcp`.

**The agent never directly imports or executes domain services as its primary tool-use mechanism.**

Exposed MCP Tools:
| Tool Name | Purpose | Output |
| :--- | :--- | :--- |
| `discover_unfinished_threads` | List open intent threads | `threads: list[ThreadSummary]` |
| `get_thread_context` | Retrieve full context for a thread | `IntentThread` + commitments, evidence, deps |
| `find_thread_blockers` | Find blocking dependencies | `blocking_status`, `blockers: list[BlockerDetail]` |
| `analyze_thread` | Evaluate status, confidence, attention | `ThreadAnalysis` |
| `suggest_next_action` | Deterministic next action | `NextActionSuggestion` |
| `prepare_action` | Prepare reviewable proposal | `ActionProposal` |
| `execute_action` | Execute proposal in SIMULATED mode | `ExecutionResult` (audit event) |

---

## 4. Model Provider Abstraction

Threadback avoids vendor lock-in and enables deterministic testing through a provider abstraction (`ModelProvider` in `app.agent.providers.base`):

```python
class ModelProvider(ABC):
    @abstractmethod
    async def process_message(
        self,
        user_message: str,
        session: ConversationSession,
        mcp_client: ThreadbackMCPClient,
    ) -> AgentChatResponse:
        ...
```

Configured via the environment variable:
```bash
THREADBACK_AGENT_PROVIDER=mock      # Deterministic, zero-credential CI/local mode
# or
THREADBACK_AGENT_PROVIDER=bedrock   # Live AWS Bedrock runtime via Strands Agents
```

---

## 5. Amazon Bedrock Integration

When `THREADBACK_AGENT_PROVIDER=bedrock`, Threadback initializes the Bedrock provider (`BedrockModelProvider`):
- Uses AWS SDK (`boto3`) session management.
- Targets Anthropic Claude models on Bedrock (default: `anthropic.claude-3-5-sonnet-20241022-v2:0`).
- Validates required configuration (`AWS_REGION`, `BEDROCK_MODEL_ID`, credentials) at startup.
- Never commits or logs credentials, secrets, or sensitive session keys.
- Raises explicit `BedrockConfigurationError` or `BedrockRuntimeError` when configuration is missing or unreachable.

---

## 6. Strands Agents Integration

The live Bedrock mode utilizes **Strands Agents** (`strands-agents`):
- Connects the model to the MCP server via `strands.tools.mcp.MCPClient(url=settings.threadback_mcp_url)`.
- Tools are loaded dynamically over Streamable HTTP per protocol specification `2025-11-25`.
- Injects `THREADBACK_SYSTEM_PROMPT` to enforce truthfulness, confirmation discipline, and simulation boundaries.

```python
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

model = BedrockModel(model_id=settings.bedrock_model_id, region_name=settings.aws_region)
mcp_client = MCPClient(url=settings.threadback_mcp_url)

agent = Agent(
    model=model,
    tools=[mcp_client],
    system_prompt=THREADBACK_SYSTEM_PROMPT,
)
```

---

## 7. Confirmation Protocol

To protect user safety and prevent unauthorized operations:
1. When `prepare_action` produces a proposal with `requires_confirmation = True`, the agent **must stop**.
2. The agent stores the pending proposal ID in the conversation state (`pending_proposal_id`, `pending_confirmation = True`).
3. The response clearly presents:
   - What action was prepared;
   - Which thread is affected;
   - That execution is strictly **SIMULATED**;
   - The exact proposal ID.
4. **Ambiguous responses do NOT authorize execution**:
   - Phrases like *"maybe"*, *"what would happen?"*, *"tell me more"*, or *"sounds good"* are flagged as ambiguous.
   - The agent reiterates that explicit authorization is required and does not execute.
5. **Only explicit affirmations authorize execution**:
   - Phrases like *"Yes"*, *"Yes, do it"*, *"Go ahead"*, *"Execute it"*, or *"Proceed"* trigger `execute_action`.
   - The proposal ID is passed exactly without alterations.
   - If an affirmative response is sent when NO proposal is pending, execution is refused.

---

## 8. Ephemeral Conversation State

Conversation state (`ConversationManager` and `ConversationSession`):
- Stored purely in-memory.
- Resets on server restart.
- Tracks:
  - `conversation_id: str`
  - `messages: list[ChatMessage]`
  - `pending_proposal_id: str | None`
  - `pending_thread_id: str | None`
  - `pending_confirmation: bool`
- Provides an endpoint `POST /api/agent/reset` to clear session state on demand.
- **No external persistent database (PostgreSQL, Redis, etc.) is used or required for conversation state in M8.**

---

## 9. Deterministic Mock Mode

`MockModelProvider` provides deterministic, credential-free orchestration for CI, automated testing, and development without AWS accounts:
- Connects directly to the real Streamable HTTP MCP server at `http://localhost:8000/mcp`.
- Translates intents into real MCP tool calls:
  - *"What am I forgetting?"* → `discover_unfinished_threads` + `analyze_thread`
  - *"Where did I leave off...?"* → `discover_unfinished_threads` + `get_thread_context` + `analyze_thread`
  - *"Help me finish..."* → `suggest_next_action` + `prepare_action`
  - *"Yes, go ahead"* → `execute_action`
- Enforces all safety, confirmation, and formatting rules identical to the live LLM.

---

## 10. Frontend Agent Flow

The frontend (`frontend/src/App.tsx`) provides an interactive interface:
- **Interactive Chat Stream**: User prompts and assistant responses.
- **Activity Badges**: Real-time display of MCP tools invoked (e.g. `discover_unfinished_threads`, `prepare_action`).
- **Confirmation Prompt Cards**: Visual confirmation dialogue displaying the exact proposal ID, simulated notice, and "Confirm Simulation" button.
- **Simulation Badges**: Highlighted indicators verifying that executed actions created audit events without real-world side effects.
- **Demo Prompt Chips**: Instant buttons for Demo A, Demo B, Demo C, Blocker Check, and Next Action.

---

## 11. Safety Boundaries

Threadback adheres to strict non-external execution constraints:
- `execute_action` is hardwired to `execution_mode = "SIMULATED"`.
- The system never sends emails, SMS, or WhatsApp messages.
- The system never places telephone calls or books calendar appointments.
- The system never submits forms, invokes webhooks, or initiates external network actions.
- Audit records (`Event` domain model) log all simulated executions deterministically.

---

## 12. Local Setup & Running

### Prerequisites
- Python 3.10+
- Node.js 18+

### 1. Setup Backend
```bash
cd backend
source .venv/bin/activate
pip install -e .
```

### 2. Run Backend MCP & Agent Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Endpoints active:
- `GET /health` — Health check
- `POST /mcp` — Streamable HTTP MCP endpoint (tools, resources)
- `POST /api/agent/chat` — Agent chat endpoint
- `POST /api/agent/reset` — Session reset endpoint

### 3. Run Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` to interact with Threadback.

---

## 13. Bedrock Configuration

To enable Amazon Bedrock:
1. Ensure your AWS credentials are configured (e.g., via `~/.aws/credentials` or environment variables):
   ```bash
   export AWS_REGION=us-east-1
   export AWS_ACCESS_KEY_ID=AKIA...
   export AWS_SECRET_ACCESS_KEY=...
   ```
2. Set agent provider and Bedrock model ID in `.env`:
   ```bash
   THREADBACK_AGENT_PROVIDER=bedrock
   # BEDROCK_MODEL_ID is fully configurable.
   # Note: Models must be enabled in your AWS Bedrock account and region.
   # Examples:
   #   BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
   #   BEDROCK_MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v2:0
   #   BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
   BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
   THREADBACK_MCP_URL=http://localhost:8000/mcp
   ```
   > **Note on Model Availability**: Model IDs are configurable examples rather than universal guarantees. Model access depends on your AWS account's enabled models in Amazon Bedrock. The agent will raise a clean `BedrockRuntimeError` / `BedrockConfigurationError` if the model or credentials cannot be accessed.

3. Restart the backend server.

---

## 14. Demo Scenarios

### Demo A — Discovery
- **User**: *"What am I forgetting?"*
- **Orchestration**: `discover_unfinished_threads` → `analyze_thread`
- **Response**: Explains unfinished intentions (e.g. University Application, Client Report, Dentist Appointment, AWS Hackathon), priorities, attention levels, and reasons for attention.

### Demo B — Context Reconstruction
- **User**: *"Where did I leave off with the university application?"*
- **Orchestration**: `discover_unfinished_threads` → `get_thread_context` → `analyze_thread`
- **Response**: Reconstructs current status (BLOCKED), open commitments, missing recommendation letter blocker, evidence history, and next recommended step. Populates `session.pending_thread_id` so subsequent commands can refer to the thread.

### Demo C — Controlled Action

**Decision Flow:**
The agent ensures the proposal strictly belongs to the thread the user is actually referring to:

```text
Known thread (e.g. session.pending_thread_id from prior turn)
    ↓
suggest_next_action
    ↓
prepare_action

Unknown thread (new request or specific topic specified)
    ↓
discover_unfinished_threads(query=...)
    ↓
get_thread_context
    ↓
suggest_next_action
    ↓
prepare_action
```

*Important Invariant*: The agent never operates on an arbitrary fallback thread. If a user asks for an unknown or nonexistent thread (e.g. *"Help me finish the spaceship project"*), the agent reports that no matching thread was found.

- **User**: *"Help me finish the application."*
- **Orchestration**: Resolves thread → `suggest_next_action` → `prepare_action`
- **Agent Action**: Halts execution, generates proposal `proposal-xxxx`, explains simulation constraints, and prompts for explicit confirmation.
- **User**: *"Yes, go ahead."*
- **Orchestration**: `execute_action(proposal_id=..., confirmed=True, execution_mode="SIMULATED")`
- **Response**: Confirms simulated execution, provides audit event ID, and reiterates that no real email was dispatched.

---

## 15. Future AgentCore Integration

In future milestones (post-M8), Threadback's agent orchestration layer can be deployed to AWS AgentCore:
- **AgentCore Runtime**: Deploying the Strands Agent container into the managed AWS AgentCore execution runtime.
- **AgentCore Gateway**: Exposing the MCP server tools through the AgentCore Gateway for enterprise service routing.
- **AgentCore Memory**: Augmenting ephemeral conversation state with durable, encrypted conversational history.
