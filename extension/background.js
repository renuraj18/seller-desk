// Seller Desk extension service worker: the only part that talks to the Seller Desk app on this PC.
const DEFAULT_SERVER = 'http://localhost:8000'

async function serverUrl() {
  const { serverUrl } = await chrome.storage.local.get('serverUrl')
  return (serverUrl || DEFAULT_SERVER).replace(/\/+$/, '')
}

function toBase64(buf) {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

async function handle(msg) {
  const base = await serverUrl()
  if (msg.type === 'api') {
    if (!String(msg.path).startsWith('/api/')) return { ok: false, error: 'Bad path' }
    const res = await fetch(base + msg.path, {
      method: msg.method || 'GET',
      headers: msg.body ? { 'Content-Type': 'application/json' } : {},
      body: msg.body ? JSON.stringify(msg.body) : undefined,
    })
    const text = await res.text()
    let data
    try { data = JSON.parse(text) } catch { data = text }
    if (!res.ok) return { ok: false, error: (data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `${res.status} ${res.statusText}` }
    return { ok: true, data }
  }
  if (msg.type === 'image') {
    const res = await fetch(`${base}/api/ext/image?url=${encodeURIComponent(msg.url)}`)
    if (!res.ok) {
      let detail = res.statusText
      try { detail = (await res.json()).detail } catch { /* not json */ }
      return { ok: false, error: detail }
    }
    const blob = await res.blob()
    return { ok: true, type: blob.type || 'image/jpeg', b64: toBase64(await blob.arrayBuffer()) }
  }
  if (msg.type === 'ping') {
    const res = await fetch(`${base}/api/ext/ping`)
    return { ok: res.ok, server: base }
  }
  return { ok: false, error: 'Unknown message' }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handle(msg).then(sendResponse, (e) => sendResponse({ ok: false, error: `Seller Desk not reachable (${e.message || e})` }))
  return true
})
