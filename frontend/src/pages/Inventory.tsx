import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Marketplace, type Row } from '../api'
import { Empty, MpBadge, PageHead, toast, useLoad } from '../components/ui'

export default function Inventory() {
  const { data, reload, setData } = useLoad<Row>(() => api.get('/api/inventory'))
  const [q, setQ] = useState('')
  const [onlyDiff, setOnlyDiff] = useState(false)

  const change = async (p: Row, body: Row) => {
    try {
      await api.post('/api/inventory/stock', [{ product_id: p.id, ...body }])
      const next = body.stock_qty !== undefined ? Math.max(0, body.stock_qty) : Math.max(0, (p.stock_qty || 0) + body.delta)
      setData({ ...data!, products: data!.products.map((x: Row) => (x.id === p.id ? { ...x, stock_qty: next } : x)) })
    } catch (e) { toast.err(e) }
  }
  if (!data) return null
  const accounts: Row[] = data.accounts
  const differs = (p: Row) => accounts.some((a) => {
    const l = p.accounts[a.id]
    return l && l.status !== 'draft' && p.stock_qty != null && l.stock !== p.stock_qty
  })
  const rows = (data.products as Row[]).filter((p) =>
    (!q || `${p.sku} ${p.color || ''} ${p.fabric || ''} ${p.parent_sku || ''}`.toLowerCase().includes(q.toLowerCase())) && (!onlyDiff || differs(p)))

  return (
    <>
      <PageHead title="Inventory" sub="One master stock per saree. Push it to every account with the extension's Stock tab on each portal's inventory page.">
        <button onClick={reload}>Refresh</button>
      </PageHead>
      <div className={`notice ${data.out_of_sync ? '' : 'info'}`}>
        {data.out_of_sync ? <><b>{data.out_of_sync}</b> listing(s) show a different stock from your master stock. Open each portal's inventory page → Seller Desk → <b>Stock</b> → <b>Sync stock on this page</b>.</>
          : 'Stock on every account matches the master stock (as last seen by the extension or an inventory file).'}
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <input style={{ width: 280 }} placeholder="Search SKU, colour, design" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 13 }}><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> Only out of sync</label>
      </div>
      {rows.length === 0 ? <div className="card"><Empty>No sarees to show.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th /><th>SKU</th><th style={{ width: 190 }}>Master stock</th>
            {accounts.map((a) => <th key={a.id} className="num"><MpBadge mp={a.marketplace as Marketplace} /><div className="small">{a.name}</div></th>)}</tr></thead>
          <tbody>{rows.map((p, i) => {
            const newGroup = p.parent_sku && p.parent_sku !== rows[i - 1]?.parent_sku
            return (<Fragment key={p.id}>
              {newGroup && <tr><td colSpan={3 + accounts.length} style={{ background: '#fbf8f4', fontWeight: 600 }}>{p.parent_sku} <span className="muted small">{[p.saree_type, p.fabric].filter(Boolean).join(' · ')}</span></td></tr>}
              <tr>
                <td>{p.image ? <img className="thumb" src={p.image} alt="" /> : <div className="thumb" />}</td>
                <td><Link to={`/products/${p.id}`}><code>{p.sku}</code></Link><div className="muted small">{p.color}</div></td>
                <td><div className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
                  <button className="icon" onClick={() => change(p, { delta: -1 })} title="Sold one">−1</button>
                  <input className="inline-input" style={{ width: 70, textAlign: 'right' }} type="number" key={p.stock_qty} defaultValue={p.stock_qty ?? ''}
                    onBlur={(e) => e.target.value !== String(p.stock_qty ?? '') && change(p, { stock_qty: Number(e.target.value) })} />
                  <button className="icon" onClick={() => change(p, { delta: 1 })} title="Add one">+1</button></div></td>
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
    </>
  )
}
