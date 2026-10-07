import React, { useEffect, useRef, useState } from 'react'
import './App.css'

interface ToolActivity {
  tool_name: string
  summary: string
}

interface RadarItem {
  thread_id: string
  title: string
  urgency_score: number
  decay_state: string
  attention_level?: string
  explanation: string
  recommended_focus?: boolean
}

interface RadarReport {
  generated_at?: string
  active_threads_count?: number
  items?: RadarItem[]
  top_focus_thread_id?: string
  top_focus_reason?: string
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
  radarReport?: RadarReport | null
  diffSummary?: string | null
  timestamp: string
}

// ---------------------------------------------------------------------------
// M14 Proactive Intent Intelligence Types
// ---------------------------------------------------------------------------

interface AttentionCandidate {
  thread_id: string
  thread_title: string
  attention_level: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE'
  attention_score: number
  urgency_score: number
  reason_codes: string[]
  human_readable_explanation: string
  supporting_evidence_ids: string[]
  supporting_commitment_ids: string[]
  blocker_ids: string[]
  recommended_action_summary?: string | null
}

interface ResumableCandidate {
  thread_id: string
  thread_title: string
  eligibility: 'RESUMABLE' | 'NOT_RESUMABLE' | 'UNKNOWN'
  reason: string
  supporting_blocker_ids: string[]
  supporting_evidence_ids: string[]
  deferred_until?: string | null
}

interface IntentConflict {
  conflict_id: string
  thread_a_id: string
  thread_a_title: string
  thread_b_id: string
  thread_b_title: string
  conflict_type: string
  severity: string
  explanation: string
}

interface StateChangeItem {
  category: string
  description: string
  timestamp: string
}

interface AttentionDelta {
  thread_id: string
  thread_title: string
  changes: StateChangeItem[]
  significance_score: number
  significance_level: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
  reason_codes: string[]
}

interface IntentHealthSummary {
  total_active_threads: number
  healthy_threads: number
  attention_threads: number
  decaying_threads: number
  stale_threads: number
  blocked_threads: number
  deferred_threads: number
  resumable_threads: number
  conflicts_count: number
  top_attention_candidates: AttentionCandidate[]
}

interface ProactiveBriefing {
  top_attention: AttentionCandidate[]
  top_changes: AttentionDelta[]
  top_resumable: ResumableCandidate[]
  top_conflicts: IntentConflict[]
  health_summary: IntentHealthSummary
  briefing_text: string
  generated_at: string
}

// ---------------------------------------------------------------------------
// M15 Proactive Agent Experience & Intent Copilot Types
// ---------------------------------------------------------------------------

interface PrioritizedThreadSummary {
  rank: number
  thread_id: string
  thread_title: string
  priority: string
  attention_level: string
  urgency_score: number
  attention_score: number
  blocker_pressure: number
  deadline_pressure: number
  why_it_ranks_high: string
  recommended_next_step: string
}

interface IntentDecisionCard {
  card_id: string
  card_type: string
  thread_id?: string | null
  thread_title?: string | null
  title: string
  summary: string
  evidence_snippets: string[]
  recommended_action: string
  urgency_score?: number | null
  attention_score?: number | null
  metadata?: Record<string, any>
  created_at: string
}

interface SafeClosureCandidate {
  thread_id: string
  thread_title: string
  status: string
  is_safe_to_close: boolean
  verification_status: string
  active_blockers_count: number
  open_commitments_count: number
  evidence_count: number
  explanation: string
  evaluated_at: string
}

interface TimeBudgetRecommendation {
  available_minutes: number
  selected_thread_id: string
  selected_thread_title: string
  reason: string
  expected_next_action: string
  fits_budget: boolean
  is_blocked: boolean
  evaluated_at: string
}

interface WhatIfSimulationResult {
  scenario_type: string
  thread_id: string
  thread_title: string
  parameters: Record<string, any>
  original_urgency: number
  simulated_urgency: number
  original_attention: number
  simulated_attention: number
  original_decay_state: string
  simulated_decay_state: string
  deadline_impact_description: string
  blocker_impact_description: string
  resumability_impact_description: string
  affected_related_thread_ids: string[]
  simulation_summary: string
  label: string
  simulated_at: string
}

interface IntentCopilotOverview {
  primary_recommendation: string
  ranked_priorities: PrioritizedThreadSummary[]
  decision_cards: IntentDecisionCard[]
  resumable_candidates: ResumableCandidate[]
  safe_closure_candidates: SafeClosureCandidate[]
  alexa_voice_text: string
  generated_at: string
}

const M15_COPILOT_PROMPTS = [
  { label: '🥇 What should I do first?', prompt: 'What should I do first?' },
  { label: '⭐ Why is this important?', prompt: 'Why is this important?' },
  { label: '🔄 What changed?', prompt: 'What changed since yesterday?' },
  { label: '🔮 What if I postpone it?', prompt: 'What if I postpone it?' },
  { label: '⏱️ I have 30 minutes', prompt: 'I have 30 minutes. What can I realistically finish?' },
  { label: '▶️ Continue where I left off', prompt: 'Continue where I left off.' },
  { label: '🚧 What is blocking me?', prompt: 'What is blocking me the most?' },
  { label: '✅ Can I close anything?', prompt: 'Can I close anything?' },
  { label: '🤝 Help me deal with this', prompt: 'Help me deal with this.' },
  { label: '❓ Ambiguous request', prompt: 'Help me deal with it' },
]

