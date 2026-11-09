import { useEffect, useRef, useState } from 'react'
import { api, MP_LABEL, type Marketplace, type Row } from '../api'
import { Markdown } from '../components/Markdown'
import { Empty, MpBadge, PageHead, toast, useLoad } from '../components/ui'

const AGENTS: Marketplace[] = ['meesho', 'flipkart', 'amazon']

const QUICK: [string, string][] = [
  ['Daily check', 'Run your daily check on all my accounts.'],
  ['Stock mismatches', 'Which SKUs have stock that differs from the master stock? Propose fixes where the right figure is clear.'],
  ['Pending orders', 'How many orders are pending on each account, and which are the oldest?'],
  ['Returns this week', 'Show returns and RTO from the last 7 days, and flag SKUs with repeat returns.'],
  ['Draft content', 'Find up to 3 listed products without approved content and propose content for them.'],
]

const KIND_LABEL: Record<string, string> = {
  master_stock: 'Master stock', listing_status: 'Listing status', content_draft: 'Listing content', task: 'To-do for you',
}

type Msg = { id: number | string; role: 'user' | 'assistant' | 'error'; content: string; tools?: Row[] | null; pending?: boolean }

export default function Agents() {
  const status = useLoad<Row>(() => api.get('/api/agents/status'))
  const proposals = useLoad<Row>(() => api.get('/api/agents/proposals?status=pending'))
  const [chats, setChats] = useState<Record<Marketplace, Msg[]>>({ meesho: [], flipkart: [], amazon: [] })
  const [busy, setBusy] = useState<Record<Marketplace, boolean>>({ meesho: false, flipkart: false, amazon: false })
  const [all, setAll] = useState('')

  useEffect(() => {
    AGENTS.forEach((mp) => api.get(`/api/agents/${mp}/messages`)
      .then((d) => setChats((c) => ({ ...c, [mp]: d.messages })))
      .catch(() => { /* status banner explains */ }))
  }, [])

  const begin = (mp: Marketplace, text: string) => {
    setBusy((b) => ({ ...b, [mp]: true }))
    setChats((c) => ({ ...c, [mp]: [...c[mp], { id: `u${Date.now()}`, role: 'user', content: text },
      { id: `p${Date.now()}`, role: 'assistant', content: '', pending: true }] }))
  }
  const finish = (mp: Marketplace, reply: Row | null, err?: unknown) => {
    setBusy((b) => ({ ...b, [mp]: false }))
    setChats((c) => {
      const kept = c[mp].filter((m) => !m.pending)
      const last: Msg = reply ? reply.message : { id: `e${Date.now()}`, role: 'error', content: err instanceof Error ? err.message : String(err) }
      return { ...c, [mp]: [...kept, last] }
    })
    if (reply?.proposals?.length) {
      toast.ok(`${MP_LABEL[mp]} agent proposed ${reply.proposals.length} change${reply.proposals.length > 1 ? 's' : ''}`)
      proposals.reload()
    }
  }

  const send = async (mp: Marketplace, text: string) => {
    if (!text.trim() || busy[mp]) return
    begin(mp, text)
    try { finish(mp, await api.post(`/api/agents/${mp}/chat`, { message: text })) } catch (e) { finish(mp, null, e) }
  }

  const sendAll = async () => {
    const text = all.trim()
    const free = AGENTS.filter((mp) => !busy[mp])
    if (!text || !free.length) return
    setAll('')
    free.forEach((mp) => begin(mp, text))
    try {
      const r = await api.post('/api/agents/ask-all', { message: text, marketplaces: free })
      free.forEach((mp) => finish(mp, r.results[mp]))
    } catch (e) { free.forEach((mp) => finish(mp, null, e)) }
  }

  const clear = async (mp: Marketplace) => {
    if (!confirm(`Clear the ${MP_LABEL[mp]} agent's chat history in Seller Desk?`)) return
    await api.del(`/api/agents/${mp}/messages`)
    setChats((c) => ({ ...c, [mp]: [] }))
  }

  const s = status.data
  const pending: Row[] = proposals.data?.proposals || []
  return (
    <>
      <PageHead title="Marketplace agents"
        sub="One OpenClaw agent per marketplace. They read Seller Desk data and propose changes; nothing changes until you approve it.">
        <GatewayChip s={s} loading={status.loading} onRefresh={status.reload} />
      </PageHead>

      {s?.problem && (
        <div className="notice">
          <b>Agents are not ready.</b> {s.problem}
          <div className="small muted" style={{ marginTop: 4 }}>To set up the agents, run <code>./openclaw/setup.sh</code> from the Seller Desk folder, then press Refresh.</div>
        </div>
      )}

      <Proposals items={pending} onChange={() => { proposals.reload() }} />

      <div className="card ask-all">
        <div className="row">
          <input placeholder="Ask all three agents, e.g. “How many orders are pending today?”" value={all}
            onChange={(e) => setAll(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && sendAll()} />
          <button className="primary" onClick={sendAll} disabled={!all.trim() || AGENTS.every((mp) => busy[mp])}>Ask all three</button>
        </div>
      </div>

      <div className="grid g3 agents">
        {AGENTS.map((mp) => (
          <AgentPanel key={mp} mp={mp} found={s?.agents?.[mp]?.found} agentId={s?.agents?.[mp]?.id}
            messages={chats[mp]} busy={busy[mp]} onSend={(t) => send(mp, t)} onClear={() => clear(mp)} />
        ))}
      </div>
    </>
  )
}

function GatewayChip({ s, loading, onRefresh }: { s: Row | null; loading: boolean; onRefresh: () => void }) {
  const ok = s && !s.problem
  return (
    <div className="row">
      <span className={`status ${loading ? '' : ok ? 'st-live' : 'st-failed'}`}>
        {loading ? 'Checking OpenClaw…' : ok ? 'OpenClaw connected' : 'OpenClaw not ready'}
      </span>
      <button onClick={onRefresh}>Refresh</button>
    </div>
  )
}

function AgentPanel({ mp, found, agentId, messages, busy, onSend, onClear }: {
  mp: Marketplace; found?: boolean; agentId?: string; messages: Msg[]; busy: boolean
  onSend: (t: string) => void; onClear: () => void
}) {
  const [text, setText] = useState('')
  const log = useRef<HTMLDivElement>(null)
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }) }, [messages])
  const go = (t: string) => { onSend(t); setText('') }
  return (
    <div className={`card agent agent-${mp}`}>
      <div className="agent-head">
        <MpBadge mp={mp} />
        <h3>{MP_LABEL[mp]} agent</h3>
        <span className="small muted" title="OpenClaw agent id">{agentId ? `openclaw/${agentId}` : ''}</span>
        <span className="spacer" />
        {found === false && <span className="status st-failed">missing</span>}
        <button className="ghost icon small" onClick={onClear} title="Clear chat" disabled={busy || !messages.length}>Clear</button>
      </div>
      <div className="quick">
        {QUICK.map(([label, prompt]) => <button key={label} className="small" disabled={busy} onClick={() => go(prompt)}>{label}</button>)}
      </div>
      <div className="chat-log" ref={log}>
        {!messages.length && <Empty>Ask about {MP_LABEL[mp]} orders, stock or listings, or use a quick action.</Empty>}
        {messages.map((m) => <Bubble key={m.id} m={m} />)}
      </div>
      <div className="row chat-input">
        <textarea rows={2} placeholder={`Message the ${MP_LABEL[mp]} agent`} value={text} disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (text.trim()) go(text) } }} />
        <button className="primary" disabled={busy || !text.trim()} onClick={() => go(text)}>{busy ? 'Working…' : 'Send'}</button>
      </div>
    </div>
  )
}

