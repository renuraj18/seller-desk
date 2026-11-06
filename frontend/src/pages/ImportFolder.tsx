import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, MP_LABEL, type Marketplace, type Row } from '../api'
import { PageHead, toast, useLoad } from '../components/ui'

type Variant = { key: string; color: string; sku: string; stock: string; files: File[]; urls: string[]; attrs: Row }
type Design = { name: string; parent: string; attrs: Row; variants: Variant[] }

const SHARED: [string, string][] = [
  ['brand', 'Brand'], ['fabric', 'Fabric'], ['saree_type', 'Type / weave'], ['occasion', 'Occasion'],
  ['selling_price', 'Base price ₹'], ['mrp', 'MRP ₹'], ['cost_price', 'Cost ₹'], ['hsn', 'HSN'], ['gst_rate', 'GST %'],
  ['blouse_piece', 'Blouse'], ['saree_length_m', 'Saree length m'], ['blouse_length_m', 'Blouse length m'], ['net_weight_g', 'Weight g'], ['wash_care', 'Wash care'],
]
const NUM = new Set(['selling_price', 'mrp', 'cost_price', 'gst_rate', 'saree_length_m', 'blouse_length_m', 'net_weight_g'])
const PER_VARIANT: [string, string][] = [['pattern', 'Pattern'], ['work', 'Work'], ['border', 'Border'], ['pallu', 'Pallu']]

const slug = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 20)
const title = (s: string) => s.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/\b\w/g, (c) => c.toUpperCase())
const natural = (a: File, b: File) => a.name.localeCompare(b.name, undefined, { numeric: true })
const isImage = (f: File) => /\.(jpe?g|png|webp)$/i.test(f.name)

function variantFromName(name: string) {
  const stem = name.replace(/\.[^.]+$/, '')
  const key = stem.replace(/[\s_-]*(\(\d+\)|\d+|front|back|side|pallu|border|blouse|close ?up|detail|drape|zoom)$/i, '')
    .replace(/[\s_-]*(\(\d+\)|\d+|front|back|side|pallu|border|blouse|close ?up|detail|drape|zoom)$/i, '').trim()
  if (!key || /^(img|dsc|image|photo|pxl|whatsapp|wa|screenshot)\b/i.test(key) || /^\d+$/.test(key)) return ''
  return key
}

function group(files: File[], subfoldersAreColours: boolean): Design[] {
  const designs = new Map<string, Map<string, File[]>>()
  const root = files[0]?.webkitRelativePath.split('/')[0] || 'Design'
  const deep = files.some((f) => f.webkitRelativePath.split('/').length >= 4)
  for (const f of files.filter(isImage)) {
    const parts = f.webkitRelativePath.split('/').slice(1, -1)
    let design: string; let variant: string
    if (deep || (!subfoldersAreColours && parts.length >= 1)) {
      design = parts[0] || root
      variant = parts[1] || variantFromName(f.name)
    } else {
      design = root
      variant = parts[0] || variantFromName(f.name)
    }
    if (!designs.has(design)) designs.set(design, new Map())
    const vs = designs.get(design)!
    vs.set(variant, [...(vs.get(variant) || []), f])
  }
  return [...designs.entries()].map(([name, vs]) => {
    const parent = slug(name)
    return {
      name, parent, attrs: {},
      variants: [...vs.entries()].map(([key, fs]) => ({
        key, color: key ? title(key) : '', sku: key ? `${parent}-${slug(key).slice(0, 10)}` : parent,
        stock: '', files: fs.sort(natural), urls: [], attrs: {},
      })),
    }
  })
}

