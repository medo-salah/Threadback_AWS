import React, { useEffect, useRef, useState } from 'react'
import './App.css'

interface ToolActivity {
  tool_name: string
  summary: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  pendingConfirmation?: boolean
  proposalId?: string | null
  threadId?: string | null
  activities?: ToolActivity[]
  executionStatus?: string | null
  executionMode?: string | null
  timestamp: string
}

const DEMO_PROMPTS = [
  { label: 'Phase 1: What am I forgetting?', prompt: 'What am I forgetting?' },
  { label: 'Phase 2: Where did I leave off?', prompt: 'Where did I leave off?' },
  { label: 'Phase 3: Blocker Check', prompt: "Why haven't I finished it?" },
  { label: 'Phase 4: Next Action', prompt: 'What should I do?' },
  { label: 'Phase 5: Prepare Action', prompt: 'Help me finish it.' },
  { label: 'Phase 6: Confirm Action', prompt: 'Yes, go ahead.' },
  { label: 'Phase 8: Verify Completion', prompt: 'Is it actually finished?' },
  { label: 'Phase 9: Close Thread', prompt: 'Close it.' },
]

const MILESTONES = [
  { id: 'm0', label: 'M0 — Product Specification', status: 'done' },
  { id: 'm1', label: 'M1 — Repository & Dev Foundation', status: 'done' },
  { id: 'm2', label: 'M2 — MCP Server Foundation', status: 'done' },
  { id: 'm3', label: 'M3 — Thread Domain & Database', status: 'done' },
  { id: 'm4', label: 'M4 — Intent & Evidence Engine', status: 'done' },
  { id: 'm5', label: 'M5 — Next Action Engine', status: 'done' },
  { id: 'm6', label: 'M6 — Action Preparation & Confirmation', status: 'done' },
  { id: 'm7', label: 'M7 — Controlled Action Execution', status: 'done' },
  { id: 'm8', label: 'M8 — Agent Intelligence & MCP Orchestration', status: 'done' },
  { id: 'm9', label: 'M9 — Remote Bedrock AgentCore & Alexa+ MCP', status: 'done' },
  { id: 'm10', label: 'M10 — Intent Memory & Lifecycle Closure', status: 'done' },
  { id: 'm11', label: 'M11 — Alexa+ Experience & Hackathon Readiness', status: 'done' },
  { id: 'm12', label: 'M12 — Final Hackathon Demo & Submission Readiness', status: 'current' },
] as const

let messageCounter = 0
function nextMessageId(prefix: string): string {
  messageCounter += 1
  return `${prefix}-${messageCounter}`
}

