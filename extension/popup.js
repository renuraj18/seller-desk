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

chrome.storage.local.get('serverUrl').then(({ serverUrl }) => {
  urlBox.value = serverUrl || 'http://localhost:8000'
  check()
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