const M14_PROMPTS = [
  { label: '⚡ Briefing', prompt: 'Give me a briefing.' },
  { label: '🎯 Attention Radar', prompt: 'What deserves my attention?' },
  { label: '❓ Why Care Now?', prompt: 'Why should I care about this now?' },
  { label: '🔄 What Changed?', prompt: "What's changed?" },
  { label: '▶️ Check Resumable', prompt: 'Can I resume anything?' },
  { label: '⚔️ Check Conflicts', prompt: 'Do any of my intentions conflict?' },
  { label: '⏳ Stale & Decaying', prompt: "What's going stale?" },
  { label: '🚫 Blocked Intentions', prompt: 'Which intentions are blocked?' },
]

const M13_PROMPTS = [
  { label: '🎯 Radar Scan', prompt: 'Scan my intent radar' },
  { label: '⏳ Decay Check', prompt: 'Which intentions are decaying?' },
  { label: '🔍 What Changed?', prompt: 'What changed on University Application?' },
  { label: '🌱 Evolve Goal', prompt: 'Update my dentist goal to: Schedule teeth cleaning and consult on wisdom tooth' },
  { label: '🛡️ Ambiguous Goal', prompt: 'I might want to change my dentist appointment to another clinic maybe' },
  { label: '⏸️ Defer Thread', prompt: 'Defer Client Quarterly Report until next Monday' },
  { label: '▶️ Resume Thread', prompt: 'Resume Client Quarterly Report' },
]

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
  { id: 'm12', label: 'M12 — Final Hackathon Demo & Submission Readiness', status: 'done' },
  { id: 'm13', label: 'M13 — Persistent Intent Intelligence & Memory', status: 'done' },
  { id: 'm14', label: 'M14 — Proactive Intent Intelligence & Attention Engine', status: 'done' },
  { id: 'm15', label: 'M15 — Proactive Agent Experience & Intent Copilot', status: 'done' },
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

  const cleaned = rawContent
    .replace(/\\([*_`~[\]()])/g, '$1')
    .replace(/\r\n/g, '\n')

  const lines = cleaned.split('\n')

  return lines.map((line, lineIdx) => {
    const parts: React.ReactNode[] = []
    const regex = /(\*\*([^*]+)\*\*|`([^`]+)`)/g
    let lastIndex = 0
    let match: RegExpExecArray | null

    while ((match = regex.exec(line)) !== null) {
      if (match.index > lastIndex) {
        parts.push(line.substring(lastIndex, match.index))
      }

      if (match[2] !== undefined) {
        parts.push(
          <strong key={`${lineIdx}-${match.index}`} className="message-bold">
            {match[2]}
          </strong>
        )
      } else if (match[3] !== undefined) {
        parts.push(
          <code key={`${lineIdx}-${match.index}`} className="message-code">
            {match[3]}
          </code>
        )
      }

      lastIndex = match.index + match[0].length
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
        'Hello! I am **Threadback**, your proactive personal intent-recovery agent. I can help you discover forgotten intentions, identify what deserves attention right now, explain why now, track changes, detect conflicts, and safely simulate actions.\n\nTry asking **"What deserves my attention?"** or click **Intent Intelligence** above for the proactive dashboard.',
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

  // M14 & M15 State
  const [activeTab, setActiveTab] = useState<'chat' | 'copilot' | 'intelligence'>('chat')
  const [briefing, setBriefing] = useState<ProactiveBriefing | null>(null)
  const [attentionList, setAttentionList] = useState<AttentionCandidate[]>([])
  const [resumableList, setResumableList] = useState<ResumableCandidate[]>([])
  const [conflictsList, setConflictsList] = useState<IntentConflict[]>([])
  const [healthSummary, setHealthSummary] = useState<IntentHealthSummary | null>(null)
  const [isLoadingIntelligence, setIsLoadingIntelligence] = useState<boolean>(false)

  // M15 Copilot State
  const [copilotOverview, setCopilotOverview] = useState<IntentCopilotOverview | null>(null)
  const [isLoadingCopilot, setIsLoadingCopilot] = useState<boolean>(false)
  const [safeClosureList, setSafeClosureList] = useState<SafeClosureCandidate[]>([])
  const [timeBudgetMinutes, setTimeBudgetMinutes] = useState<number>(30)
  const [timeBudgetPlan, setTimeBudgetPlan] = useState<TimeBudgetRecommendation | null>(null)
  const [isLoadingBudget, setIsLoadingBudget] = useState<boolean>(false)
  const [whatIfResult, setWhatIfResult] = useState<WhatIfSimulationResult | null>(null)
  const [whatIfThreadId, setWhatIfThreadId] = useState<string>('thread-university-application')
  const [whatIfScenario, setWhatIfScenario] = useState<string>('POSTPONE')
  const [whatIfDays, setWhatIfDays] = useState<number>(7)
  const [isSimulating, setIsSimulating] = useState<boolean>(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)

  const fetchCopilotData = async () => {
    setIsLoadingCopilot(true)
    try {
      const [oRes, cRes, bRes] = await Promise.all([
        fetch('/api/copilot/overview'),
        fetch('/api/copilot/safe-closure'),
        fetch(`/api/copilot/time-budget?available_minutes=${timeBudgetMinutes}`),
      ])
      if (oRes.ok) setCopilotOverview(await oRes.json())
      if (cRes.ok) setSafeClosureList(await cRes.json())
      if (bRes.ok) setTimeBudgetPlan(await bRes.json())
    } catch (err) {
      console.error('Failed to load copilot data', err)
    } finally {
      setIsLoadingCopilot(false)
    }
  }

  const runWhatIf = async () => {
    if (!whatIfThreadId) return
    setIsSimulating(true)
    try {
      const res = await fetch('/api/copilot/what-if', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_type: whatIfScenario,
          thread_id: whatIfThreadId,
          parameters: { days: whatIfDays },
        }),
      })
      if (res.ok) {
        setWhatIfResult(await res.json())
      }
    } catch (err) {
      console.error('Failed to run what-if simulation', err)
    } finally {
      setIsSimulating(false)
    }
  }

  const runTimeBudget = async (mins: number) => {
    setTimeBudgetMinutes(mins)
    setIsLoadingBudget(true)
    try {
      const res = await fetch(`/api/copilot/time-budget?available_minutes=${mins}`)
      if (res.ok) {
        setTimeBudgetPlan(await res.json())
      }
    } catch (err) {
      console.error('Failed to fetch time budget plan', err)
    } finally {
      setIsLoadingBudget(false)
    }
  }

  const fetchIntelligence = async () => {
    setIsLoadingIntelligence(true)
    try {
      const [bRes, aRes, rRes, cRes, hRes] = await Promise.all([
        fetch('/api/proactive/briefing'),
        fetch('/api/proactive/attention'),
        fetch('/api/proactive/resumable'),
        fetch('/api/proactive/conflicts'),
        fetch('/api/proactive/health'),
      ])
      if (bRes.ok) setBriefing(await bRes.json())
      if (aRes.ok) setAttentionList(await aRes.json())
      if (rRes.ok) setResumableList(await rRes.json())
      if (cRes.ok) setConflictsList(await cRes.json())
      if (hRes.ok) setHealthSummary(await hRes.json())
    } catch (err) {
      console.error('Failed to load proactive intelligence', err)
    } finally {
      setIsLoadingIntelligence(false)
    }
  }

  useEffect(() => {
    fetch('/api/agent/info')
      .then((res) => res.json())
      .then((data) => {
        if (data.provider) setAgentProvider(data.provider)
      })
      .catch(() => {})

    Promise.all([
      fetch('/api/proactive/briefing').then((r) => (r.ok ? r.json() : null)),
      fetch('/api/proactive/attention').then((r) => (r.ok ? r.json() : [])),
      fetch('/api/proactive/resumable').then((r) => (r.ok ? r.json() : [])),
      fetch('/api/proactive/conflicts').then((r) => (r.ok ? r.json() : [])),
      fetch('/api/proactive/health').then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([b, a, r, c, h]) => {
        if (b) setBriefing(b)
        if (a) setAttentionList(a)
        if (r) setResumableList(r)
        if (c) setConflictsList(c)
        if (h) setHealthSummary(h)
      })
      .catch(() => {})
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

    if (
      pendingProposalId &&
      (text.toLowerCase().includes('yes') ||
        text.toLowerCase().includes('ahead') ||
        text.toLowerCase().includes('proceed'))
    ) {
      setCurrentActivity('Executing action via MCP execute_action...')
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
        throw new Error(`Server returned HTTP ${res.status}`)
      }

      const data = await res.json()

      const assistantMsg: Message = {
        id: nextMessageId('assistant'),
        role: 'assistant',
        content: data.message || 'No response message received.',
        pendingConfirmation: Boolean(data.pending_confirmation),
        proposalId: data.pending_proposal_id || null,
        threadId: data.active_thread_id || null,
        activities: data.activities || [],
        executionStatus: data.execution_status || null,
        executionMode: data.execution_mode || null,
        radarReport: data.radar_report || null,
        diffSummary: data.diff_summary || null,
        timestamp: getTimestamp(),
      }

      setMessages((prev) => [...prev, assistantMsg])
      setPendingProposalId(data.pending_proposal_id || null)

      // Refresh intelligence state after potential changes
      fetchIntelligence()
    } catch (err) {
      const errorMsg: Message = {
        id: nextMessageId('error'),
        role: 'assistant',
        content: `Error: Unable to connect to Threadback Agent (${String(err)}). Please ensure the backend is running.`,
        timestamp: getTimestamp(),
      }
      setMessages((prev) => [...prev, errorMsg])
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

      const newConvId = `session-${Date.now()}`
      setConversationId(newConvId)
      setPendingProposalId(null)
      setMessages([
        {
          id: nextMessageId('reset'),
          role: 'assistant',
          content:
            'Conversation state reset and canonical demo data restored in persistent SQLite storage. Try asking **"Give me a briefing"** or **"What deserves my attention?"**.',
          timestamp: getTimestamp(),
        },
      ])
      fetchIntelligence()
    } catch (err) {
      console.error('Reset error:', err)
    }
  }

  const handleDashboardAction = (promptText: string) => {
    setActiveTab('chat')
    sendMessage(promptText)
  }

  return (
    <div className="app">
      <div className="app-background" aria-hidden="true" />

      {/* Header */}
      <header className="header" role="banner">
        <div className="header-logo">
          <div className="logo-mark" aria-hidden="true">
            🧵
          </div>
          <div className="logo-text-group">
            <span className="logo-name">Threadback</span>
            <span className="logo-subtitle">Proactive Intent Intelligence</span>
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
            title="Reset conversation state and restore canonical demo data in SQLite"
          >
            Reset Demo
          </button>
          <span className="header-badge" aria-label="Development status">
            M14 Proactive Intelligence
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
                  m.status === 'done' ? 'milestone-tile--done' : 'milestone-tile--current'
                }`}
              >
                <span className="tile-check">✓</span>
                <span className="tile-label">{m.label}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Navigation Tabs */}
      <div className="nav-tabs-container">
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'chat' ? 'nav-tab-btn--active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          💬 Conversational Agent
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'copilot' ? 'nav-tab-btn--active' : ''}`}
          onClick={() => {
            setActiveTab('copilot')
            fetchCopilotData()
          }}
        >
          🧭 Intent Copilot (M15)
        </button>
        <button
          type="button"
          className={`nav-tab-btn ${activeTab === 'intelligence' ? 'nav-tab-btn--active' : ''}`}
          onClick={() => {
            setActiveTab('intelligence')
            fetchIntelligence()
          }}
        >
          🧠 Intent Intelligence Dashboard (M14)
        </button>
      </div>

      {/* View: Intent Copilot Dashboard (M15) */}
      {activeTab === 'copilot' && (
        <div className="copilot-dashboard" role="region" aria-label="Intent Copilot Dashboard">
          {/* Visual Taxonomy Legend */}
          <div className="taxonomy-legend-bar">
            <span className="taxonomy-legend-title">Boundary Taxonomy:</span>
            <span className="taxonomy-badge taxonomy-badge--simulated">
              ⚡ SIMULATED EXTERNAL ACTION (No real-world side effects)
            </span>
            <span className="taxonomy-badge taxonomy-badge--mutation">
              💾 PERSISTENT THREADBACK MUTATION (Durable internal SQLite state)
            </span>
            <span className="taxonomy-badge taxonomy-badge--verified">
              🔍 VERIFIED COMPLETION (Factual evidence proof)
            </span>
            <span className="taxonomy-badge taxonomy-badge--simulation">
              🔮 SIMULATION — NO STATE CHANGED (Counterfactual analysis)
            </span>
            <button
              type="button"
              className="intel-action-btn"
              style={{ marginLeft: 'auto' }}
              disabled={isLoadingCopilot}
              onClick={fetchCopilotData}
            >
              {isLoadingCopilot ? 'Refreshing...' : '🔄 Refresh Copilot'}
            </button>
          </div>

          {/* Copilot Executive Hero Card */}
          {copilotOverview && (
            <div className="copilot-hero-card">
              <div className="copilot-hero-header">
                <span className="copilot-hero-title">
                  <span>🧭</span> Intent Copilot Voice Synthesis
                </span>
                <span className="briefing-hero-timestamp">
                  Generated: {new Date(copilotOverview.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              <div className="copilot-hero-speech">
                "{copilotOverview.alexa_voice_text || copilotOverview.primary_recommendation}"
              </div>
              <div className="briefing-alexa-tag">
                <span>🔊 Alexa+ Conversational Format</span>
                <span style={{ margin: '0 8px' }}>·</span>
                <span>Deterministic Grounded Reasoning — Zero Speculation</span>
              </div>
            </div>
          )}

          {/* 1. Explainable Prioritization */}
          <div className="copilot-card-section">
            <div className="copilot-section-header">
              <span className="copilot-section-title">
                <span>🥇</span> Explainable Prioritization ("What should I do first?")
              </span>
              <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                Urgency (Execution pressure) vs Attention (Cognitive salience)
              </span>
            </div>
            <div className="priorities-list">
              {copilotOverview?.ranked_priorities.map((item) => (
                <div key={item.thread_id} className="priority-item-card">
                  <div className="priority-item-top">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="priority-rank-chip">#{item.rank}</span>
                      <strong style={{ color: '#fff', fontSize: '0.95rem' }}>{item.thread_title}</strong>
                      <span className={`intel-level-chip intel-level-chip--${item.attention_level}`}>
                        {item.attention_level}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="intel-action-btn"
                      onClick={() => handleDashboardAction(`Why is ${item.thread_title} important?`)}
                    >
                      Why is this important? →
                    </button>
                  </div>
                  <div className="priority-scores-bar">
                    <span style={{ color: '#f87171' }}>⚡ Urgency: {item.urgency_score.toFixed(2)}</span>
                    <span style={{ color: '#c084fc' }}>🧠 Attention: {item.attention_score.toFixed(2)}</span>
                    <span style={{ color: '#fb923c' }}>🚧 Blocker Pressure: {item.blocker_pressure.toFixed(2)}</span>
                    <span style={{ color: '#facc15' }}>⏳ Deadline Pressure: {item.deadline_pressure.toFixed(2)}</span>
                  </div>
                  <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>
                    {item.why_it_ranks_high}
                  </p>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                    <span style={{ fontSize: '0.78rem', color: '#38bdf8' }}>
                      👉 Recommended Next: {item.recommended_next_step}
                    </span>
                    <button
                      type="button"
                      className="intel-action-btn"
                      onClick={() => handleDashboardAction(`Help me deal with ${item.thread_title}`)}
                    >
                      Help me deal with this →
                    </button>
                  </div>
                </div>
              ))}
              {(!copilotOverview?.ranked_priorities || copilotOverview.ranked_priorities.length === 0) && (
                <div className="intel-empty-note">No open intentions require prioritization right now.</div>
              )}
            </div>
          </div>

          {/* 2. Interactive What-If Simulation Sandbox */}
          <div className="copilot-card-section">
            <div className="copilot-section-header">
              <span className="copilot-section-title">
                <span>🔮</span> What-If Scenario Sandbox ("What if I postpone it?")
              </span>
              <span className="taxonomy-badge taxonomy-badge--simulation">
                SIMULATION — NO STATE CHANGED
              </span>
            </div>
            <div className="what-if-sandbox">
              <div className="what-if-controls-row">
                <div className="what-if-control-group">
                  <label className="what-if-label">Target Intention</label>
                  <select
                    className="what-if-select"
                    value={whatIfThreadId}
                    onChange={(e) => setWhatIfThreadId(e.target.value)}
                  >
                    <option value="thread-university-application">University Application</option>
                    <option value="thread-client-report">Client Quarterly Report</option>
                    <option value="thread-dentist-appointment">Dentist Appointment</option>
                    <option value="thread-professional-certification">Professional Certification</option>
                  </select>
                </div>
                <div className="what-if-control-group">
                  <label className="what-if-label">Scenario</label>
                  <select
                    className="what-if-select"
                    value={whatIfScenario}
                    onChange={(e) => setWhatIfScenario(e.target.value)}
                  >
                    <option value="POSTPONE">Postpone Intention</option>
                    <option value="IGNORE_TEMPORARILY">Ignore Temporarily</option>
                    <option value="RESOLVE_BLOCKER">Resolve Active Blocker</option>
                    <option value="CHANGE_GOAL">Evolve Goal</option>
                  </select>
                </div>
                {(whatIfScenario === 'POSTPONE' || whatIfScenario === 'IGNORE_TEMPORARILY') && (
                  <div className="what-if-control-group">
                    <label className="what-if-label">Duration (Days)</label>
                    <input
                      type="number"
                      min={1}
                      max={90}
                      className="what-if-input"
                      style={{ width: '80px' }}
                      value={whatIfDays}
                      onChange={(e) => setWhatIfDays(Number(e.target.value))}
                    />
                  </div>
                )}
                <button
                  type="button"
                  className="what-if-run-btn"
                  disabled={isSimulating}
                  onClick={runWhatIf}
                >
                  {isSimulating ? 'Simulating...' : 'Run Simulation'}
                </button>
              </div>

              {whatIfResult && (
                <div className="what-if-result-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong style={{ color: '#c084fc' }}>
                      Simulation Result: {whatIfResult.thread_title} ({whatIfResult.scenario_type})
                    </strong>
                    <span className="taxonomy-badge taxonomy-badge--simulation">
                      {whatIfResult.label}
                    </span>
                  </div>
                  <div className="what-if-metrics-grid">
                    <div className="what-if-metric-box">
                      <span style={{ color: 'var(--color-text-muted)', display: 'block', fontSize: '0.7rem' }}>URGENCY SHIFT</span>
                      <strong>{whatIfResult.original_urgency.toFixed(2)} → {whatIfResult.simulated_urgency.toFixed(2)}</strong>
                    </div>
                    <div className="what-if-metric-box">
                      <span style={{ color: 'var(--color-text-muted)', display: 'block', fontSize: '0.7rem' }}>ATTENTION SHIFT</span>
                      <strong>{whatIfResult.original_attention.toFixed(2)} → {whatIfResult.simulated_attention.toFixed(2)}</strong>
                    </div>
                    <div className="what-if-metric-box">
                      <span style={{ color: 'var(--color-text-muted)', display: 'block', fontSize: '0.7rem' }}>DECAY TRANSITION</span>
                      <strong>{whatIfResult.original_decay_state} → {whatIfResult.simulated_decay_state}</strong>
                    </div>
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div><strong>Deadline Impact:</strong> {whatIfResult.deadline_impact_description}</div>
                    <div><strong>Blocker Impact:</strong> {whatIfResult.blocker_impact_description}</div>
                    <div><strong>Resumability Impact:</strong> {whatIfResult.resumability_impact_description}</div>
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '0.85rem', color: '#e2e8f0', background: 'rgba(0,0,0,0.3)', padding: '8px', borderRadius: '4px' }}>
                    💬 {whatIfResult.simulation_summary}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 3. Time-Budget Planning */}
          <div className="copilot-card-section">
            <div className="copilot-section-header">
              <span className="copilot-section-title">
                <span>⏱️</span> Time-Budget Planning ("I have 30 minutes. What can I realistically finish?")
              </span>
              <div className="time-budget-pills-row">
                {[15, 30, 60, 120].map((mins) => (
                  <button
                    key={mins}
                    type="button"
                    className={`time-pill-btn ${timeBudgetMinutes === mins ? 'time-pill-btn--active' : ''}`}
                    disabled={isLoadingBudget}
                    onClick={() => runTimeBudget(mins)}
                  >
                    {isLoadingBudget && timeBudgetMinutes === mins ? 'Calculating...' : `${mins}m Slot`}
                  </button>
                ))}
              </div>
            </div>
            {timeBudgetPlan && (
              <div className="priority-item-card" style={{ borderColor: 'rgba(14, 165, 233, 0.35)' }}>
                <div className="priority-item-top">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <strong style={{ color: '#38bdf8', fontSize: '0.95rem' }}>
                      Recommended for {timeBudgetPlan.available_minutes}m: {timeBudgetPlan.selected_thread_title}
                    </strong>
                    <span className={`taxonomy-badge ${timeBudgetPlan.fits_budget ? 'taxonomy-badge--verified' : 'taxonomy-badge--simulated'}`}>
                      {timeBudgetPlan.fits_budget ? '✓ Fits Time Budget' : '⚠️ Requires Multiple Sessions'}
                    </span>
                    {timeBudgetPlan.is_blocked && (
                      <span className="taxonomy-badge taxonomy-badge--simulated" style={{ color: '#fb7185' }}>
                        🚫 Blocked
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="intel-action-btn"
                    onClick={() => handleDashboardAction(`I have ${timeBudgetPlan.available_minutes} minutes. What can I realistically finish?`)}
                  >
                    Plan in Chat →
                  </button>
                </div>
                <p style={{ margin: 0, fontSize: '0.84rem', color: 'var(--color-text-secondary)' }}>
                  {timeBudgetPlan.reason}
                </p>
                <div style={{ fontSize: '0.8rem', color: '#a5b4fc' }}>
                  👉 Next Action: {timeBudgetPlan.expected_next_action}
                </div>
              </div>
            )}
          </div>

          {/* 4. Safe Closure Assistant */}
          <div className="copilot-card-section">
            <div className="copilot-section-header">
              <span className="copilot-section-title">
                <span>🛡️</span> Safe Closure Assistant ("Can I close anything?")
              </span>
              <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                Verification-Gated: verify_thread_completion → Confirmation → close_thread
              </span>
            </div>
            <div className="priorities-list">
              {safeClosureList.map((cand) => (
                <div key={cand.thread_id} className="priority-item-card">
                  <div className="priority-item-top">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <strong style={{ color: '#fff' }}>{cand.thread_title}</strong>
                      <span className={`taxonomy-badge ${cand.is_safe_to_close ? 'taxonomy-badge--verified' : 'taxonomy-badge--simulated'}`}>
                        {cand.is_safe_to_close ? 'SAFE TO CLOSE' : 'NOT SAFE TO CLOSE'}
                      </span>
                      <span className={`verification-badge verification-badge--${cand.verification_status.toLowerCase()}`}>
                        {cand.verification_status}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="intel-action-btn"
                      onClick={() => handleDashboardAction(`Can I close ${cand.thread_title}?`)}
                    >
                      Inspect Closure →
                    </button>
                  </div>
                  <div className="priority-scores-bar">
                    <span>Blockers: {cand.active_blockers_count}</span>
                    <span>Open Commitments: {cand.open_commitments_count}</span>
                    <span>Evidence Count: {cand.evidence_count}</span>
                  </div>
                  <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>
                    {cand.explanation}
                  </p>
                </div>
              ))}
              {safeClosureList.length === 0 && (
                <div className="intel-empty-note">No terminal or unclosable intentions detected.</div>
              )}
            </div>
          </div>

          {/* 5. Intent Decision Cards */}
          <div className="copilot-card-section">
            <div className="copilot-section-header">
              <span className="copilot-section-title">
                <span>🗂️</span> Intent Decision Cards
              </span>
              <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                Structured Frontend Objects
              </span>
            </div>
            <div className="decision-cards-grid">
              {copilotOverview?.decision_cards.map((card) => (
                <div key={card.card_id} className="decision-card-item">
                  <div className="decision-card-header">
                    <span className={`card-type-chip card-type-chip--${card.card_type}`}>
                      {card.card_type}
                    </span>
                    {card.urgency_score !== null && card.urgency_score !== undefined && (
                      <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>
                        U: {card.urgency_score.toFixed(2)}
                      </span>
                    )}
                  </div>
                  <strong style={{ color: '#fff', fontSize: '0.9rem' }}>{card.title}</strong>
                  <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
                    {card.summary}
                  </p>
                  {card.evidence_snippets.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', background: 'rgba(0,0,0,0.2)', padding: '6px', borderRadius: '4px', fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>
                      {card.evidence_snippets.map((snip, idx) => (
                        <div key={idx}>• {snip}</div>
                      ))}
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto', paddingTop: '4px' }}>
                    <span style={{ fontSize: '0.75rem', color: '#c4b5fd' }}>
                      👉 {card.recommended_action}
                    </span>
                    <button
                      type="button"
                      className="intel-action-btn"
                      onClick={() => handleDashboardAction(card.recommended_action)}
                    >
                      Ask →
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* View: Intent Intelligence Dashboard */}
      {activeTab === 'intelligence' && (
        <div className="intelligence-dashboard" role="region" aria-label="Intent Intelligence Dashboard">
          {/* Visual Taxonomy Legend */}
          <div className="taxonomy-legend-bar">
            <span className="taxonomy-legend-title">Boundary Taxonomy:</span>
            <span className="taxonomy-badge taxonomy-badge--simulated">
              ⚡ SIMULATED EXTERNAL ACTION (No real-world side effects)
            </span>
            <span className="taxonomy-badge taxonomy-badge--mutation">
              💾 PERSISTENT THREADBACK MUTATION (Durable internal SQLite state)
            </span>
            <span className="taxonomy-badge taxonomy-badge--verified">
              🔍 VERIFIED COMPLETION (Factual evidence proof)
            </span>
            <button
              type="button"
              className="intel-action-btn"
              style={{ marginLeft: 'auto' }}
              disabled={isLoadingIntelligence}
              onClick={fetchIntelligence}
            >
              {isLoadingIntelligence ? 'Refreshing...' : '🔄 Refresh Intelligence'}
            </button>
          </div>

          {/* Executive Briefing Hero Card */}
          {briefing && (
            <div className="briefing-hero-card">
              <div className="briefing-hero-header">
                <span className="briefing-hero-title">
                  <span>⚡</span> Proactive Executive Briefing
                </span>
                <span className="briefing-hero-timestamp">
                  Generated: {new Date(briefing.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              <div className="briefing-hero-body">
                "{briefing.briefing_text}"
              </div>
              <div className="briefing-alexa-tag">
                <span>🔊 Alexa+ Conversational Format</span>
                <span style={{ margin: '0 8px' }}>·</span>
                <span>Deterministic Grounded Synthesis</span>
              </div>
            </div>
          )}

          {/* Health Summary KPIs */}
          {healthSummary && (
            <div className="kpi-metrics-grid">
              <div className="kpi-tile">
                <span className="kpi-tile-value">{healthSummary.total_active_threads}</span>
                <span className="kpi-tile-label">Active Intentions</span>
              </div>
              <div className="kpi-tile">
                <span className="kpi-tile-value" style={{ color: '#34d399' }}>
                  {healthSummary.healthy_threads}
                </span>
                <span className="kpi-tile-label">Healthy</span>
              </div>
              <div className="kpi-tile kpi-tile--attention">
                <span className="kpi-tile-value">{healthSummary.attention_threads}</span>
                <span className="kpi-tile-label">Attention Required</span>
              </div>
              <div className="kpi-tile">
                <span className="kpi-tile-value" style={{ color: '#fbbf24' }}>
                  {healthSummary.decaying_threads + healthSummary.stale_threads}
                </span>
                <span className="kpi-tile-label">Decaying / Stale</span>
              </div>
              <div className="kpi-tile">
                <span className="kpi-tile-value" style={{ color: '#f87171' }}>
                  {healthSummary.blocked_threads}
                </span>
                <span className="kpi-tile-label">Blocked</span>
              </div>
              <div className="kpi-tile kpi-tile--resumable">
                <span className="kpi-tile-value">{healthSummary.resumable_threads}</span>
                <span className="kpi-tile-label">Resumable</span>
              </div>
              <div className="kpi-tile kpi-tile--conflict">
                <span className="kpi-tile-value">{healthSummary.conflicts_count}</span>
                <span className="kpi-tile-label">Conflicts</span>
              </div>
            </div>
          )}

          {/* 2-Column Intelligence Grid */}
          <div className="intel-sections-grid">
            {/* Panel 1: Attention Radar */}
            <div className="intel-panel">
              <div className="intel-panel-header">
                <span className="intel-panel-title">
                  <span>🎯</span> Attention Radar Candidates
                </span>
                <span className="intel-panel-count">{attentionList.length} monitored</span>
              </div>
              <div className="intel-panel-body">
                {attentionList.map((c) => (
                  <div key={c.thread_id} className="intel-item-card">
                    <div className="intel-item-header">
                      <span className="intel-item-title">{c.thread_title}</span>
                      <span className={`attention-badge attention-badge--${c.attention_level.toLowerCase()}`}>
                        {c.attention_level}
                      </span>
                    </div>
                    <div className="intel-score-bar-row">
                      <span>AttentionScore: {Math.round(c.attention_score * 100)}%</span>
                      <div className="intel-score-progress">
                        <div
                          className="intel-score-fill"
                          style={{ width: `${Math.round(c.attention_score * 100)}%` }}
                        />
                      </div>
                      <span>Urgency: {Math.round(c.urgency_score * 100)}%</span>
                    </div>
                    <div className="intel-item-desc">{c.human_readable_explanation}</div>
                    {c.reason_codes && c.reason_codes.length > 0 && (
                      <div className="intel-chips-row">
                        {c.reason_codes.map((code) => (
                          <span key={code} className="intel-tag-chip">
                            {code}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="intel-item-footer">
                      {c.recommended_action_summary && (
                        <span style={{ fontSize: '0.72rem', color: '#c4b5fd' }}>
                          💡 {c.recommended_action_summary}
                        </span>
                      )}
                      <button
                        type="button"
                        className="intel-action-btn"
                        onClick={() => handleDashboardAction(`Why should I care about ${c.thread_title} now?`)}
                      >
                        Investigate Why Now →
                      </button>
                    </div>
                  </div>
                ))}
                {attentionList.length === 0 && (
                  <div className="intel-empty-note">All intentions are clear and healthy.</div>
                )}
              </div>
            </div>

            {/* Panel 2: Resume Intelligence */}
            <div className="intel-panel">
              <div className="intel-panel-header">
                <span className="intel-panel-title">
                  <span>▶️</span> Resume Eligibility Engine
                </span>
                <span className="intel-panel-count">{resumableList.length} deferred</span>
              </div>
              <div className="intel-panel-body">
                {resumableList.map((r) => (
                  <div key={r.thread_id} className="intel-item-card">
                    <div className="intel-item-header">
                      <span className="intel-item-title">{r.thread_title}</span>
                      <span
                        className="attention-badge"
                        style={{
                          background:
                            r.eligibility === 'RESUMABLE'
                              ? 'rgba(16, 185, 129, 0.2)'
                              : 'rgba(148, 163, 184, 0.15)',
                          color: r.eligibility === 'RESUMABLE' ? '#34d399' : '#94a3b8',
                          borderColor:
                            r.eligibility === 'RESUMABLE' ? 'rgba(16, 185, 129, 0.4)' : 'transparent',
                        }}
                      >
                        {r.eligibility}
                      </span>
                    </div>
                    <div className="intel-item-desc">{r.reason}</div>
                    <div className="intel-item-footer">
                      <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                        Status: DEFERRED · Safe Confirmation Gate
                      </span>
                      {r.eligibility === 'RESUMABLE' && (
                        <button
                          type="button"
                          className="intel-action-btn"
                          onClick={() => handleDashboardAction(`Resume ${r.thread_title}`)}
                        >
                          Prepare Resume Action →
                        </button>
                      )}
                    </div>
                  </div>
                ))}
                {resumableList.length === 0 && (
                  <div className="intel-empty-note">No deferred intentions currently recorded.</div>
                )}
              </div>
            </div>

            {/* Panel 3: Conflict Detection */}
            <div className="intel-panel">
              <div className="intel-panel-header">
                <span className="intel-panel-title">
                  <span>⚔️</span> Conservative Conflict Detection
                </span>
                <span className="intel-panel-count">{conflictsList.length} detected</span>
              </div>
              <div className="intel-panel-body">
                {conflictsList.map((conf) => (
                  <div key={conf.conflict_id} className="intel-item-card">
                    <div className="intel-item-header">
                      <span className="intel-item-title">
                        {conf.thread_a_title} ↔ {conf.thread_b_title}
                      </span>
                      <span className="attention-badge attention-badge--high">
                        {conf.conflict_type}
                      </span>
                    </div>
                    <div className="intel-item-desc">{conf.explanation}</div>
                    <div className="intel-item-footer">
                      <span style={{ fontSize: '0.7rem', color: '#fbbf24' }}>
                        Severity: {conf.severity} · Temporal Impossibility
                      </span>
                      <button
                        type="button"
                        className="intel-action-btn"
                        onClick={() => handleDashboardAction('Do any of my intentions conflict?')}
                      >
                        Inspect Conflict Details →
                      </button>
                    </div>
                  </div>
                ))}
                {conflictsList.length === 0 && (
                  <div className="intel-empty-note">
                    No structured conflicts detected. Temporal and resource schedules are harmonious.
                  </div>
                )}
              </div>
            </div>

            {/* Panel 4: Recent State Changes */}
            <div className="intel-panel">
              <div className="intel-panel-header">
                <span className="intel-panel-title">
                  <span>🔄</span> What Changed? (4-Tier Comparison Anchor)
                </span>
                <span className="intel-panel-count">
                  {briefing?.top_changes.length || 0} modified
                </span>
              </div>
              <div className="intel-panel-body">
                {briefing?.top_changes.map((delta) => (
                  <div key={delta.thread_id} className="intel-item-card">
                    <div className="intel-item-header">
                      <span className="intel-item-title">{delta.thread_title}</span>
                      <span className={`attention-badge attention-badge--${delta.significance_level.toLowerCase()}`}>
                        {delta.significance_level} SIGNIFICANCE
                      </span>
                    </div>
                    <div className="intel-chips-row">
                      {delta.changes.map((ch, idx) => (
                        <div key={idx} className="intel-item-desc" style={{ width: '100%' }}>
                          • <strong>{ch.category}</strong>: {ch.description}
                        </div>
                      ))}
                    </div>
                    <div className="intel-item-footer">
                      <span style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
                        Significance: {Math.round(delta.significance_score * 100)}%
                      </span>
                      <button
                        type="button"
                        className="intel-action-btn"
                        onClick={() => handleDashboardAction(`What changed on ${delta.thread_title}?`)}
                      >
                        Inspect Thread Diff →
                      </button>
                    </div>
                  </div>
                ))}
                {(!briefing?.top_changes || briefing.top_changes.length === 0) && (
                  <div className="intel-empty-note">No recent state changes since anchor.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* View: Conversational Agent Chat */}
      {activeTab === 'chat' && (
        <main className="chat-container" id="main-content" role="main">
          {/* M15 Intent Copilot Chips */}
          <div className="demo-chips-container" aria-label="M15 Intent Copilot Scenarios">
            <span className="chips-label">🧭 M15 Intent Copilot:</span>
            {M15_COPILOT_PROMPTS.map((item) => (
              <button
                key={item.label}
                type="button"
                className="chip-btn"
                style={{ borderColor: 'rgba(129, 140, 248, 0.4)', color: '#c7d2fe' }}
                disabled={isLoading}
                onClick={() => sendMessage(item.prompt)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {/* M14 Suggestion Chips */}
          <div className="demo-chips-container" aria-label="Quick proactive queries">
            <span className="chips-label">⚡ M14 Proactive Intelligence:</span>
            {M14_PROMPTS.map((item) => (
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

          {/* M13 Suggestion Chips */}
          <div className="demo-chips-container" aria-label="M13 Intent Memory Queries" style={{ marginTop: '4px' }}>
            <span className="chips-label">🎯 M13 Intent Memory:</span>
            {M13_PROMPTS.map((item) => (
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
            <span className="chips-label" style={{ marginLeft: '12px' }}>
              🧵 9-Phase Lifecycle:
            </span>
            {DEMO_PROMPTS.slice(0, 4).map((item) => (
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

                  {/* Tool Activity Indicators */}
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
                  {msg.executionMode === 'PERSISTENT_MUTATION' && (
                    <div className="mutation-badge">
                      💾 <strong>PERSISTENT THREADBACK MUTATION</strong> · Internal Threadback state mutated in persistent SQLite storage (<strong>Persistent Threadback mutation ≠ external-world action</strong>).
                    </div>
                  )}

                  {/* M13 Intent Radar Scan Card */}
                  {msg.radarReport && (
                    <div className="radar-report-card">
                      <div className="radar-report-header">
                        <span className="radar-badge-icon" aria-hidden="true">🎯</span>
                        <div>
                          <strong>Intent Radar Prioritization</strong>
                          {msg.radarReport.top_focus_thread_id && (
                            <span className="radar-top-focus">
                              Top Focus: {msg.radarReport.top_focus_thread_id}
                            </span>
                          )}
                        </div>
                      </div>
                      {msg.radarReport.items && msg.radarReport.items.length > 0 && (
                        <div className="radar-items-grid">
                          {msg.radarReport.items.map((item) => (
                            <div key={item.thread_id} className="radar-item-row">
                              <div className="radar-item-main">
                                <span className="radar-item-title">{item.title}</span>
                                <span className={`decay-chip decay-chip--${item.decay_state.toLowerCase()}`}>
                                  {item.decay_state}
                                </span>
                              </div>
                              <div className="radar-item-meta">
                                <span className="radar-score">Urgency: {Math.round(item.urgency_score * 100)}/100</span>
                                <span>Attention: {item.attention_level}</span>
                              </div>
                              <div className="radar-item-signal">{item.explanation}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
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
                  : "Ask Threadback: 'Give me a briefing', 'What deserves my attention?', 'Why now?'..."
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
      )}

      {/* Footer */}
      <footer className="footer" role="contentinfo">
        <span>Threadback M15</span>
        <span className="footer-divider" aria-hidden="true">·</span>
        <span>Proactive Agent Experience &amp; Intent Copilot</span>
        <span className="footer-divider" aria-hidden="true">·</span>
        <span>MCP Streamable HTTP (2025-11-25)</span>
        <span className="footer-divider" aria-hidden="true">·</span>
        <span>Grounded Deterministic Boundaries</span>
      </footer>
    </div>
  )
}

export default App
