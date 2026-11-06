import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { MP_LABEL, type Marketplace } from '../api'

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const reload = useCallback(() => {
    setLoading(true)
    fn().then((d) => { setData(d); setError('') }).catch((e) => setError(String(e.message || e))).finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  return { data, error, loading, reload, setData }
}

type ToastT = { id: number; text: string; kind: 'ok' | 'err' }
let pushToast: (t: Omit<ToastT, 'id'>) => void = () => {}
export const toast = {
  ok: (text: string) => pushToast({ text, kind: 'ok' }),
  err: (e: unknown) => pushToast({ text: e instanceof Error ? e.message : String(e), kind: 'err' }),
}
export function Toasts() {
  const [items, setItems] = useState<ToastT[]>([])
  const n = useRef(0)
  useEffect(() => {
    pushToast = (t) => {
      const id = ++n.current
      setItems((x) => [...x, { ...t, id }])
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.kind === 'err' ? 7000 : 3500)
    }
  }, [])
  return <div className="toasts">{items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}</div>
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{sub && <p className="muted">{sub}</p>}</div>
      <div className="actions">{children}</div>
    </div>
  )
}

export function MpBadge({ mp }: { mp: Marketplace }) {
  return <span className={`mp mp-${mp}`}>{MP_LABEL[mp]}</span>
}

export function Status({ value }: { value?: string | null }) {
  if (!value) return <span className="muted">—</span>
  return <span className={`status st-${value.toLowerCase().replace(/[^a-z]/g, '')}`}>{value}</span>
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`}>
        <div className="modal-head"><h3>{title}</h3><button className="ghost icon" onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  )
}

export function FileButton({ label, accept, onFile, className = '' }: { label: string; accept?: string; onFile: (f: File) => void; className?: string }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <button className={className} onClick={() => ref.current?.click()}>{label}</button>
      <input ref={ref} type="file" hidden accept={accept} onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
    </>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Score({ value }: { value?: number | null }) {
  if (value === null || value === undefined) return null
  const cls = value >= 85 ? 'good' : value >= 65 ? 'mid' : 'low'
  return <span className={`score ${cls}`} title="SEO score">{value}</span>
}

export function Counter({ n, max }: { n: number; max: number }) {
  if (!max) return null
  return <span className={`counter ${n > max ? 'over' : ''}`}>{n}/{max}</span>
}
