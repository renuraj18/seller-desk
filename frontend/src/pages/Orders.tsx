import { useState } from 'react'
import { api, money, MP_LABEL, type Marketplace, type Row } from '../api'
import { Empty, FileButton, Modal, MpBadge, PageHead, toast, useLoad } from '../components/ui'

const STATUS_CLASS: Record<string, string> = {
  pending: 'st-exported', shipped: 'st-active', delivered: 'st-live', cancelled: 'st-failed', courier_return: 'st-rejected', customer_return: 'st-rejected', other: '',
}

export default function Orders() {
  const firms = useLoad<Row[]>(() => api.get('/api/firms'))
  const accounts = useLoad<Row[]>(() => api.get('/api/accounts'))
  const [f, setF] = useState<Row>({ firm_id: '', marketplace: '', status: '', date_from: '', date_to: '', q: '' })
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== '') as [string, string][]).toString()
  const { data, reload } = useLoad<Row>(() => api.get(`/api/orders?${qs}`), [qs])
  const [importing, setImporting] = useState(false)
  const [edit, setEdit] = useState<Row | null>(null)

  const save = async () => {
    try {
      await api.put(`/api/orders/${edit!.id}`, {
        status: edit!.status, awb: edit!.awb || null,
        cancel_charges: edit!.cancel_charges === '' || edit!.cancel_charges == null ? null : Number(edit!.cancel_charges),
        return_charges: edit!.return_charges === '' || edit!.return_charges == null ? null : Number(edit!.return_charges),
      })
      setEdit(null); reload(); toast.ok('Saved')
    } catch (e) { toast.err(e) }
  }
  const labels: Record<string, string> = data?.labels || {}
  return (
    <>
      <PageHead title="Orders & shipments" sub="One master list for both firms and all portals. Captured by the extension or imported from panel reports.">
        <button onClick={() => setImporting(true)}>Import report file</button>
        <a className="btn primary" href={`/api/orders/master.xlsx?${qs}`}>Download master Excel</a>
      </PageHead>
      {data && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', marginBottom: 16 }}>
          {['pending', 'shipped', 'delivered', 'cancelled', 'courier_return', 'customer_return'].map((s) => (
            <div key={s} className="card" style={{ marginBottom: 0, cursor: 'pointer', outline: f.status === s ? '2px solid var(--brand)' : undefined }}
              onClick={() => setF({ ...f, status: f.status === s ? '' : s })}>
              <div className="muted small">{labels[s]}</div><div className="stat">{data.summary[s] || 0}</div></div>
          ))}
          <div className="card" style={{ marginBottom: 0 }}><div className="muted small">Cancellation charges</div><div className="stat" style={{ fontSize: 20 }}>{money(data.charges.cancel)}</div></div>
          <div className="card" style={{ marginBottom: 0 }}><div className="muted small">Return / RTO charges</div><div className="stat" style={{ fontSize: 20 }}>{money(data.charges.returns)}</div></div>
        </div>
      )}
      <div className="row" style={{ marginBottom: 12 }}>
        <select style={{ width: 170 }} value={f.firm_id} onChange={(e) => setF({ ...f, firm_id: e.target.value })}><option value="">All firms</option>{firms.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        <select style={{ width: 150 }} value={f.marketplace} onChange={(e) => setF({ ...f, marketplace: e.target.value })}><option value="">All platforms</option>{Object.entries(MP_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select style={{ width: 190 }} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">All statuses</option>{Object.entries(labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <input style={{ width: 150 }} type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} title="From" />
        <input style={{ width: 150 }} type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} title="To" />
        <input style={{ width: 200 }} placeholder="Order ID, SKU, AWB" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
      </div>
      {data?.total === 0 ? <div className="card"><Empty>No orders yet. Open an orders page on a portal → Seller Desk extension → <b>Orders</b> → <b>Capture orders on this page</b>, or import a report file.</Empty></div> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Date</th><th>Firm</th><th>Account</th><th>Order ID</th><th>SKU</th><th className="num">MRP</th><th className="num">Price</th><th>Status</th><th className="num">Cancel ₹</th><th className="num">Return ₹</th><th /></tr></thead>
          <tbody>{data?.orders.map((o: Row) => (
            <tr key={o.id}>
              <td className="small">{o.order_date || '—'}</td><td className="small">{o.firm_name}</td>
              <td><MpBadge mp={o.marketplace as Marketplace} /> <span className="small">{o.account_name}</span></td>
              <td><code>{o.order_id}</code>{o.sub_order_id && o.sub_order_id !== o.order_id ? <div className="muted small">{o.sub_order_id}</div> : null}</td>
              <td className="small">{o.sku || '—'}</td><td className="num">{money(o.mrp)}</td><td className="num">{money(o.sale_amount)}</td>
              <td><span className={`status ${STATUS_CLASS[o.status] || ''}`}>{labels[o.status] || o.status}</span>{o.status_text && <div className="muted small">{o.status_text}</div>}</td>
              <td className="num">{o.cancel_charges ? money(o.cancel_charges) : '—'}</td><td className="num">{o.return_charges ? money(o.return_charges) : '—'}</td>
              <td className="num"><button className="ghost" onClick={() => setEdit({ ...o })}>Edit</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {data && data.total > data.orders.length && <p className="muted small">Showing {data.orders.length} of {data.total}. Download the Excel for everything.</p>}
      <p className="muted small" style={{ marginTop: 10 }}>The master Excel is also kept up to date on this PC at <code>{data?.master_path}</code>.</p>

      {importing && <ImportModal accounts={accounts.data || []} onClose={() => { setImporting(false); reload() }} />}
      {edit && (
        <Modal title={`Order ${edit.sub_order_id || edit.order_id}`} onClose={() => setEdit(null)}>
          <div className="field"><label>Status</label><select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
            {Object.entries(labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="grid g2" style={{ gap: '0 14px' }}>
            <div className="field"><label>Cancellation charges ₹</label><input type="number" value={edit.cancel_charges ?? ''} onChange={(e) => setEdit({ ...edit, cancel_charges: e.target.value })} /></div>
            <div className="field"><label>Return / RTO charges ₹</label><input type="number" value={edit.return_charges ?? ''} onChange={(e) => setEdit({ ...edit, return_charges: e.target.value })} /></div>
          </div>
          <div className="field"><label>AWB / tracking</label><input value={edit.awb || ''} onChange={(e) => setEdit({ ...edit, awb: e.target.value })} /></div>
          <div className="row"><button className="ghost danger" onClick={async () => { if (confirm('Delete this order from Seller Desk?')) { await api.del(`/api/orders/${edit.id}`); setEdit(null); reload() } }}>Delete</button>
            <span className="spacer" /><button onClick={() => setEdit(null)}>Cancel</button><button className="primary" onClick={save}>Save</button></div>
        </Modal>
      )}
    </>
  )
}

function ImportModal({ accounts, onClose }: { accounts: Row[]; onClose: () => void }) {
  const [acc, setAcc] = useState<number | ''>(accounts[0]?.id ?? '')
  const [status, setStatus] = useState('')
  const upload = async (file: File) => {
    try {
      const r = await api.upload(`/api/accounts/${acc}/orders-file`, file, { default_status: status })
      toast.ok(`${r.rows} rows: ${r.created} new, ${r.updated} updated`)
      onClose()
    } catch (e) { toast.err(e) }
  }
  return (
    <Modal title="Import orders / returns / payments report" onClose={onClose}>
      <div className="field"><label>Account the report belongs to</label><select value={acc} onChange={(e) => setAcc(Number(e.target.value))}>
        {accounts.map((a) => <option key={a.id} value={a.id}>{MP_LABEL[a.marketplace as Marketplace]} · {a.name} ({a.firm_name})</option>)}</select></div>
      <div className="field"><label>Status for rows without one</label><select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="">Read from the file</option><option>Pending</option><option>Shipped</option><option>Delivered</option><option>Cancelled</option><option value="RTO">Courier return (RTO)</option><option>Customer return</option></select>
        <div className="help">For example, choose “Customer return” for a returns report that has no status column.</div></div>
      <ul className="small muted" style={{ lineHeight: 1.6 }}>
        <li><b>Meesho</b>: Orders → download orders; Returns/RTO → download; Payments → download the payments file (has penalties and return charges).</li>
        <li><b>Flipkart</b>: Orders → download orders report; Payments → settlement report.</li>
        <li><b>Amazon</b>: Reports → Fulfilment / Order reports; Payments → transaction view download.</li>
      </ul>
      <div className="row"><span className="spacer" /><button onClick={onClose}>Cancel</button>
        <FileButton className="primary" label="Choose file…" accept=".xlsx,.xls,.csv,.txt,.tsv" onFile={upload} /></div>
    </Modal>
  )
}
