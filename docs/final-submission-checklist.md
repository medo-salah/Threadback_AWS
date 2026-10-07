# Threadback — Final Hackathon Submission Checklist

This checklist documents the final audit and verification gate for Threadback prior to hackathon submission.

---

## 1. Submission

- [ ] **Project name**: "Threadback" (clean name without generic subtitles)
- [ ] **Elevator pitch**: Intention recovery vs. task checklists, context reconstruction, explainable next actions, proactive/counterfactual intelligence
- [ ] **About/project description**: Comprehensive 10-point description covering problem, solution, 9-stage lifecycle, M13–M15 capabilities, MCP architecture, safety pillars, hackathon updates, and honest boundaries
- [ ] **Built With**: Concise list (MCP, Python MCP SDK, Streamable HTTP, Bedrock, Strands Agents, Boto3, FastAPI, SQLite, React, TypeScript, Vite, Docker)
- [ ] **Primary track: Alexa+**: Self-hosted MCP server with 9 canonical tools over Streamable HTTP on protocol `2025-11-25` at `/mcp`
- [ ] **AWS Builder mini challenge decision**: Documented as **QUALIFIES (Integration-Ready)** based on Bedrock provider architecture, Strands Agents SDK integration, Boto3 integration, and AgentCore ARM64 container packaging
- [ ] **Open Source mini challenge decision**: Documented as **DOES NOT QUALIFY / EVIDENCE NOT FOUND** (no qualifying separate open-source contribution or secondary repository created during hackathon window)
- [ ] **GitHub repository URL**: `https://github.com/medo-salah/Threadback_AWS` (includes MIT License, source code, setup/run instructions, sanitized `.env.example`)
- [ ] **Demo video URL**: Dedicated demo video URL (under 3 minutes) uploaded and linked on Devpost
- [ ] **Product feedback**: Complete 5-question technical feedback provided for all 4 tools/SDKs used (Python MCP SDK, Strands Agents, Amazon Bedrock / Boto3, AgentCore Packaging)
- [ ] **Significant-update explanation**: Section "What We Built During the Hackathon" clearly contrasting M0–M12 foundation with M13–M16 advanced additions

---

## 2. Technical

- [x] **MCP server working**: Local MCP server verified and tested via automated test suite and live endpoints
- [x] **`/mcp` endpoint**: Hosted and tested at `/mcp`
- [x] **Streamable HTTP transport**: Fully functional stateless Streamable HTTP transport
- [x] **MCP protocol `2025-11-25`**: Native compliance with MCP protocol version `2025-11-25`
- [x] **9 canonical tools**: Exactly 9 tools advertised at `/mcp` (zero extraneous or omitted tools)
- [x] **401 tests passing**: 401 / 401 automated tests passing (100% green across M0–M15)
- [x] **Frontend build clean**: `npm run build` compiles clean production bundle with zero TypeScript errors
- [x] **Ruff clean**: `ruff check` (0 errors) and `ruff format --check` (0 deviations) across all 87 files
- [x] **No secrets committed**: No `.env` credentials, API keys, or temporary database files committed

---

## 3. Video

- [x] **<3 minutes**: Spoken script strictly calibrated at 371 words (2:44–2:55 total duration at 135–145 WPM with 10s visual pauses; 5–16s safety margin before 3:00 cutoff)
- [x] **English narration**: High-impact English voiceover and visual titles
- [ ] **Public YouTube/Vimeo**: Video uploaded and set to public or unlisted with embed permissions
- [x] **No unlicensed music/third-party material**: UI-only visuals, synthetic/original audio, zero copyrighted third-party assets
- [x] **Working product visibly demonstrated**: 9-stage lifecycle, pronoun resolution, Attention Radar, counterfactual simulation, confirmation gating, verification proof, and closure shown in action
- [x] **MCP clearly visible**: Live MCP Activity Drawer visibly displaying `/mcp`, Streamable HTTP, Protocol `2025-11-25`, and 9 canonical tools

---

## 4. Claims & Truthful Boundaries

- [x] **No live AgentCore claim**: Truthfully documented as **Integration-Ready (Cloud Provisioning Blocked by Sandbox IAM `ViewOnlyAccess`)**
- [x] **No published Alexa+ claim**: Truthfully documented as **Integration-Ready (Pending Partner Toolkit Access)**; positioned on approved self-hosted MCP server path
- [x] **No Echo hardware claim**: Evaluator-ready web interface demonstrated; no false physical hardware claims
- [x] **No real external-action claim**: Operational actions explicitly badged as **`SIMULATED EXTERNAL ACTION`**; zero external emails, SMS, or API side effects dispatched
- [x] **No autonomous-completion claim**: Invariant strictly enforced: **`EXECUTION_SUCCESS ≠ COMPLETION`**; completion requires deterministic Rule A–E verification
