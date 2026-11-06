export type Marketplace = 'amazon' | 'flipkart' | 'meesho'
export const MARKETPLACES: Marketplace[] = ['amazon', 'flipkart', 'meesho']
export const MP_LABEL: Record<Marketplace, string> = { amazon: 'Amazon', flipkart: 'Flipkart', meesho: 'Meesho' }

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Row = Record<string, any>

export class ApiError extends Error {}

async function handle(res: Response) {
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch { /* not json */ }
    throw new ApiError(msg)
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res
}

export const api = {
  get: (url: string) => fetch(url).then(handle),
  post: (url: string, body?: unknown) =>
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) }).then(handle),
  put: (url: string, body: unknown) =>
    fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(handle),
  del: (url: string) => fetch(url, { method: 'DELETE' }).then(handle),
  upload: (url: string, file: File, fields: Record<string, string> = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    Object.entries(fields).forEach(([k, v]) => fd.append(k, v))
    return fetch(url, { method: 'POST', body: fd }).then(handle)
  },
}

export function money(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return '₹' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}
