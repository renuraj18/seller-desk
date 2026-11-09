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

// ---------------------------------------------------------------- automatic daily order sync
// Every minute this profile's extension asks Seller Desk whether its firm has work (a scheduled time passed, or
// "Sync now" was pressed). If so it opens each taught order page in a background tab, has the page's helper read the
// order rows, sends them to Seller Desk and closes the tab. It never clicks anything except the page's own status
// tab, and only opens pages Seller Desk lists for this firm.
let syncing = false
const call = async (path, method, body) => {
  const r = await handle({ type: 'api', path, method, body })
  if (!r.ok) throw new Error(r.error)
  return r.data
}
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms))

function waitLoaded(tabId, ms) {
  return new Promise((resolve) => {
    const done = (v) => { chrome.tabs.onUpdated.removeListener(on); clearTimeout(t); resolve(v) }
    const on = (id, info) => { if (id === tabId && info.status === 'complete') done(true) }
    const t = setTimeout(() => done(false), ms)
    chrome.tabs.onUpdated.addListener(on)
    chrome.tabs.get(tabId).then((tab) => { if (tab.status === 'complete') done(true) }).catch(() => done(false))
  })
}

async function readPage(page, skus) {
  const tab = await chrome.tabs.create({ url: page.url, active: false })
  try {
    const loaded = await waitLoaded(tab.id, 60000)
    if (!loaded) return { state: 'error', error: 'The page did not finish loading' }
    const stop = Date.now() + 25000
    while (Date.now() < stop) {
      try {
        return await chrome.tabs.sendMessage(tab.id, { type: 'sd-scan', skus, tabLabel: page.tab_label || '', timeout: 30000 })
      } catch { await sleepMs(1500) }   // the page's helper is not ready yet
    }
    // the tab loaded but the seller-panel helper never started: the browser was sent somewhere else, usually a sign-in page
    return { state: 'signed_out', error: 'The seller panel did not open (probably signed out)' }
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {})
  }
}

async function runSync() {
  const { firmId } = await chrome.storage.local.get('firmId')
  if (!firmId || syncing) return
  syncing = true
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(), 20000)
  try {
    const claim = await call('/api/ext/sync/claim', 'POST', { firm_id: firmId })
    if (!claim.run_id) return
    for (const page of claim.pages) {
      let res
      try {
        const skus = await call(`/api/ext/known-skus?account_id=${page.account_id}`)
        res = await readPage(page, skus)
      } catch (e) { res = { state: 'error', error: String(e.message || e) } }
      await call('/api/ext/sync/result', 'POST', {
        run_id: claim.run_id, page_id: page.page_id, state: res.state, rows: res.rows || [], error: res.error || null, tab_hint: res.tabHint || null,
      }).catch(() => {})
    }
    await call('/api/ext/sync/finish', 'POST', { run_id: claim.run_id })
  } catch { /* Seller Desk is not running: try again next minute */ } finally {
    clearInterval(keepAlive); syncing = false
  }
}

// ---------------------------------------------------------------- new catalog uploads
// Same minute tick. Seller Desk hands out queued sarees for this firm (never more than a few unreviewed forms at
// once). Each opens the account's taught add-catalog page in its own tab; the page's helper fills the form and
// photos. The tab stays open for you to review and submit unless Seller Desk was told to submit by itself.
let uploading = false
async function runUploads() {
  const { firmId } = await chrome.storage.local.get('firmId')
  if (!firmId || uploading || syncing) return
  uploading = true
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(), 20000)
  try {
    const claim = await call('/api/ext/upload/claim', 'POST', { firm_id: firmId })
    for (const job of claim.jobs || []) {
      const report = (status, message, detail) => call('/api/ext/upload/update', 'POST', { job_id: job.job_id, status, message, detail: detail || null }).catch(() => {})
      let tab
      try {
        tab = await chrome.tabs.create({ url: job.url, active: false })
        if (!(await waitLoaded(tab.id, 60000))) { await report('failed', 'The add-catalog page did not finish loading'); continue }
        let res = null
        const stop = Date.now() + 25000
        while (!res && Date.now() < stop) {
          try {
            res = await chrome.tabs.sendMessage(tab.id, { type: 'sd-upload', productId: job.product_id, accountId: job.account_id, submit: !!claim.submit })
          } catch { await sleepMs(1500) }
        }
        if (!res) { await report('failed', 'The seller panel did not open (probably signed out)'); continue }
        if (res.state === 'submitted') { await report('submitted', res.message, res.detail); chrome.tabs.remove(tab.id).catch(() => {}); tab = null }
        else if (res.state === 'filled') await report('filled', res.message, res.detail)
        else await report('failed', res.error || res.message || 'Could not fill the form')
      } catch (e) { await report('failed', String(e.message || e)) }
    }
  } catch { /* Seller Desk is not running: try again next minute */ } finally {
    clearInterval(keepAlive); uploading = false
  }
}

// ---------------------------------------------------------------- automatic stock push
// Seller Desk hands this firm's taught inventory pages out at the scheduled times, after order syncs, or on "Push stock now".
// Each page opens in a background tab; its helper finds every listed saree by SKU and sets the portal's stock to the master.
let pushing = false
async function runStockPush() {
  const { firmId } = await chrome.storage.local.get('firmId')
  if (!firmId || pushing || syncing || uploading) return
  pushing = true
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(), 20000)
  try {
    const claim = await call('/api/ext/stockpush/claim', 'POST', { firm_id: firmId })
    if (!claim.run_id) return
    for (const page of claim.pages) {
      let res
      try {
        const tab = await chrome.tabs.create({ url: page.url, active: false })
        try {
          if (!(await waitLoaded(tab.id, 60000))) res = { state: 'error', error: 'The page did not finish loading' }
          const stop = Date.now() + 25000
          while (!res && Date.now() < stop) {
            try { res = await chrome.tabs.sendMessage(tab.id, { type: 'sd-stock', accountId: page.account_id }) } catch { await sleepMs(1500) }
          }
          if (!res) res = { state: 'signed_out', error: 'The seller panel did not open (probably signed out)' }
        } finally { chrome.tabs.remove(tab.id).catch(() => {}) }
      } catch (e) { res = { state: 'error', error: String(e.message || e) } }
      await call('/api/ext/stockpush/result', 'POST', {
        run_id: claim.run_id, page_id: page.page_id, state: res.state, found: res.found || 0, updated: res.updated || 0,
        failed: res.failed || [], not_on_page: res.notOnPage || 0, error: res.error || null,
      }).catch(() => {})
    }
    await call('/api/ext/stockpush/finish', 'POST', { run_id: claim.run_id })
  } catch { /* Seller Desk is not running: try again next minute */ } finally {
    clearInterval(keepAlive); pushing = false
  }
}

chrome.alarms.get('sd-tick').then((a) => { if (!a) chrome.alarms.create('sd-tick', { periodInMinutes: 1 }) })
chrome.alarms.onAlarm.addListener((a) => { if (a.name === 'sd-tick') runSync().finally(runUploads).finally(runStockPush) })
chrome.runtime.onStartup.addListener(() => runSync().finally(runUploads).finally(runStockPush))