export default function ImportFolder() {
  const nav = useNavigate()
  const accounts = useLoad<Row[]>(() => api.get('/api/accounts'))
  const [all, setAll] = useState<File[]>([])
  const [colours, setColours] = useState(true)
  const [designs, setDesigns] = useState<Design[]>([])
  const [accs, setAccs] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState('')

  const choose = (files: FileList | null) => {
    const list = [...(files || [])]
    setAll(list)
    setDesigns(group(list, colours))
  }
  const regroup = (c: boolean) => { setColours(c); setDesigns(group(all, c)) }
  const upd = (di: number, fn: (d: Design) => void) => setDesigns((ds) => {
    const n = ds.map((d) => ({ ...d, attrs: { ...d.attrs }, variants: d.variants.map((v) => ({ ...v, attrs: { ...v.attrs } })) }))
    fn(n[di]); return n
  })

  async function uploadAll(ds: Design[]) {
    const out = ds.map((d) => ({ ...d, variants: d.variants.map((v) => ({ ...v })) }))
    const pending = out.flatMap((d) => d.variants.filter((v) => !v.urls.length))
    let done = 0
    for (const v of pending) {
      const urls: string[] = []
      for (let i = 0; i < v.files.length; i += 8) {
        const fd = new FormData()
        v.files.slice(i, i + 8).forEach((f) => fd.append('files', f))
        const res = await fetch('/api/media', { method: 'POST', body: fd })
        if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed')
        urls.push(...(await res.json()).map((x: Row) => x.url))
      }
      v.urls = urls
      done++
      setBusy(`Uploading photos… ${done}/${pending.length} variants`)
    }
    setDesigns(out)
    return out
  }

  async function detect() {
    setBusy('Uploading photos…')
    try {
      const ds = await uploadAll(designs)
      let n = 0; const total = ds.reduce((s, d) => s + d.variants.length, 0)
      for (const d of ds) {
        for (const v of d.variants) {
          setBusy(`Claude is looking at the photos… ${++n}/${total}`)
          if (!v.urls[0]) continue
          const r = await api.post('/api/ai/detect-attributes', { image_url: v.urls[0] })
          if (!v.color || v.color === title(v.key)) v.color = r.color || v.color
          if (!v.key) v.sku = `${d.parent}-${slug(v.color).slice(0, 10)}`
          v.attrs = { ...v.attrs, pattern: r.pattern, work: r.work, border: r.border, pallu: r.pallu, secondary_color: r.secondary_color, _notes: r.photo_notes }
          if (!d.attrs.fabric && r.fabric_guess) d.attrs.fabric = r.fabric_guess
          if (!d.attrs.saree_type && r.saree_type_guess) d.attrs.saree_type = r.saree_type_guess
        }
      }
      setDesigns([...ds])
      toast.ok('Attributes filled from the photos — please check them')
    } catch (e) { toast.err(e) } finally { setBusy('') }
  }

  async function create() {
    setBusy('Uploading photos…')
    try {
      const ds = await uploadAll(designs)
      setBusy('Creating sarees…')
      const body = {
        account_ids: [...accs],
        designs: ds.map((d) => ({
          parent_sku: d.parent,
          attributes: Object.fromEntries(Object.entries(d.attrs).filter(([, v]) => v !== '' && v != null).map(([k, v]) => [k, NUM.has(k) ? Number(v) : v])),
          variants: d.variants.map((v) => ({
            sku: v.sku, color: v.color || null, images: v.urls, stock_qty: v.stock === '' ? null : Number(v.stock),
            attributes: Object.fromEntries(Object.entries(v.attrs).filter(([k, val]) => !k.startsWith('_') && val)),
          })),
        })),
      }
      const r = await api.post('/api/products/import-designs', body)
      toast.ok(`${r.created} sarees created${r.updated ? `, ${r.updated} updated` : ''}${accs.size ? ` and queued on ${accs.size} account(s)` : ''}`)
      r.errors?.forEach((m: string) => toast.err(m))
      nav('/products')
    } catch (e) { toast.err(e) } finally { setBusy('') }
  }

  const variantCount = designs.reduce((s, d) => s + d.variants.length, 0)
  return (
    <>
      <PageHead title="Import photo folder" sub="One folder per design, one subfolder (or file name) per colour. Photos stay on this PC.">
        <Link className="btn" to="/products">Back</Link>
      </PageHead>
      <div className="card">
        <div className="row">
          <label className="btn primary" style={{ margin: 0, color: '#fff' }}>Choose folder…
            {/* @ts-expect-error webkitdirectory is not in React's types */}
            <input type="file" webkitdirectory="" multiple hidden onChange={(e) => choose(e.target.files)} />
          </label>
          {all.length > 0 && <span className="muted">{all.filter(isImage).length} photos → {designs.length} design(s), {variantCount} colour variant(s)</span>}
          <span className="spacer" />
          <label className="row" style={{ margin: 0, color: 'var(--ink)', fontSize: 13 }}><input type="checkbox" checked={colours} onChange={(e) => regroup(e.target.checked)} /> Subfolders are colours of one design</label>
        </div>
        <div className="muted small" style={{ marginTop: 10, lineHeight: 1.6 }}>
          Layouts that work: <code>Kanchi-Butta/Maroon/1.jpg</code> · <code>Kanchi-Butta/maroon-1.jpg, green-1.jpg</code> · <code>New Arrivals/Kanchi-Butta/Maroon/1.jpg</code> (several designs).
          Photos in each colour are used in file-name order, so name the main photo 1.
        </div>
      </div>

      {designs.map((d, di) => (
        <div className="card" key={d.name}>
          <div className="row" style={{ marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>{d.name}</h2><span className="spacer" />
            <div style={{ width: 220 }}><label>Group / parent SKU</label><input value={d.parent} onChange={(e) => upd(di, (x) => {
              const old = x.parent; x.parent = slug(e.target.value)
              x.variants.forEach((v) => { if (v.sku.startsWith(old)) v.sku = x.parent + v.sku.slice(old.length) })
            })} /></div>
          </div>
          <div className="form-grid">{SHARED.map(([k, l]) => (
            <div className="field" key={k}><label>{l}</label><input type={NUM.has(k) ? 'number' : 'text'} value={d.attrs[k] ?? ''} onChange={(e) => upd(di, (x) => { x.attrs[k] = e.target.value })} /></div>
          ))}</div>
          <div className="table-wrap" style={{ marginTop: 6 }}><table>
            <thead><tr><th>Photos</th><th>Colour</th><th>SKU</th><th className="num">Stock</th>{PER_VARIANT.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
            <tbody>{d.variants.map((v, vi) => (
              <tr key={vi}>
                <td><div className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>{v.files.slice(0, 4).map((f, i) => <img key={i} className="thumb" src={URL.createObjectURL(f)} alt="" />)}
                  {v.files.length > 4 && <span className="muted small">+{v.files.length - 4}</span>}</div>
                  {v.attrs._notes && <div className="muted small" style={{ maxWidth: 220 }}>{v.attrs._notes}</div>}</td>
                <td><input className="inline-input" style={{ width: 130 }} value={v.color} onChange={(e) => upd(di, (x) => { x.variants[vi].color = e.target.value })} /></td>
                <td><input className="inline-input" style={{ width: 170 }} value={v.sku} onChange={(e) => upd(di, (x) => { x.variants[vi].sku = e.target.value.toUpperCase() })} /></td>
                <td className="num"><input className="inline-input" style={{ width: 70 }} type="number" value={v.stock} onChange={(e) => upd(di, (x) => { x.variants[vi].stock = e.target.value })} /></td>
                {PER_VARIANT.map(([k]) => <td key={k}><input className="inline-input" style={{ width: 120 }} value={v.attrs[k] || ''} onChange={(e) => upd(di, (x) => { x.variants[vi].attrs[k] = e.target.value })} /></td>)}
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      ))}

      {designs.length > 0 && (
        <div className="card">
          <h2>Queue on accounts (optional)</h2>
          <div className="row">{accounts.data?.map((a) => (
            <label key={a.id} className="row" style={{ margin: '0 12px 0 0', color: 'var(--ink)', fontSize: 13 }}>
              <input type="checkbox" checked={accs.has(a.id)} onChange={() => { const n = new Set(accs); n.has(a.id) ? n.delete(a.id) : n.add(a.id); setAccs(n) }} />
              {MP_LABEL[a.marketplace as Marketplace]} · {a.name}</label>
          ))}</div>
          <div className="row" style={{ marginTop: 14 }}>
            <button disabled={!!busy} onClick={detect}>✨ Fill colour & design from photos (AI)</button>
            <span className="spacer" />{busy && <span className="muted">{busy}</span>}
            <button className="primary" disabled={!!busy || !variantCount} onClick={create}>Create {variantCount} saree(s)</button>
          </div>
        </div>
      )}
    </>
  )
}
