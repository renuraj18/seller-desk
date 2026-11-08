import { useState } from 'react'
import { api, MARKETPLACES, MP_LABEL, type Row } from '../api'
import { Empty, Modal, MpBadge, PageHead, toast, useLoad } from '../components/ui'

const emptyAccount = { firm_id: 0, marketplace: 'amazon', name: '', seller_id: '', brand: '', sku_prefix: '', price_markup_pct: 0, price_add: 0, price_round_to: 0, active: true, notes: '' }

export default function Setup() {
  const firms = useLoad<Row[]>(() => api.get('/api/firms'))
  const accounts = useLoad<Row[]>(() => api.get('/api/accounts'))
  const [firm, setFirm] = useState<Row | null>(null)
  const [acc, setAcc] = useState<Row | null>(null)

  const saveFirm = async () => {
    try {
      if (firm!.id) await api.put(`/api/firms/${firm!.id}`, firm)
      else await api.post('/api/firms', firm)
      setFirm(null); firms.reload(); toast.ok('Firm saved')
    } catch (e) { toast.err(e) }
  }
  const saveAcc = async () => {
    try {
      const body = { ...acc, price_markup_pct: Number(acc!.price_markup_pct) || 0, price_add: Number(acc!.price_add) || 0, price_round_to: Number(acc!.price_round_to) || 0 }
      if (acc!.id) await api.put(`/api/accounts/${acc!.id}`, body)
      else await api.post('/api/accounts', body)
      setAcc(null); accounts.reload(); firms.reload(); toast.ok('Account saved')
    } catch (e) { toast.err(e) }
  }
  const delFirm = async (f: Row) => {
    if (!confirm(`Delete ${f.name} and all its accounts and listings?`)) return
    await api.del(`/api/firms/${f.id}`); firms.reload(); accounts.reload()
  }
  const delAcc = async (a: Row) => {
    if (!confirm(`Delete account ${a.name}? Its listings in Seller Desk are removed (nothing changes on the marketplace).`)) return
    await api.del(`/api/accounts/${a.id}`); accounts.reload()
  }

  return (
    <>
      <PageHead title="Firms & accounts" sub="Each marketplace account belongs to a firm (GSTIN). Prices and SKUs can differ per account." />
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0 }}>Firms</h2><span className="spacer" />
          <button className="primary" onClick={() => setFirm({ name: '', gstin: '', state: '', address: '', pincode: '' })}>Add firm</button></div>
        {firms.data?.length === 0 ? <Empty>Add your first firm.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Name</th><th>GSTIN</th><th>State</th><th className="num">Accounts</th><th /></tr></thead>
            <tbody>{firms.data?.map((f) => (
              <tr key={f.id}><td>{f.name}</td><td>{f.gstin || '—'}</td><td>{f.state || '—'}</td><td className="num">{f.account_count}</td>
                <td className="num"><button className="ghost" onClick={() => setFirm(f)}>Edit</button><button className="ghost danger" onClick={() => delFirm(f)}>Delete</button></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}><h2 style={{ margin: 0 }}>Marketplace accounts</h2><span className="spacer" />
          <button className="primary" disabled={!firms.data?.length} onClick={() => setAcc({ ...emptyAccount, firm_id: firms.data![0].id })}>Add account</button></div>
        {accounts.data?.length === 0 ? <Empty>No accounts yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Account</th><th>Firm</th><th>Brand</th><th>SKU prefix</th><th>Price rule</th><th className="num">Listings</th><th /></tr></thead>
            <tbody>{accounts.data?.map((a) => (
              <tr key={a.id}><td><MpBadge mp={a.marketplace} /> {a.name}</td><td>{a.firm_name}</td><td>{a.brand || '—'}</td><td><code>{a.sku_prefix || '—'}</code></td>
                <td className="small">{a.price_markup_pct ? `+${a.price_markup_pct}%` : 'base'}{a.price_add ? ` +₹${a.price_add}` : ''}{a.price_round_to === 9 ? ', ends in 9' : a.price_round_to ? `, round ${a.price_round_to}` : ''}</td>
                <td className="num">{a.listing_count}</td>
                <td className="num"><button className="ghost" onClick={() => setAcc(a)}>Edit</button><button className="ghost danger" onClick={() => delAcc(a)}>Delete</button></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      {firm && (
        <Modal title={firm.id ? 'Edit firm' : 'Add firm'} onClose={() => setFirm(null)}>
          {(['name', 'gstin', 'state', 'pincode'] as const).map((k) => (
            <div className="field" key={k}><label>{k === 'gstin' ? 'GSTIN' : k[0].toUpperCase() + k.slice(1)}</label>
              <input value={firm[k] || ''} onChange={(e) => setFirm({ ...firm, [k]: e.target.value })} /></div>
          ))}
          <div className="field"><label>Address</label><textarea value={firm.address || ''} onChange={(e) => setFirm({ ...firm, address: e.target.value })} />
            <div className="help">Used for Manufacturer / Packer address on marketplace forms.</div></div>
          <div className="row"><span className="spacer" /><button onClick={() => setFirm(null)}>Cancel</button><button className="primary" disabled={!firm.name} onClick={saveFirm}>Save</button></div>
        </Modal>
      )}
      {acc && (
        <Modal title={acc.id ? 'Edit account' : 'Add account'} onClose={() => setAcc(null)}>
          <div className="grid g2" style={{ gap: '0 14px' }}>
            <div className="field"><label>Firm</label><select value={acc.firm_id} onChange={(e) => setAcc({ ...acc, firm_id: Number(e.target.value) })}>
              {firms.data?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></div>
            <div className="field"><label>Marketplace</label><select value={acc.marketplace} onChange={(e) => setAcc({ ...acc, marketplace: e.target.value })}>
              {MARKETPLACES.map((m) => <option key={m} value={m}>{MP_LABEL[m]}</option>)}</select></div>
            <div className="field"><label>Account name</label><input value={acc.name} placeholder="e.g. Amazon – Shanthi Silks" onChange={(e) => setAcc({ ...acc, name: e.target.value })} /></div>
            <div className="field"><label>Seller / Supplier ID</label><input value={acc.seller_id || ''} onChange={(e) => setAcc({ ...acc, seller_id: e.target.value })} />
              <div className="help">As shown in the seller panel. The extension uses it to detect which account is logged in.</div></div>
            <div className="field"><label>Store / display name on the portal</label><input value={acc.store_name || ''} onChange={(e) => setAcc({ ...acc, store_name: e.target.value })} />
              <div className="help">Also used for account detection.</div></div>
            <div className="field"><label>Brand on this account</label><input value={acc.brand || ''} onChange={(e) => setAcc({ ...acc, brand: e.target.value })} /></div>
            <div className="field"><label>SKU prefix</label><input value={acc.sku_prefix || ''} placeholder="e.g. SS-AMZ-" onChange={(e) => setAcc({ ...acc, sku_prefix: e.target.value })} />
              <div className="help">Added to the master SKU when this account has no SKU of its own.</div></div>
            <div className="field"><label>Price markup %</label><input type="number" value={acc.price_markup_pct} onChange={(e) => setAcc({ ...acc, price_markup_pct: e.target.value })} /></div>
            <div className="field"><label>Add ₹ (e.g. for shipping)</label><input type="number" value={acc.price_add} onChange={(e) => setAcc({ ...acc, price_add: e.target.value })} /></div>
            <div className="field"><label>Rounding</label><select value={acc.price_round_to} onChange={(e) => setAcc({ ...acc, price_round_to: Number(e.target.value) })}>
              <option value={0}>None</option><option value={9}>End in 9 (₹1,249)</option><option value={10}>Nearest ₹10 up</option><option value={50}>Nearest ₹50 up</option></select></div>
          </div>
          <div className="row"><span className="spacer" /><button onClick={() => setAcc(null)}>Cancel</button><button className="primary" disabled={!acc.name} onClick={saveAcc}>Save</button></div>
        </Modal>
      )}
    </>
  )
}
