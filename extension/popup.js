const urlBox = document.getElementById('url')
const status = document.getElementById('status')

async function check() {
  status.textContent = 'Checking…'
  status.className = 'st'
  const r = await chrome.runtime.sendMessage({ type: 'ping' }).catch((e) => ({ ok: false, error: e.message }))
  if (r && r.ok) {
    status.textContent = `Connected to ${r.server}`
    status.className = 'st ok'
  } else {
    status.textContent = 'Not connected. Is Seller Desk running? (start.bat)'
    status.className = 'st bad'
  }
}

const firmBox = document.getElementById('firm')
async function loadFirms() {
  const { firmId } = await chrome.storage.local.get('firmId')
  const r = await chrome.runtime.sendMessage({ type: 'api', path: '/api/firms' }).catch(() => null)
  if (!r || !r.ok) return
  r.data.forEach((f) => firmBox.add(new Option(f.name, f.id)))
  firmBox.value = firmId || ''
}
firmBox.addEventListener('change', async () => {
  await chrome.storage.local.set({ firmId: firmBox.value ? Number(firmBox.value) : null })
  document.getElementById('firmInfo').textContent = firmBox.value ? 'Saved. This profile will sync that firm\'s order pages.' : 'Automatic order sync is off for this profile.'
})

chrome.storage.local.get('serverUrl').then(({ serverUrl }) => {
  urlBox.value = serverUrl || 'http://localhost:8000'
  check().then(loadFirms)
})

document.getElementById('save').addEventListener('click', async () => {
  const v = urlBox.value.trim().replace(/\/+$/, '') || 'http://localhost:8000'
  await chrome.storage.local.set({ serverUrl: v })
  check()
})

document.getElementById('demo').addEventListener('click', async (e) => {
  e.preventDefault()
  const { serverUrl } = await chrome.storage.local.get('serverUrl')
  chrome.tabs.create({ url: `${(serverUrl || 'http://localhost:8000').replace(/\/+$/, '')}/ext-demo?mp=meesho` })
})
