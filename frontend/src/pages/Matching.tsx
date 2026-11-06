import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, money, type Row } from '../api'
import { Empty, Modal, MpBadge, PageHead, Status, toast, useLoad } from '../components/ui'

export default function Matching() {
  const [params, setParams] = useSearchParams()
  const accounts = useLoad<Row[]>(() => api.get('/api/connections').then((d) => d.accounts))
  const accountId = Number(params.get('account')) ||
    [...(accounts.data || [])].sort((a, b) => (b.unmatched || 0) - (a.unmatched || 0))[0]?.id
  const [only, setOnly] = useState('unmatched')
  const [q, setQ] = useState('')
  const rows = useLoad<Row[]>(() => accountId ? api.get(`/api/accounts/${accountId}/remote-listings?only=${only}&q=${encodeURIComponent(q)}`) : Promise.resolve([]), [accountId, only, q])
  const products = useLoad<Row[]>(() => api.get('/api/products?limit=5000'))
  const [linking, setLinking] = useState<Row | null>(null)
  const [search, setSearch] = useState('')
  useEffect(() => setSearch(''), [linking])

  const account = accounts.data?.find((a) => a.id === accountId)
  const filtered = useMemo(() => (products.data || []).filter((p) =>
    !search || `${p.sku} ${p.name || ''} ${p.fabric || ''} ${p.color || ''}`.toLowerCase().includes(search.toLowerCase())).slice(0, 50), [products.data, search])

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast.ok(msg); rows.reload(); products.reload() } catch (e) { toast.err(e) }
  }

  return (
    <>
      <PageHead title="SKU matching" sub="Link each marketplace listing to one master product. Exact SKUs and SKUs with the account prefix match automatically.">
        {accountId && <button onClick={() => act(() => api.post(`/api/accounts/${accountId}/rematch`), 'Re-matched')}>Re-run auto match</button>}
        {accountId && only !== 'matched' && !!rows.data?.length && <button className="primary" onClick={() => {
          if (confirm('Create a master product for every unmatched listing on this account? Fabric / colour are guessed from the title; review them after.'))
            act(() => api.post(`/api/accounts/${accountId}/create-all-unmatched`), 'Products created')
        }}>Create products for all unmatched</button>}
      </PageHead>
      <div className="row" style={{ marginBottom: 14 }}>
        <select style={{ width: 360 }} value={accountId || ''} onChange={(e) => setParams({ account: e.target.value })}>
          {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.marketplace.toUpperCase()} · {a.name}{a.unmatched ? ` (${a.unmatched} unmatched)` : ''}</option>)}
        </select>
        <select style={{ width: 160 }} value={only} onChange={(e) => setOnly(e.target.value)}>
          <option value="unmatched">Unmatched</option><option value="matched">Matched</option><option value="all">All</option>
        </select>
        <input style={{ width: 240 }} placeholder="Search SKU, title, ASIN/FSN" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {!account ? <div className="card"><Empty>Add an account and sync its inventory first.</Empty></div>
        : rows.data?.length === 0 ? <div className="card"><Empty>{only === 'unmatched' ? 'Nothing left to match 🎉' : 'No listings. Sync or upload the inventory on Connections.'}</Empty></div> : (
          <div className="table-wrap"><table>
            <thead><tr><th /><th>Marketplace SKU</th><th>Title</th><th>{account.marketplace === 'amazon' ? 'ASIN' : account.marketplace === 'flipkart' ? 'FSN' : 'Catalog ID'}</th>
              <th className="num">Price</th><th className="num">Stock</th><th>Status</th><th>Master product</th><th /></tr></thead>
            <tbody>{rows.data?.map((r) => (
              <tr key={r.id}>
                <td>{r.image ? <img className="thumb" src={r.image} alt="" /> : null}</td>
                <td><code>{r.remote_sku}</code></td>
                <td style={{ maxWidth: 340 }} className="small">{r.title || '—'}</td>
                <td className="small">{r.listing_ref || '—'}</td>
                <td className="num">{money(r.price)}</td><td className="num">{r.stock ?? '—'}</td><td><Status value={r.status} /></td>
                <td>{r.product_id ? <><Link to={`/products/${r.product_id}`}>{r.product_sku}</Link> <span className="pill">{r.match_method}</span></> : <span className="muted">—</span>}</td>
                <td className="num"><div className="actions" style={{ justifyContent: 'flex-end' }}>
                  {r.product_id ? <button className="ghost" onClick={() => act(() => api.post(`/api/remote-listings/${r.id}/unlink`), 'Unlinked')}>Unlink</button> : <>
                    <button onClick={() => setLinking(r)}>Link…</button>
                    <button className="primary" onClick={() => act(() => api.post(`/api/remote-listings/${r.id}/create-product`, {}), 'Product created')}>Create product</button>
                  </>}
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      {linking && (
        <Modal title={`Link ${linking.remote_sku}`} onClose={() => setLinking(null)}>
          <p className="small muted">{linking.title}</p>
          <input autoFocus placeholder="Search master products" value={search} onChange={(e) => setSearch(e.target.value)} />
          <div style={{ maxHeight: 340, overflowY: 'auto', marginTop: 10 }}>
            {filtered.map((p) => (
              <div key={p.id} className="row" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                <code>{p.sku}</code><span className="small">{[p.name, p.fabric, p.color].filter(Boolean).join(' · ')}</span><span className="spacer" />
                <button onClick={() => { act(() => api.post(`/api/remote-listings/${linking.id}/link`, { product_id: p.id }), 'Linked'); setLinking(null) }}>Link</button>
              </div>
            ))}
            {filtered.length === 0 && <p className="muted small">No products found.</p>}
          </div>
        </Modal>
      )}
      {account && <p className="muted small" style={{ marginTop: 10 }}><MpBadge mp={account.marketplace} /> Amazon: if the same saree sells on two Amazon accounts, both must use the same ASIN. Never create a second ASIN for it.</p>}
    </>
  )
}