function Bubble({ m }: { m: Msg }) {
  if (m.pending) return <div className="bubble assistant thinking">Working: reading Seller Desk data…</div>
  const tools = (m.tools || []).map((t) => t.name).filter(Boolean)
  return (
    <div className={`bubble ${m.role}`}>
      {m.role === 'assistant' ? <Markdown text={m.content} /> : m.content}
      {tools.length > 0 && <div className="tools-used">{[...new Set(tools)].map((t) => <span key={t} className="pill">{t}</span>)}</div>}
    </div>
  )
}

function Proposals({ items, onChange }: { items: Row[]; onChange: () => void }) {
  const [working, setWorking] = useState<number | null>(null)
  const decide = async (p: Row, approve: boolean) => {
    setWorking(p.id)
    try {
      const r = await api.post(`/api/agents/proposals/${p.id}/decide`, { approve })
      if (r.status === 'failed') toast.err(`Could not apply: ${r.result}`)
      else toast.ok(approve ? r.result || 'Applied' : 'Rejected')
      onChange()
    } catch (e) { toast.err(e) } finally { setWorking(null) }
  }
  if (!items.length) return null
  return (
    <div className="card proposals">
      <h2>Waiting for your approval <span className="pill">{items.length}</span></h2>
      {items.map((p) => (
        <div key={p.id} className="proposal">
          <div className="row">
            <MpBadge mp={p.marketplace} /><span className="pill">{KIND_LABEL[p.kind] || p.kind}</span>
            <b>{p.summary}</b><span className="spacer" />
            <span className="small muted">{p.created_at}</span>
          </div>
          {p.reason && <div className="small muted">Why: {p.reason}</div>}
          {p.kind === 'content_draft' && <ContentPreview d={p.payload} />}
          {p.kind === 'task' && p.payload.detail && <div className="small">{p.payload.detail}</div>}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="primary" disabled={working === p.id} onClick={() => decide(p, true)}>{p.kind === 'task' ? 'Mark done' : 'Approve'}</button>
            <button disabled={working === p.id} onClick={() => decide(p, false)}>{p.kind === 'task' ? 'Dismiss' : 'Reject'}</button>
          </div>
        </div>
      ))}
    </div>
  )
}

function ContentPreview({ d }: { d: Row }) {
  return (
    <div className="content-preview small">
      <div><b>Title</b> ({(d.title || '').length} chars): {d.title}</div>
      {d.highlights && <div><b>Highlights</b>: {d.highlights}</div>}
      {d.bullets?.length > 0 && <ul>{d.bullets.map((b: string, i: number) => <li key={i}>{b}</li>)}</ul>}
      {d.search_terms && <div><b>Search terms</b>: {d.search_terms}</div>}
      <div className="muted">Approving saves this as a draft on the product page. You still approve it there before upload.</div>
    </div>
  )
}
