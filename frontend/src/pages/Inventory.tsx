import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Marketplace, type Row } from '../api'
import { Empty, Modal, MpBadge, PageHead, toast, useLoad } from '../components/ui'

const REASON: Record<string, string> = { manual: 'Changed by hand', set: 'Set by hand', order_sold: 'Order', order_restock: 'Order cancelled / returned', order_deleted: 'Order record deleted', agent: 'Agent proposal', import: 'Import' }
const LEVEL_COLOR: Record<string, string> = { oversold: 'var(--err)', out: 'var(--err)', low: 'var(--warn)' }

export default function Inventory() {
  const { data, reload, setData } = useLoad<Row>(() => api.get('/api/inventory'))
  const [q, setQ] = useState('')
  const [onlyDiff, setOnlyDiff] = useState(false)
  const [level, setLevel] = useState('')
  const [history, setHistory] = useState<Row | null>(null)
  const [moves, setMoves] = useState<Row[]>([])

  const change = async (p: Row, body: Row) => {
    try {
      await api.post('/api/inventory/stock', [{ product_id: p.id, ...body }])
      const next = body.stock_qty !== undefined ? Math.max(0, body.stock_qty) : Math.max(0, (p.stock_qty || 0) + body.delta)
      setData({ ...data!, products: data!.products.map((x: Row) => (x.id === p.id ? { ...x, stock_qty: next } : x)) })
    } catch (e) { toast.err(e) }
  }
  const openHistory = async (p: Row) => {
    setHistory(p); setMoves([])
    try { setMoves((await api.get(`/api/inventory/moves?product_id=${p.id}`)).moves) } catch (e) { toast.err(e) }
  }
  const saveSettings = async (body: Row) => {
    try { await api.put('/api/inventory/settings', body); reload() } catch (e) { toast.err(e) }
  }
  if (!data) return null
  const accounts: Row[] = data.accounts
  const differs = (p: Row) => accounts.some((a) => {
    const l = p.accounts[a.id]
    return l && l.status !== 'draft' && p.stock_qty != null && l.stock !== p.stock_qty
  })
  const rows = (data.products as Row[]).filter((p) =>
    (!q || `${p.sku} ${p.color || ''} ${p.fabric || ''} ${p.parent_sku || ''}`.toLowerCase().includes(q.toLowerCase())) && (!onlyDiff || differs(p)) && (!level || p.level === level))

  return (
    <>
      <PageHead title="Inventory" sub="One master stock per saree. Push it to every account with the extension's Stock tab on each portal's inventory page.">
        <button onClick={reload}>Refresh</button>
      </PageHead>
      <div className={`notice ${data.out_of_sync ? '' : 'info'}`}>
        {data.out_of_sync ? <><b>{data.out_of_sync}</b> listing(s) show a different stock from your master stock. Open each portal's inventory page → Seller Desk → <b>Stock</b> → <b>Sync stock on this page</b>.</>
          : 'Stock on every account matches the master stock (as last seen by the extension or an inventory file).'}
      </div>
      <div className="card">
        <label className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 14 }}>
          <input type="checkbox" checked={data.settings.from_orders} onChange={(e) => {
            if (e.target.checked && !confirm('From now on, new orders take their quantity out of master stock, and cancelled or courier-returned orders put it back. Orders already in Seller Desk are never counted. Turn on?')) return
            saveSettings({ from_orders: e.target.checked })
          }} /> <b>Take stock from orders</b>
        </label>
        <div className="muted small" style={{ margin: '4px 0 8px' }}>
          {data.settings.from_orders ? <>On since {data.settings.since} (UTC). Only orders first seen after that count, and only for sarees whose SKU matches a product.
            Customer returns are not put back automatically: add the stock by hand once you have checked the saree.</> : 'Off. Master stock only changes when you change it, but every change is logged.'}
        </div>
        <div className="row"><label style={{ margin: 0 }}>Low stock at or below</label>
          <input style={{ width: 70 }} type="number" min={0} defaultValue={data.settings.low_stock_at} key={data.settings.low_stock_at}
            onBlur={(e) => Number(e.target.value) !== data.settings.low_stock_at && saveSettings({ low_stock_at: Number(e.target.value) })} />
          <span className="muted small">pieces</span></div>
        {data.unlinked_orders > 0 && <div className="small" style={{ color: 'var(--warn)', marginTop: 8 }}>
          {data.unlinked_orders} pending/shipped order(s) have a SKU that matches no product, so their stock is not tracked. Check <Link to="/matching">SKU matching</Link>.</div>}
      </div>
      <PortalSync onChange={reload} />
      <div className="row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
        {([['', 'All'], ['oversold', 'Oversold'], ['out', 'Out of stock'], ['low', 'Low']] as [string, string][]).map(([k, label]) => (
          <button key={k} className={level === k ? 'primary' : ''} onClick={() => setLevel(k)}>{label}{k ? ` (${data.counts[k] || 0})` : ''}</button>
        ))}
        <span className="spacer" />
        <input style={{ width: 280 }} placeholder="Search SKU, colour, design" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 13 }}><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> Only out of sync</label>
      </div>
      {rows.length === 0 ? <div className="card"><Empty>No sarees to show.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th /><th>SKU</th><th style={{ width: 190 }}>Master stock</th><th className="num" title="Units in pending orders">Pending</th>
            {accounts.map((a) => <th key={a.id} className="num"><MpBadge mp={a.marketplace as Marketplace} /><div className="small">{a.name}</div></th>)}</tr></thead>
          <tbody>{rows.map((p, i) => {
            const newGroup = p.parent_sku && p.parent_sku !== rows[i - 1]?.parent_sku
            return (<Fragment key={p.id}>
              {newGroup && <tr><td colSpan={4 + accounts.length} style={{ background: '#fbf8f4', fontWeight: 600 }}>{p.parent_sku} <span className="muted small">{[p.saree_type, p.fabric].filter(Boolean).join(' · ')}</span></td></tr>}
              <tr>
                <td>{p.image ? <img className="thumb" src={p.image} alt="" /> : <div className="thumb" />}</td>
                <td><Link to={`/products/${p.id}`}><code>{p.sku}</code></Link><div className="muted small">{p.color}</div></td>
                <td><div className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
                  <button className="icon" onClick={() => change(p, { delta: -1 })} title="Sold one">−1</button>
                  <input className="inline-input" style={{ width: 70, textAlign: 'right' }} type="number" key={p.stock_qty} defaultValue={p.stock_qty ?? ''}
                    onBlur={(e) => e.target.value !== String(p.stock_qty ?? '') && change(p, { stock_qty: Number(e.target.value) })} />
                  <button className="icon" onClick={() => change(p, { delta: 1 })} title="Add one">+1</button>
                  <button className="ghost" onClick={() => openHistory(p)} title="Stock history">History</button></div>
                  {LEVEL_COLOR[p.level] && <div className="small" style={{ color: LEVEL_COLOR[p.level] }}>{p.level === 'oversold' ? 'Oversold' : p.level === 'out' ? 'Out of stock' : 'Low stock'}</div>}</td>
                <td className="num">{p.pending_units || '—'}</td>
                {accounts.map((a) => {
                  const l = p.accounts[a.id]
                  if (!l) return <td key={a.id} className="num muted">—</td>
                  if (l.status === 'draft') return <td key={a.id} className="num"><span className="pill">to list</span></td>
                  const off = p.stock_qty != null && l.stock !== p.stock_qty
                  return <td key={a.id} className="num" style={{ color: off ? 'var(--warn)' : 'var(--ok)', fontWeight: off ? 700 : 500 }} title={off ? 'Different from master' : 'Matches'}>{l.stock ?? '?'}</td>
                })}
              </tr></Fragment>)
          })}</tbody>
        </table></div>
      )}
      {history && (
        <Modal title={`Stock history · ${history.sku}`} onClose={() => setHistory(null)}>
          {!moves.length ? <Empty>No changes logged yet.</Empty> : (
            <div className="table-wrap"><table>
              <thead><tr><th>When (UTC)</th><th>What</th><th className="num">Change</th><th className="num">Stock</th></tr></thead>
              <tbody>{moves.map((m) => (
                <tr key={m.id}><td className="small">{m.created_at}</td>
                  <td className="small">{REASON[m.reason] || m.reason}{m.order_ref ? ` · ${m.order_ref}` : ''}{m.account_name ? <div className="muted">{m.account_name}</div> : null}</td>
                  <td className="num" style={{ color: m.delta < 0 ? 'var(--err)' : 'var(--ok)' }}>{m.delta > 0 ? `+${m.delta}` : m.delta}</td>
                  <td className="num">{m.qty_after}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </Modal>
      )}
    </>
  )
}

function ago(ts?: string | null) {
  if (!ts) return 'never'
  const d = new Date(ts.replace(' ', 'T') + (ts.includes('T') ? '' : 'Z'))
  const m = Math.round((Date.now() - d.getTime()) / 60000)
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
}

function PortalSync({ onChange }: { onChange: () => void }) {
  const { data, reload } = useLoad<Row>(() => api.get('/api/stockpush/status'))
  const [times, setTimes] = useState('')
  const running = data?.firms?.some((f: Row) => ['requested', 'running'].includes(f.last_run?.status))
  useEffect(() => { if (data && !times) setTimes(data.times.join(', ')) }, [data, times])
  useEffect(() => {
    const t = setInterval(() => { reload(); if (running) onChange() }, running ? 5000 : 30000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])
  if (!data) return null
  const silent = data.firms.filter((f: Row) => f.pages > 0 && (f.extension_seen_seconds_ago === null || f.extension_seen_seconds_ago > 180))
  const push = async () => {
    try {
      const r = await api.post('/api/stockpush/now')
      toast.ok(r.queued.length ? `Stock push queued for ${r.queued.join(' and ')}. The extension starts within a minute.` : 'Nothing queued: no inventory pages taught, or a push is already waiting.')
      reload()
    } catch (e) { toast.err(e) }
  }
  const save = async (body: Row) => { try { await api.put('/api/stockpush/settings', body); toast.ok('Saved'); reload() } catch (e) { toast.err(e) } }
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 6 }}>
        <h2 style={{ margin: 0 }}>Push stock to the portals</h2><span className="spacer" />
        <label className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 13 }}>
          <input type="checkbox" checked={data.enabled} onChange={(e) => save({ enabled: e.target.checked })} /> Automatic</label>
        <button className="primary" onClick={push}>Push stock now</button>
      </div>
      <div className="muted small">The extension opens each taught inventory page, finds every listed saree by its SKU there, and sets the portal's stock to the master stock above. It runs at the times below and after each order sync that changes stock. Drafts and sarees with no master stock are left alone, and negative stock is sent as 0.</div>
      {silent.length > 0 && <div className="notice" style={{ marginTop: 10 }}><b>Waiting for the extension</b> in {silent.map((f: Row) => f.name).join(' and ')}&apos;s Chrome profile (pick the firm in the extension popup).</div>}
      {data.pages.length === 0 ? <div className="muted small" style={{ marginTop: 10 }}>No inventory pages yet. On each portal&apos;s inventory page open the Seller Desk panel → <b>Stock</b> → <b>Add this page to automatic stock sync</b>. Set the page to show as many rows as it allows.</div> : (
        <div className="table-wrap" style={{ marginTop: 10 }}><table>
          <thead><tr><th>Account</th><th>Page</th><th>Last run</th><th>Result</th><th /></tr></thead>
          <tbody>{data.pages.map((p: Row) => (
            <tr key={p.id}>
              <td><MpBadge mp={p.marketplace as Marketplace} /> {p.account_name}<div className="muted small">{p.firm}</div></td>
              <td className="small" title={p.url}>{p.label || 'Inventory page'}</td>
              <td className="small">{ago(p.last_run_at)}</td>
              <td className="small">{p.last_state === 'ok' ? <span className="status st-live">{p.last_rows} changed</span> : p.last_state ? <span className="status st-failed">{p.last_state === 'signed_out' ? 'signed out' : p.last_state}</span> : <span className="muted">not run yet</span>}
                {p.last_error && <div style={{ color: 'var(--warn)' }}>{p.last_error}</div>}</td>
              <td className="num"><button className="ghost danger" onClick={async () => { if (confirm('Stop syncing stock on this page?')) { await api.del(`/api/sync/pages/${p.id}`); reload() } }}>Remove</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <label style={{ margin: 0 }}>Times (24 h)</label>
        <input style={{ width: 220 }} value={times} onChange={(e) => setTimes(e.target.value)} placeholder="09:00, 13:00, 18:00" />
        <button onClick={() => save({ times: times.split(/[,\s]+/).filter(Boolean) })}>Save</button>
        <span className="spacer" />
        <span className="muted small">{data.firms.filter((f: Row) => f.pages > 0).map((f: Row) => `${f.name}: ${f.out_of_step} listing(s) out of step${f.last_run ? `, last push ${f.last_run.status === 'done' ? ago(f.last_run.finished_at) : f.last_run.status}${f.last_run.summary ? ` (${f.last_run.summary})` : ''}` : ''}`).join(' · ')}</span>
      </div>
    </div>
  )
}
