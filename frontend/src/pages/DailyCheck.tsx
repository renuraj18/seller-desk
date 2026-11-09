import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, MP_LABEL, type Marketplace, type Row } from '../api'
import { Markdown } from '../components/Markdown'
import { Empty, MpBadge, PageHead, toast, useLoad } from '../components/ui'

const LEVEL_CLASS: Record<string, string> = { high: 'st-failed', med: 'st-exported', info: '' }
const STATE_CLASS: Record<string, string> = { ok: 'st-live', empty: 'st-exported', signed_out: 'st-failed', error: 'st-failed' }
const MPS: Marketplace[] = ['meesho', 'flipkart', 'amazon']

function ago(ts?: string | null) {
  if (!ts) return 'never'
  const d = new Date(ts.replace(' ', 'T') + (ts.includes('T') ? '' : 'Z'))   // stored in UTC
  const m = Math.round((Date.now() - d.getTime()) / 60000)
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
}

export default function DailyCheck() {
  const report = useLoad<Row>(() => api.get('/api/daily-check'))
  const sync = useLoad<Row>(() => api.get('/api/sync/status'))
  const [times, setTimes] = useState('')
  const [summaries, setSummaries] = useState<Record<string, Row | null>>({})
  const [writing, setWriting] = useState(false)

  const running = sync.data?.firms?.some((f: Row) => ['requested', 'running'].includes(f.last_run?.status))
  useEffect(() => {
    const t = setInterval(() => { sync.reload(); report.reload() }, running ? 5000 : 30000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])
  useEffect(() => { if (sync.data && !times) setTimes(sync.data.times.join(', ')) }, [sync.data, times])

  const loadSummaries = () => Promise.all(MPS.map((mp) => api.get(`/api/agents/${mp}/messages`).then((d) => {
    const last = [...d.messages].reverse().find((m: Row) => m.role === 'assistant' || m.role === 'error')
    setSummaries((s) => ({ ...s, [mp]: last || null }))
  }).catch(() => { /* agents page explains */ })))
  useEffect(() => { loadSummaries() }, [])
  useEffect(() => {
    if (!writing) return
    const t = setInterval(loadSummaries, 6000)
    const stop = setTimeout(() => setWriting(false), 240000)
    return () => { clearInterval(t); clearTimeout(stop) }
  }, [writing])

  const syncNow = async () => {
    try {
      const r = await api.post('/api/sync/now')
      toast.ok(r.queued.length ? `Sync queued for ${r.queued.join(' and ')}. The extension picks it up within a minute.` : 'Nothing to queue: no taught pages, or a sync is already waiting.')
      sync.reload()
    } catch (e) { toast.err(e) }
  }
  const saveTimes = async () => {
    try { await api.put('/api/sync/times', { times: times.split(/[,\s]+/).filter(Boolean) }); toast.ok('Sync times saved'); sync.reload() } catch (e) { toast.err(e) }
  }
  const writeSummary = async () => { try { await api.post('/api/agents/daily-summary'); setWriting(true); toast.ok('The agents are writing their summaries') } catch (e) { toast.err(e) } }
  const removePage = async (p: Row) => {
    if (!confirm(`Stop syncing ${p.label || p.status || 'this page'} for ${p.account_name}?`)) return
    await api.del(`/api/sync/pages/${p.id}`); sync.reload(); report.reload()
  }

  const r = report.data
  const s = sync.data
  const silent = (s?.firms || []).filter((f: Row) => f.pages > 0 && (f.extension_seen_seconds_ago === null || f.extension_seen_seconds_ago > 180))
  return (
    <>
      <PageHead title="Daily order check" sub="The Seller Desk extension reads your order pages by itself; the checks below are plain rules, no AI, so they appear instantly.">
        <button className="primary" onClick={syncNow}>Sync now</button>
        <button onClick={() => { report.reload(); sync.reload() }}>Refresh</button>
      </PageHead>

      {silent.length > 0 && (
        <div className="notice"><b>Waiting for the extension.</b> No contact from the extension for {silent.map((f: Row) => f.name).join(' and ')} yet. Open Chrome in that firm&apos;s profile with the Seller Desk extension, and pick the firm in the extension popup. <Link to="/extension">Extension help</Link></div>
      )}

      {r && r.attention.length > 0 && (
        <div className="card">
          <h2>Needs attention <span className="pill">{r.attention.length}</span></h2>
          {r.attention.map((a: Row, i: number) => (
            <div key={i} className="row" style={{ padding: '6px 0', borderTop: i ? '1px solid var(--line)' : undefined }}>
              <span className={`status ${LEVEL_CLASS[a.level]}`}>{a.level === 'high' ? 'Urgent' : a.level === 'med' ? 'Check' : 'Info'}</span>
              <MpBadge mp={a.marketplace} /><b>{a.account}</b><span>{a.text}</span>
            </div>
          ))}
        </div>
      )}
      {r && r.attention.length === 0 && r.accounts.length > 0 && <div className="card"><b>All clear.</b> <span className="muted">Nothing needs attention right now.</span></div>}

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}><h2 style={{ margin: 0 }}>Agent summaries</h2><span className="spacer" />
          <button onClick={writeSummary} disabled={writing}>{writing ? 'Writing…' : 'Write summaries now'}</button></div>
        <div className="grid g3">
          {MPS.map((mp) => {
            const m = summaries[mp]
            return (
              <div key={mp} className="summary">
                <div className="row"><MpBadge mp={mp} /><span className="muted small">{m ? ago(m.created_at) : ''}</span></div>
                {m ? <div className={m.role === 'error' ? 'summary-err' : ''}>{m.role === 'error' ? m.content : <Markdown text={m.content} />}</div> : <span className="muted small">No summary yet. They are written after each sync.</span>}
              </div>
            )
          })}
        </div>
        <div className="muted small" style={{ marginTop: 8 }}>Written by the marketplace agents from the figures above. <Link to="/agents">Open the agents</Link> to ask follow-up questions.</div>
      </div>

      <div className="card">
        <h2>Accounts</h2>
        {!r || r.accounts.length === 0 ? <Empty>No accounts yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Account</th><th className="num">Pending</th><th>Oldest pending</th><th className="num">Overdue</th><th className="num">No stock</th><th className="num">Not on page</th><th className="num">Returns 24h</th><th>Last sync</th></tr></thead>
            <tbody>{r.accounts.map((a: Row) => (
              <tr key={a.id}>
                <td><MpBadge mp={a.marketplace} /> {a.name}<div className="muted small">{a.firm}</div></td>
                <td className="num"><b>{a.pending}</b></td>
                <td className="small">{a.oldest_pending_date ? `${a.oldest_pending_date} (${a.oldest_pending_days} d)` : '—'}</td>
                <td className="num" style={{ color: a.pending_overdue ? 'var(--err)' : undefined }}>{a.pending_overdue}</td>
                <td className="num" style={{ color: a.pending_no_stock ? 'var(--err)' : undefined }}>{a.pending_no_stock}</td>
                <td className="num" title="Marked pending in Seller Desk but not shown on the latest Pending page">{a.pending_unconfirmed}</td>
                <td className="num">{a.returns_updated_24h}</td>
                <td className="small">{a.last_sync_ok ? ago(a.last_sync_ok) : <span className="muted">never</span>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <h2>Synced pages</h2>
        {!s || s.pages.length === 0 ? <Empty>No pages yet. On an orders page of a seller panel, open the Seller Desk button → Orders → pick the account → <b>Add this page to daily sync</b>. Repeat for each tab (Pending, Shipped, Cancelled, Returns).</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Account</th><th>Page</th><th>Last read</th><th>Result</th><th /></tr></thead>
            <tbody>{s.pages.map((p: Row) => (
              <tr key={p.id}>
                <td><MpBadge mp={p.marketplace} /> {p.account_name}<div className="muted small">{p.firm}</div></td>
                <td>{p.label || p.status || 'Orders page'}<div className="muted small" title={p.url}>{p.status ? `rows without a status count as ${p.status}` : ''}</div></td>
                <td className="small">{ago(p.last_run_at)}</td>
                <td>{p.last_state ? <span className={`status ${STATE_CLASS[p.last_state]}`}>{p.last_state === 'signed_out' ? 'signed out' : p.last_state}</span> : <span className="muted">not read yet</span>}
                  {p.last_state === 'ok' && <span className="small muted"> · {p.last_rows} rows</span>}
                  {p.last_error && <div className="small" style={{ color: 'var(--err)' }}>{p.last_error}</div>}</td>
                <td className="num"><button className="ghost danger" onClick={() => removePage(p)}>Remove</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        <div className="row" style={{ marginTop: 14 }}>
          <label style={{ margin: 0 }}>Sync times (24 h, comma separated)</label>
          <input style={{ width: 240 }} value={times} onChange={(e) => setTimes(e.target.value)} placeholder="08:30, 12:30, 17:30" />
          <button onClick={saveTimes}>Save</button>
        </div>
        {s && <div className="muted small" style={{ marginTop: 8 }}>
          {s.firms.filter((f: Row) => f.pages > 0).map((f: Row) => (
            <div key={f.id}>{f.name}: {f.last_run ? `last sync ${f.last_run.status === 'done' ? ago(f.last_run.finished_at) : f.last_run.status}${f.last_run.summary ? `, ${f.last_run.summary}` : ''}` : 'no sync yet'}; extension {f.extension_seen_seconds_ago === null ? 'not seen since Seller Desk started' : `seen ${f.extension_seen_seconds_ago} s ago`}</div>
          ))}
          Chrome must be open, with the extension set to the right firm, at sync times. {MP_LABEL.meesho}, {MP_LABEL.flipkart} and {MP_LABEL.amazon} pages open in background tabs and close again.
        </div>}
      </div>
    </>
  )
}