function getTimestamp(): string {
  const d = new Date()
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

/**
 * Renders user-facing message text with clean formatting:
 * - Unescapes literal backslash escapes (e.g., \*\* -> **)
 * - Parses **bold** segments into <strong> elements
 * - Parses `code` segments into <code> elements
 * - Preserves line breaks
 */
function renderFormattedContent(rawContent: string): React.ReactNode {
  if (!rawContent) return null

  // Unescape backslash-escaped markdown characters
  const content = rawContent.replace(/\\\*/g, '*').replace(/\\`/g, '`')
  const lines = content.split('\n')

  return lines.map((line, lineIdx) => {
    if (!line.includes('**') && !line.includes('`')) {
      return (
        <span key={lineIdx} className="message-line">
          {line}
          {lineIdx < lines.length - 1 && '\n'}
        </span>
      )
    }

    const parts: React.ReactNode[] = []
    const regex = /(\*\*.*?\*\*|`.*?`)/g
    let match: RegExpExecArray | null
    let lastIndex = 0
    let tokenIndex = 0

    while ((match = regex.exec(line)) !== null) {
      if (match.index > lastIndex) {
        parts.push(line.substring(lastIndex, match.index))
      }
      const token = match[0]
      if (token.startsWith('**') && token.endsWith('**')) {
        parts.push(
          <strong key={`${lineIdx}-${tokenIndex++}`}>
            {token.slice(2, -2)}
          </strong>
        )
      } else if (token.startsWith('`') && token.endsWith('`')) {
        parts.push(
          <code key={`${lineIdx}-${tokenIndex++}`} className="inline-code">
            {token.slice(1, -1)}
          </code>
        )
      }
      lastIndex = regex.lastIndex
    }

    if (lastIndex < line.length) {
      parts.push(line.substring(lastIndex))
    }

    return (
      <span key={lineIdx} className="message-line">
        {parts}
        {lineIdx < lines.length - 1 && '\n'}
      </span>
    )
  })
}

function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        'Hello! I am **Threadback**, your personal intent-recovery agent. I can help you discover forgotten intentions, understand unfinished commitments, identify blockers, and safely prepare or simulate actions.\n\nTry asking me what you are forgetting, or select one of the demo scenarios below.',
      timestamp: getTimestamp(),
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [currentActivity, setCurrentActivity] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string>('session-default')
  const [pendingProposalId, setPendingProposalId] = useState<string | null>(null)
  const [agentProvider, setAgentProvider] = useState<string>('mock')
  const [showMilestones, setShowMilestones] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Check agent backend configuration
    fetch('/api/agent/info')
      .then((res) => res.json())
      .then((data) => {
        if (data.provider) setAgentProvider(data.provider)
      })
      .catch(() => {
        // Fallback for direct backend or dev server
      })
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, currentActivity])

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return

    const userMsg: Message = {
      id: nextMessageId('user'),
      role: 'user',
      content: text.trim(),
      timestamp: getTimestamp(),
    }

    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)

    // Set initial activity state
    if (pendingProposalId && (text.toLowerCase().includes('yes') || text.toLowerCase().includes('ahead') || text.toLowerCase().includes('proceed'))) {
      setCurrentActivity('Executing simulation via MCP execute_action...')
    } else if (text.toLowerCase().includes('finish') || text.toLowerCase().includes('help')) {
      setCurrentActivity('Preparing action via MCP prepare_action...')
    } else {
      setCurrentActivity('Using Threadback tools over Streamable HTTP...')
    }

    try {
      const res = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text.trim(),
          conversation_id: conversationId,
        }),
      })

      if (!res.ok) {
        throw new Error(`Server returned status ${res.status}`)
      }

      const data = await res.json()

      if (data.conversation_id) {
        setConversationId(data.conversation_id)
      }

      if (data.pending_confirmation && data.proposal_id) {
        setPendingProposalId(data.proposal_id)
      } else {
        setPendingProposalId(null)
      }

      const assistantMsg: Message = {
        id: nextMessageId('assistant'),
        role: 'assistant',
        content: data.message,
        pendingConfirmation: data.pending_confirmation,
        proposalId: data.proposal_id,
        threadId: data.thread_id,
        activities: data.activities,
        executionStatus: data.execution_status,
        executionMode: data.execution_mode,
        timestamp: getTimestamp(),
      }

      setMessages((prev) => [...prev, assistantMsg])
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      setMessages((prev) => [
        ...prev,
        {
          id: nextMessageId('error'),
          role: 'assistant',
          content: `⚠️ Could not reach Threadback Agent: ${errorMsg}. Please ensure the backend is running at http://localhost:8000.`,
          timestamp: getTimestamp(),
        },
      ])
    } finally {
      setIsLoading(false)
      setCurrentActivity(null)
    }
  }

  const handleReset = async () => {
    try {
      await fetch('/api/agent/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          reset_demo_state: true,
        }),
      })
    } catch {
      // Ignore network errors on reset
    }
    setPendingProposalId(null)
    setMessages([
      {
        id: nextMessageId('reset-welcome'),
        role: 'assistant',
        content:
          'Demo reset complete. Canonical University Application scenario reinitialized in persistent SQLite. What intention would you like to review?',
        timestamp: getTimestamp(),
      },
    ])
  }

  return (
    <div className="app">
      {/* Ambient background glow */}
      <div className="app-background" aria-hidden="true" />

      {/* Header */}
      <header className="header" role="banner">
        <div className="header-logo">
          <div className="logo-mark" aria-hidden="true">
            🧵
          </div>
          <div className="logo-text-group">
            <span className="logo-name">Threadback</span>
            <span className="logo-subtitle">Intent Recovery Agent</span>
          </div>
        </div>

        <div className="header-controls">
          <span className="provider-badge" title="Active Model Provider">
            <span className="provider-dot" />
            Provider: <strong>{agentProvider.toUpperCase()}</strong>
          </span>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => setShowMilestones(!showMilestones)}
          >
            {showMilestones ? 'Hide Milestones' : 'Milestones'}
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={handleReset}
            title="Reset conversation state and restore canonical University Application demo data in SQLite"
          >
            Reset Demo
          </button>
          <span className="header-badge" aria-label="Development status">
            M12 Hackathon Ready
          </span>
        </div>
      </header>

      {/* Milestones Drawer */}
      {showMilestones && (
        <section className="milestones-drawer" aria-label="Milestone Progress">
          <div className="drawer-header">
            <h4>System Architecture &amp; Milestones</h4>
            <span className="drawer-close" onClick={() => setShowMilestones(false)}>
              ✕
            </span>
          </div>
          <div className="milestone-grid">
            {MILESTONES.map((m) => (
              <div
                key={m.id}
                className={`milestone-tile ${
                  m.status === 'done'
                    ? 'milestone-tile--done'
                    : m.status === 'current'
                      ? 'milestone-tile--current'
                      : ''
                }`}
              >
                <span className="tile-check">{m.status === 'done' ? '✓' : '▶'}</span>
                <span className="tile-label">{m.label}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Main chat container */}
      <main className="chat-container" id="main-content" role="main">
        {/* Suggestion Chips */}
        <div className="demo-chips-container" aria-label="Quick demo scenarios">
          <span className="chips-label">Demo Scenarios:</span>
          {DEMO_PROMPTS.map((item) => (
            <button
              key={item.label}
              type="button"
              className="chip-btn"
              disabled={isLoading}
              onClick={() => sendMessage(item.prompt)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Message Stream */}
        <div className="messages-stream" role="log" aria-live="polite">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-row ${
                msg.role === 'user' ? 'message-row--user' : 'message-row--assistant'
              }`}
            >
              {msg.role === 'assistant' && (
                <div className="message-avatar" aria-hidden="true">
                  🧵
                </div>
              )}

              <div className="message-bubble-wrapper">
                <div
                  className={`message-bubble ${
                    msg.role === 'user' ? 'message-bubble--user' : 'message-bubble--assistant'
                  }`}
                >
                  <div className="message-text">{renderFormattedContent(msg.content)}</div>
                </div>

                {/* Tool Activity Indicators — Rendered as a separate structured activity container */}
                {msg.activities && msg.activities.length > 0 && (
                  <div className="tool-activities-box" aria-label="MCP Tool Activity">
                    <div className="activities-header">
                      <span className="activity-badge-dot" aria-hidden="true" />
                      <span className="activities-title">Activity · MCP Tools Orchestrated</span>
                    </div>
                    <div className="activities-list">
                      {msg.activities.map((act, idx) => (
                        <div key={idx} className="activity-item">
                          <span className="activity-tool-tag">MCP → {act.tool_name}</span>
                          <span className="activity-summary">{act.summary}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Execution Mode Notice */}
                {msg.executionMode === 'SIMULATED' && (
                  <div className="simulation-badge">
                    ⚡ <strong>SIMULATED ACTION EXECUTED</strong> · Action was executed in simulation mode. Intention remains UNFINISHED until independent evidence is verified (<strong>SIMULATED ACTION ≠ VERIFIED COMPLETION</strong>).
                  </div>
                )}

                {/* Verification Status Notice */}
                {(msg.content.includes('VERIFIED') || msg.content.includes('Verification Status:')) && (
                  <div className="verification-badge">
                    🔍 <strong>DETERMINISTIC VERIFICATION</strong> · Evaluated factual evidence against domain closure rules (<strong>VERIFIED → CLOSED → COMPLETED</strong>).
                  </div>
                )}

                {/* Lifecycle Completion Notice & History */}
                {(msg.content.includes('thread is complete') || msg.content.includes('lifecycle loop for this intention is now successfully closed')) && (
                  <>
                    <div className="completion-badge">
                      🏁 <strong>INTENT THREAD COMPLETED</strong>
                      <span>Deterministic verification succeeded. Thread transition persisted in memory.</span>
                    </div>
                    <div className="thread-history-card">
                      <div className="history-card-title">Chronological Lifecycle Memory</div>
                      <div className="history-timeline">
                        <div className="history-item"><span className="history-check">✓</span> 1. Intent Discovered</div>
                        <div className="history-item"><span className="history-check">✓</span> 2. Context Reconstructed</div>
                        <div className="history-item"><span className="history-check">✓</span> 3. Blocker Identified (Recommendation letter)</div>
                        <div className="history-item"><span className="history-check">✓</span> 4. Next Action Suggested</div>
                        <div className="history-item"><span className="history-check">✓</span> 5. Action Proposal Prepared</div>
                        <div className="history-item"><span className="history-check">✓</span> 6. Explicit Confirmation Validated</div>
                        <div className="history-item history-item--sim"><span className="history-check">⚡</span> 7. Action Simulated (SIMULATED ACTION ≠ VERIFIED COMPLETION)</div>
                        <div className="history-item"><span className="history-check">✓</span> 8. Factual Evidence Received</div>
                        <div className="history-item history-item--verify"><span className="history-check">🔍</span> 9. Completion Deterministically Verified</div>
                        <div className="history-item history-item--close"><span className="history-check">🏁</span> 10. Thread Closed &amp; Completed</div>
                      </div>
                    </div>
                  </>
                )}

                {/* Confirmation Request Card */}
                {msg.pendingConfirmation && msg.proposalId && (
                  <div className="confirmation-card">
                    <div className="confirmation-card-header">
                      <span className="confirmation-card-title">⚠️ Confirmation Required</span>
                      <code className="proposal-tag">{msg.proposalId}</code>
                    </div>
                    <p className="confirmation-card-desc">
                      Threadback has prepared this action. Execution will be strictly <strong>SIMULATED</strong> (no external emails, calls, or actions).
                    </p>
                    <div className="confirmation-actions">
                      <button
                        type="button"
                        className="confirm-btn"
                        disabled={isLoading}
                        onClick={() => sendMessage('Yes, go ahead.')}
                      >
                        Confirm &amp; Execute Simulation
                      </button>
                      <button
                        type="button"
                        className="cancel-btn"
                        disabled={isLoading}
                        onClick={() => sendMessage('Cancel')}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
                <span className="message-timestamp">{msg.timestamp}</span>
              </div>
            </div>
          ))}

          {/* Loading / Activity Indicator */}
          {isLoading && (
            <div className="message-row message-row--assistant">
              <div className="message-avatar" aria-hidden="true">
                🧵
              </div>
              <div className="message-bubble message-bubble--assistant message-bubble--thinking">
                <div className="thinking-indicator">
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </div>
                <span className="thinking-label">{currentActivity || 'Thinking...'}</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <form
          className="chat-input-bar"
          onSubmit={(e) => {
            e.preventDefault()
            sendMessage(input)
          }}
        >
          <input
            type="text"
            className="chat-input"
            value={input}
            disabled={isLoading}
            placeholder={
              pendingProposalId
                ? "Reply 'Yes' or 'Go ahead' to confirm simulation..."
                : "Ask Threadback about your forgotten intentions, blockers, or next actions..."
            }
            onChange={(e) => setInput(e.target.value)}
          />
          <button
            type="submit"
            className="send-btn"
            disabled={!input.trim() || isLoading}
            aria-label="Send message"
          >
            Send
          </button>
        </form>
      </main>

      {/* Footer */}
      <footer className="footer" role="contentinfo">
        <span>Threadback M12</span>
        <span className="footer-divider" aria-hidden="true">·</span>
        <span>Hackathon Demo &amp; Submission Ready</span>
        <span className="footer-divider" aria-hidden="true">·</span>
        <span>MCP Streamable HTTP</span>
        <span className="footer-divider" aria-hidden="true">·</span>
        <span>Strict SIMULATED Execution Boundary</span>
      </footer>
    </div>
  )
}

export default App
