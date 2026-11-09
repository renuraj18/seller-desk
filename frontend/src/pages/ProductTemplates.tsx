import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Row, money } from '../api'
import { PageHead, Modal, toast, useLoad } from '../components/ui'

export default function ProductTemplates() {
  const { data: templates, reload } = useLoad<Row[]>(() => api.get('/api/product-templates'))
  const [editing, setEditing] = useState<Row | null>(null)
  const [newOpen, setNewOpen] = useState(false)
  const nav = useNavigate()

  const handleSave = async (t: Row | null, formData: Row) => {
    try {
      if (t) {
        await api.put(`/api/product-templates/${t.id}`, formData)
        toast.ok('Template updated')
      } else {
        await api.post('/api/product-templates', formData)
        toast.ok('Template created')
      }
      setEditing(null)
      setNewOpen(false)
      reload()
    } catch (e) { toast.err(e) }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this template?')) return
    try {
      await api.del(`/api/product-templates/${id}`)
      toast.ok('Template deleted')
      reload()
    } catch (e) { toast.err(e) }
  }

  const handleApply = (template: Row) => {
    nav(`/products/new?template=${template.id}`)
  }

  return (
    <>
      <PageHead title="Product Templates" sub="Master defaults per saree type. Apply when creating products to pre-fill HSN, GST, blouse, shipping, compliance, etc.">
        <button className="primary" onClick={() => { setEditing(null); setNewOpen(true) }}>New template</button>
      </PageHead>

      {templates?.length === 0 ? (
        <div className="card"><p className="muted">No templates yet. Create one for each saree type you sell (e.g. Kanjivaram Silk, Cotton Daily Wear, Banarasi Wedding).</p></div>
      ) : (
        <div className="table-wrap"><table>
          <thead><tr>
            <th>Name</th>
            <th>Matches</th>
            <th>Tax & Price</th>
            <th>Blouse</th>
            <th>Shipping</th>
            <th>Compliance</th>
            <th style={{ width: 120 }}>Actions</th>
          </tr></thead>
          <tbody>{templates?.map((t) => (
            <tr key={t.id}>
              <td><b>{t.name}</b>{!t.active && <span className="pill" style={{ marginLeft: 8, fontSize: 11 }}>inactive</span>}</td>
              <td className="muted small">
                {t.match_fabric && <div>Fabric: {t.match_fabric}</div>}
                {t.match_saree_type && <div>Type: {t.match_saree_type}</div>}
              </td>
              <td className="small">
                <div>HSN: {t.hsn || '—'}</div>
                <div>GST: {t.gst_rate != null ? t.gst_rate + '%' : '—'}</div>
                <div>MRP: {money(t.mrp)} | Base: {money(t.selling_price)}</div>
                <div>Cost: {money(t.cost_price)} | Pkg: {money(t.packaging_cost)}</div>
              </td>
              <td className="small">
                <div>Piece: {t.blouse_piece || '—'}</div>
                <div>Len: {t.blouse_length_m || '—'} m</div>
                <div>Fabric: {t.blouse_fabric || '—'}</div>
                <div>Color: {t.blouse_color || '—'}</div>
              </td>
              <td className="small">
                <div>Net: {t.net_weight_g || '—'} g</div>
                <div>Pkg: {t.pkg_weight_g || '—'} g</div>
                <div>L×B×H: {t.pkg_length_cm || '—'}×{t.pkg_breadth_cm || '—'}×{t.pkg_height_cm || '—'} cm</div>
              </td>
              <td className="small muted">
                <div>Origin: {t.country_of_origin || 'India'}</div>
                <div>Mfr: {t.manufacturer_details ? 'Set' : '—'}</div>
                <div>Packer: {t.packer_details ? 'Set' : '—'}</div>
              </td>
              <td>
                <div className="row" style={{ gap: 4 }}>
                  <button className="ghost small" onClick={() => handleApply(t)}>Apply</button>
                  <button className="ghost small" onClick={() => setEditing(t)}>Edit</button>
                  <button className="ghost small" style={{ color: 'var(--err)' }} onClick={() => handleDelete(t.id)}>Del</button>
                </div>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}

      {(editing || newOpen) && (
        <Modal title={editing ? `Edit: ${editing.name}` : 'New Template'} onClose={() => { setEditing(null); setNewOpen(false) }} wide>
          <TemplateForm initial={editing} onSave={handleSave} onClose={() => { setEditing(null); setNewOpen(false) }} />
        </Modal>
      )}
    </>
  )
}

const GROUPS = [
  { key: 'basics', label: 'Basics & Matching', fields: ['name', 'match_fabric', 'match_saree_type', 'brand', 'active'] },
  { key: 'tax_price', label: 'Tax & Price', fields: ['hsn', 'gst_rate', 'mrp', 'selling_price', 'cost_price', 'packaging_cost'] },
  { key: 'saree', label: 'Saree Attributes', fields: ['fabric', 'saree_type', 'pattern', 'work', 'border', 'pallu', 'occasion', 'saree_length_m'] },
  { key: 'blouse', label: 'Blouse', fields: ['blouse_piece', 'blouse_length_m', 'blouse_fabric', 'blouse_color'] },
  { key: 'wash', label: 'Wash Care', fields: ['wash_care'] },
  { key: 'shipping', label: 'Shipping / Package', fields: ['net_weight_g', 'pkg_weight_g', 'pkg_length_cm', 'pkg_breadth_cm', 'pkg_height_cm'] },
  { key: 'compliance', label: 'Compliance', fields: ['country_of_origin', 'manufacturer_details', 'packer_details'] },
  { key: 'content', label: 'Content', fields: ['description', 'keywords'] },
]

const FIELD_CONFIG: Record<string, { type: string; options?: string[]; placeholder?: string; step?: number }> = {
  name: { type: 'text', placeholder: 'e.g. Kanjivaram Silk' },
  match_fabric: { type: 'text', placeholder: 'e.g. Kanjivaram Silk, Pure Silk (comma-separated)' },
  match_saree_type: { type: 'text', placeholder: 'e.g. Kanjivaram (comma-separated)' },
  brand: { type: 'text', placeholder: 'Brand name' },
  active: { type: 'checkbox', placeholder: '' },
  hsn: { type: 'text', placeholder: 'e.g. 5007' },
  gst_rate: { type: 'number', step: 0.5, placeholder: 'e.g. 5' },
  mrp: { type: 'number', step: 1, placeholder: 'e.g. 8999' },
  selling_price: { type: 'number', step: 1, placeholder: 'e.g. 7500' },
  cost_price: { type: 'number', step: 1, placeholder: 'e.g. 4500' },
  packaging_cost: { type: 'number', step: 1, placeholder: 'e.g. 50' },
  fabric: { type: 'text', placeholder: 'e.g. Kanjivaram Silk' },
  saree_type: { type: 'text', placeholder: 'e.g. Kanjivaram' },
  pattern: { type: 'text', placeholder: 'e.g. Woven Design' },
  work: { type: 'text', placeholder: 'e.g. Zari Butta' },
  border: { type: 'text', placeholder: 'e.g. Zari Border' },
  pallu: { type: 'text', placeholder: 'e.g. Heavy Zari Pallu' },
  occasion: { type: 'text', placeholder: 'e.g. Wedding' },
  saree_length_m: { type: 'number', step: 0.05, placeholder: 'e.g. 5.5' },
  blouse_piece: { type: 'select', options: ['Unstitched Blouse Piece', 'Running Blouse', 'Separate Blouse Piece', 'Without Blouse'] },
  blouse_length_m: { type: 'number', step: 0.05, placeholder: 'e.g. 0.8' },
  blouse_fabric: { type: 'text', placeholder: 'e.g. Silk' },
  blouse_color: { type: 'text', placeholder: 'e.g. Matching' },
  wash_care: { type: 'select', options: ['Dry Clean Only', 'Hand Wash', 'Machine Wash', 'Gentle Wash'] },
  net_weight_g: { type: 'number', step: 1, placeholder: 'e.g. 600' },
  pkg_weight_g: { type: 'number', step: 1, placeholder: 'e.g. 800' },
  pkg_length_cm: { type: 'number', step: 1, placeholder: 'e.g. 35' },
  pkg_breadth_cm: { type: 'number', step: 1, placeholder: 'e.g. 25' },
  pkg_height_cm: { type: 'number', step: 1, placeholder: 'e.g. 5' },
  country_of_origin: { type: 'text', placeholder: 'India' },
  manufacturer_details: { type: 'textarea', placeholder: 'Name & address of manufacturer' },
  packer_details: { type: 'textarea', placeholder: 'Name & address of packer' },
  description: { type: 'textarea', placeholder: 'Optional base description' },
  keywords: { type: 'text', placeholder: 'Comma-separated extra keywords' },
}

function TemplateForm({ initial, onSave, onClose }: { initial: Row | null; onSave: (t: Row | null, data: Row) => void; onClose: () => void }) {
  const [form, setForm] = useState<Row>(() => initial || { active: 1, country_of_origin: 'India' })

  const handleChange = (key: string, value: any) => {
    setForm((f) => ({ ...f, [key]: value }))
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave(initial, form)
  }

  return (
    <form onSubmit={submit}>
      {GROUPS.map((group) => (
        <fieldset key={group.key} style={{ marginBottom: 20, border: '1px solid var(--line)', borderRadius: 8, padding: 12 }}>
          <legend style={{ fontWeight: 600, fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>{group.label}</legend>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
            {group.fields.map((field) => {
              const cfg = FIELD_CONFIG[field]
              if (!cfg) return null
              if (cfg.type === 'checkbox') {
                return (
                  <label key={field} className="row" style={{ alignItems: 'center', gap: 6, fontSize: 13 }}>
                    <input type="checkbox" checked={!!form[field]} onChange={(e) => handleChange(field, e.target.checked)} />
                    {field === 'active' && 'Active template'}
                  </label>
                )
              }
              if (cfg.type === 'select') {
                return (
                  <label key={field} className="field">
                    <span>{field.replace(/_/g, ' ')}</span>
                    <select value={form[field] || ''} onChange={(e) => handleChange(field, e.target.value)}>
                      <option value="">—</option>
                      {cfg.options?.map((o: string) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </label>
                )
              }
              if (cfg.type === 'textarea') {
                return (
                  <label key={field} className="field" style={{ gridColumn: '1 / -1' }}>
                    <span>{field.replace(/_/g, ' ')}</span>
                    <textarea rows={3} value={form[field] || ''} onChange={(e) => handleChange(field, e.target.value)} placeholder={cfg.placeholder} />
                  </label>
                )
              }
              return (
                <label key={field} className="field">
                  <span>{field.replace(/_/g, ' ')}</span>
                  <input type={cfg.type === 'number' ? 'number' : 'text'} value={form[field] ?? ''} onChange={(e) => handleChange(field, cfg.type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value)} placeholder={cfg.placeholder} step={cfg.step} />
                </label>
              )
            })}
          </div>
        </fieldset>
      ))}
      <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" onClick={onClose}>Cancel</button>
        <button className="primary" type="submit">{initial ? 'Save changes' : 'Create template'}</button>
      </div>
    </form>
  )
}