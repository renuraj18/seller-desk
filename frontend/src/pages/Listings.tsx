import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, money, type Row } from '../api'
import { Empty, PageHead, Status, toast, useLoad } from '../components/ui'

const STATUSES = ['draft', 'exported', 'live', 'inactive', 'rejected']

export default function Listings() {
  const [params, setParams] = useSearchParams()
  const accounts = useLoad<Row[]>(() => api.get('/api/accounts'))
  const accountId = Number(params.get('account')) || accounts.data?.[0]?.id
  const { data, reload } = useLoad<Row>(() => accountId ? api.get(`/api/accounts/${accountId}/listings`) : Promise.resolve(null), [accountId])
  const [show, setShow] = useState<'listed' | 'all'>('listed')
  const [sel, setSel] = useState<Set<number>>(new Set())

  const rows: Row[] = (data?.rows || []).filter((r: Row) => show === 'all' || r.listing)

  const saveListing = async (r: Row, patch: Row) => {
    try {
      await api.put('/api/listings', { product_id: r.product_id, account_id: accountId, ...(r.listing || {}), ...patch })
      reload()
    } catch (e) { toast.err(e) }
  }
  const addSelected = async () => {
    const r = await api.post('/api/listings/bulk-add', { account_id: accountId, product_ids: [...sel] })
    toast.ok(`${r.added} added as draft`); setSel(new Set()); reload()
  }

  return (
    <>
      <PageHead title="Listings by account" sub="Per-account SKU, price and status. Leave price blank to use the account's price rule." />
      <div className="row" style={{ marginBottom: 12 }}>
        <select style={{ width: 360 }} value={accountId || ''} onChange={(e) => setParams({ account: e.target.value })}>
          {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.marketplace.toUpperCase()} · {a.name}</option>)}
        </select>
        <select style={{ width: 200 }} value={show} onChange={(e) => setShow(e.target.value as 'listed' | 'all')}>
          <option value="listed">On this account</option><option value="all">All products</option>
        </select>
        <span className="spacer" />
        {sel.size > 0 && <button className="primary" onClick={addSelected}>Add {sel.size} to this account</button>}
      </div>
      {!accountId ? <div className="card"><Empty>Add an account first.</Empty></div> : rows.length === 0 ? (
        <div className="card"><Empty>No listings on this account yet. Switch to "All products" to add some, or sync inventory.</Empty></div>
      ) : (
        <div className="table-wrap"><table>
          <thead><tr><th /><th>Product</th><th>Marketplace SKU</th><th>ASIN / FSN / ID</th><th className="num">Cost</th><th className="num">Base</th><th className="num">Price here</th><th className="num">Stock</th><th>Status</th></tr></thead>
          <tbody>{rows.map((r) => {
            const l = r.listing
            return (
              <tr key={r.product_id}>
                <td>{!l && <input type="checkbox" checked={sel.has(r.product_id)} onChange={() => setSel((s) => { const n = new Set(s); n.has(r.product_id) ? n.delete(r.product_id) : n.add(r.product_id); return n })} />}</td>
                <td><Link to={`/products/${r.product_id}`}><code>{r.sku}</code></Link><div className="muted small">{[r.fabric, r.color].filter(Boolean).join(' · ')}</div></td>
                <td>{l ? <input className="inline-input" style={{ width: 150 }} defaultValue={l.marketplace_sku || ''} placeholder={r.effective_sku}
                  onBlur={(e) => e.target.value !== (l.marketplace_sku || '') && saveListing(r, { marketplace_sku: e.target.value })} /> : <span className="muted small">{r.effective_sku}</span>}</td>
                <td>{l ? <input className="inline-input" style={{ width: 130 }} defaultValue={l.listing_ref || ''}
                  onBlur={(e) => e.target.value !== (l.listing_ref || '') && saveListing(r, { listing_ref: e.target.value })} /> : '—'}</td>
                <td className="num">{money(r.cost_price)}</td>
                <td className="num">{money(r.base_price)}</td>
                <td className="num">{l ? <input className="inline-input" type="number" defaultValue={l.price ?? ''} placeholder={r.effective_price ?? ''}
                  onBlur={(e) => saveListing(r, { price: e.target.value === '' ? null : Number(e.target.value) })} /> : money(r.effective_price)}</td>
                <td className="num">{l?.stock_qty ?? '—'}</td>
                <td>{l ? <select className="inline-input" value={l.status} onChange={(e) => saveListing(r, { status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s}>{s}</option>)}</select> : <Status value={null} />}</td>
              </tr>
            )
          })}</tbody>
        </table></div>
      )}
    </>
  )
}
