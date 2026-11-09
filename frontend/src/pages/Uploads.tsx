import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Marketplace, type Row } from '../api'
import { Empty, MpBadge, PageHead, toast, useLoad } from '../components/ui'

const STATUS_LABEL: Record<string, string> = { queued: 'Waiting', filling: 'Filling now', filled: 'Filled: review & submit', submitted: 'Submitted', failed: 'Needs attention', cancelled: 'Cancelled' }
const STATUS_CLASS: Record<string, string> = { queued: 'st-exported', filling: 'st-active', filled: 'st-active', submitted: 'st-live', failed: 'st-failed', cancelled: '' }
const REQUIRED: [string, string][] = [['fabric', 'fabric'], ['color', 'colour'], ['mrp', 'MRP'], ['selling_price', 'selling price'], ['hsn', 'HSN']]

const missing = (p: Row) => [...REQUIRED.filter(([k]) => p[k] == null || p[k] === '').map(([, l]) => l), ...((p.images || []).length ? [] : ['photos'])]

export default function Uploads() {
  const jobs = useLoad<Row>(() => api.get('/api/uploads'))
  const [q, setQ] = useState('')
  const products = useLoad<Row[]>(() => api.get(`/api/products?q=${encodeURIComponent(q)}`), [q])
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [accs, setAccs] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [skipped, setSkipped] = useState<Row[]>([])

  const active = jobs.data && (jobs.data.counts.queued + jobs.data.counts.filling + jobs.data.counts.filled) > 0
  useEffect(() => {
    if (!active) return
    const t = setInterval(jobs.reload, 8000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  const toggle = <T,>(set: Set<T>, v: T, put: (s: Set<T>) => void) => { const n = new Set(set); n.has(v) ? n.delete(v) : n.add(v); put(n) }

  const queue = async () => {
    setBusy(true)
    try {
      const r = await api.post('/api/uploads/queue', { product_ids: [...sel], account_ids: [...accs] })
      setSkipped(r.skipped)
      toast.ok(r.queued ? `${r.queued} queued. The extension in each firm's Chrome picks them up within a minute.` : 'Nothing was queued')
      r.splits?.forEach((s: Row) => toast.ok(`${s.sku} on ${s.account}: ${s.catalogs.reduce((a: number, b: number) => a + b, 0)} colours split into ${s.catalogs.length} catalogs (${s.catalogs.join(' + ')}), at most ${s.limit} each`))
      if (r.queued) setSel(new Set())
      jobs.reload()
    } catch (e) { toast.err(e) } finally { setBusy(false) }
  }
  const mark = async (id: number, status: string) => {
    try { await api.post(`/api/uploads/${id}/status`, { status }); jobs.reload() } catch (e) { toast.err(e) }
  }
  const setPaused = async (on: boolean) => {
    try { await api.put('/api/uploads/settings', { paused: on }); jobs.reload() } catch (e) { toast.err(e) }
  }
  const setAuto = async (on: boolean) => {
    if (on && !confirm('Seller Desk will click Submit on the portal by itself when a form is filled without problems. Turn on?')) return
    try { await api.put('/api/uploads/settings', { auto_submit: on }); jobs.reload() } catch (e) { toast.err(e) }
  }

  const d = jobs.data
  const accounts: Row[] = d?.accounts || []
  const readyIds = (products.data || []).filter((p) => !missing(p).length).map((p) => p.id)
  return (
    <>
      <PageHead title="4a. Upload with the extension" sub={<>Pick sarees and accounts. The Seller Desk extension fills each portal's add-catalog form, and you review and submit. Prefer a file? <Link to="/templates">4b. Excel template</Link>.</>}>
        <button onClick={jobs.reload}>Refresh</button>
      </PageHead>

      {d && (
        <div className="card">
          <h2>1. Where to upload</h2>
          <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
            {accounts.map((a) => (
              <label key={a.id} className="row" style={{ margin: 0, gap: 6, color: 'var(--ink)', fontSize: 13, opacity: a.add_catalog_url ? 1 : 0.55 }}
                title={a.add_catalog_url ? 'Add-catalog page taught' : 'Open this account\'s add-catalog page on the portal, then Seller Desk extension → Use this page'}>
                <input type="checkbox" checked={accs.has(a.id)} onChange={() => toggle(accs, a.id, setAccs)} />
                <MpBadge mp={a.marketplace as Marketplace} /> {a.name} <span className="muted small">{a.firm}</span>
                {!a.add_catalog_url && <span className="pill">page not taught</span>}
              </label>
            ))}
          </div>
          <div className="muted small" style={{ marginTop: 8 }}>The extension must be open in that firm's Chrome profile (pick the firm in its popup). <Link to="/extension">Extension help</Link></div>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>2. Which sarees</h2><span className="spacer" />
          <input style={{ width: 220 }} placeholder="Search SKU, colour, fabric" value={q} onChange={(e) => setQ(e.target.value)} />
          <button onClick={() => setSel(new Set(readyIds))}>Select all ready</button>
          <button className="primary" disabled={busy || !sel.size || !accs.size} onClick={queue}>Add {sel.size || ''} to queue</button>
        </div>
        {!products.data?.length ? <Empty>No sarees yet. Add them under <Link to="/products">Products</Link>.</Empty> : (
          <div className="table-wrap" style={{ maxHeight: 320, overflow: 'auto' }}><table>
            <thead><tr><th /><th>SKU</th><th>Design</th><th>Ready?</th></tr></thead>
            <tbody>{products.data.map((p) => {
              const miss = missing(p)
              return (
                <tr key={p.id}>
                  <td><input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(sel, p.id, setSel)} /></td>
                  <td><Link to={`/products/${p.id}`}><code>{p.sku}</code></Link></td>
                  <td className="small">{[p.parent_sku, p.color, p.fabric].filter(Boolean).join(' · ')}</td>
                  <td className="small">{miss.length ? <span style={{ color: 'var(--warn)' }}>Missing {miss.join(', ')}</span> : <span style={{ color: 'var(--ok)' }}>Ready</span>}</td>
                </tr>
              )
            })}</tbody>
          </table></div>
        )}
        {skipped.length > 0 && (
          <div className="notice" style={{ marginTop: 10 }}><b>Not queued:</b>
            {skipped.map((s, i) => <div key={i} className="small">{s.sku} on {s.account}: {s.reason}</div>)}
          </div>
        )}
        <div className="muted small" style={{ marginTop: 8 }}>All colour variants of a design go into one catalog form together. Meesho takes at most 9 per catalog, so a bigger design is split into catalogs of 9 (parent SKU, then -2, -3…).</div>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>3. Queue</h2><span className="spacer" />
          <button className={d?.paused ? 'primary' : ''} onClick={() => setPaused(!d?.paused)} title="Paused: the extension takes no new sarees. A form already being filled can be stopped with its Stop button on the portal page.">{d?.paused ? '▶ Resume queue' : '⏸ Pause queue'}</button>
          <label className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 13 }}>
            <input type="checkbox" checked={!!d?.auto_submit} onChange={(e) => setAuto(e.target.checked)} /> Submit by itself when the form is filled without problems
          </label>
        </div>
        {d && <div className="muted small" style={{ marginBottom: 8 }}>At most {d.max_open} filled forms per firm wait open for your review; the rest stay queued until you submit or cancel some.</div>}
        {!d?.jobs.length ? <Empty>Nothing queued yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Saree</th><th>Account</th><th>Status</th><th>Updated</th><th /></tr></thead>
            <tbody>{d.jobs.map((j: Row) => (
              <tr key={j.id}>
                <td><Link to={`/products/${j.product_id}`}><code>{j.catalog_parent_sku || j.parent_sku || j.sku}</code></Link><div className="muted small">{j.catalog_size > 1 ? `${j.catalog_size} colours in this catalog` : j.color}</div></td>
                <td><MpBadge mp={j.marketplace as Marketplace} /> <span className="small">{j.account_name}</span><div className="muted small">{j.firm}</div></td>
                <td><span className={`status ${STATUS_CLASS[j.status]}`}>{STATUS_LABEL[j.status]}</span>{j.message && <div className="small muted">{j.message}</div>}
                  {j.detail && <details className="small"><summary>What was filled ({j.detail.counts.filled} fields, {j.detail.images} photos)</summary>
                    {j.detail.problems.map((x: Row, i: number) => <div key={i}>{x.status}: <b>{x.label}</b>{x.reason ? ` (${x.reason})` : ''}{x.options?.length ? `: ${x.options.join(', ')}` : ''}</div>)}
                    {!j.detail.problems.length && <div>No unfilled fields.</div>}</details>}</td>
                <td className="small">{j.updated_at}</td>
                <td className="num">
                  {['filled', 'failed'].includes(j.status) && <button onClick={() => mark(j.id, 'submitted')}>I submitted it</button>}{' '}
                  {['queued', 'failed'].includes(j.status) && j.status === 'failed' && <button onClick={() => mark(j.id, 'queued')}>Retry</button>}{' '}
                  {['queued', 'filling', 'filled', 'failed'].includes(j.status) && <button className="ghost danger" onClick={() => mark(j.id, 'cancelled')}>Cancel</button>}
                  {j.status === 'cancelled' && <button onClick={() => mark(j.id, 'queued')}>Queue again</button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </>
  )
}
