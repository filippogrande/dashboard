
const iconMap = {
  home: '🏠',
  download: '⬇️',
  heart: '💙',
  server: '🖥️'
}

async function fetchServices(){
  const res = await fetch('/api/services')
  return res.json()
}

function statusBadge(status, color){
  const span = document.createElement('span')
  span.className = 'text-sm text-slate-500 flex items-center'
  const dot = document.createElement('span')
  dot.className = 'status-dot'
  // prefer explicit color if provided (from Kuma), otherwise derive from status
  if (color){
    dot.style.background = color
  } else if (status === 'running' || status === 'up') dot.style.background = '#16a34a'
  else if (status === 'stopped' || status === 'down') dot.style.background = '#ef4444'
  else if (status === 'missing') dot.style.background = '#9ca3af'
  else dot.style.background = '#6366f1'
  const txt = document.createElement('span')
  txt.textContent = status
  span.appendChild(dot)
  span.appendChild(txt)
  return span
}

function render(services){
  const grid = document.getElementById('grid')
  grid.innerHTML = ''
  services.forEach(s => {
    const card = document.createElement('div')
    card.className = 'bg-white rounded-xl p-4 flex items-center justify-between card-hover fade-in'
    card.style.minHeight = '76px'
    if (s.url) card.title = 'Apri ' + s.name
    card.onclick = () => { if (s.url) window.open(s.url, '_blank') }

    const left = document.createElement('div')
    left.className = 'flex items-center space-x-4'

    const icWrap = document.createElement('div')
    icWrap.className = 'w-14 h-14 rounded-lg flex items-center justify-center text-2xl font-medium text-white overflow-hidden bg-gradient-to-br from-indigo-600 to-pink-500'
    // if icon is an image filename, use it from /static/images
    if (s.icon && (s.icon.includes('.') )){
      const img = document.createElement('img')
      img.src = '/images/' + s.icon
      img.alt = s.name + ' icon'
      img.className = 'w-10 h-10 object-contain'
      img.onerror = () => { img.remove(); icWrap.textContent = iconMap[s.icon] || '🔧' }
      icWrap.appendChild(img)
    } else {
      icWrap.textContent = iconMap[s.icon] || '🔧'
    }

    const meta = document.createElement('div')
    const name = document.createElement('div')
    name.className = 'font-medium text-slate-900'
    name.textContent = s.name
    // Prefer uptime/Kuma status/color when available so UI reflects monitoring
    const badgeStatus = s.kuma_status || s.status || 'unknown'
    const badgeColor = s.kuma_color || null
    const statusEl = statusBadge(badgeStatus, badgeColor)
    meta.appendChild(name)
    meta.appendChild(statusEl)

    left.appendChild(icWrap)
    left.appendChild(meta)

    const right = document.createElement('div')
    right.className = 'flex items-center gap-2'

    // don't show controls for kuma-only monitors
    if (s.controls !== false && !s.kuma_only){
      const start = document.createElement('button')
      start.className = 'px-3 py-1 bg-emerald-600 text-white rounded-md text-sm shadow-sm'
      start.textContent = 'Avvia'
      start.onclick = async (e) => { e.stopPropagation(); await runJobAndPoll(s.name, '/api/start', start, stop); await refresh() }

      const stop = document.createElement('button')
      stop.className = 'px-3 py-1 bg-rose-600 text-white rounded-md text-sm shadow-sm'
      stop.textContent = 'Ferma'
      stop.onclick = async (e) => { e.stopPropagation(); await runJobAndPoll(s.name, '/api/stop', start, stop); await refresh() }

      right.appendChild(start)
      right.appendChild(stop)
    }

    card.appendChild(left)
    card.appendChild(right)
    grid.appendChild(card)
  })
}

async function action(name, url){
  try{
    const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})})
    return res.json()
  }catch(e){console.error(e); return {ok:false,error:e.message}}
}

async function pollJob(job_id, interval=1000){
  while(true){
    try{
      const r = await fetch('/api/job/' + job_id)
      const j = await r.json()
      if (!j.ok) return {ok:false, error:'job not found'}
      const job = j.job
      if (job.status === 'done' || job.status === 'failed') return {ok:true, job}
    }catch(e){return {ok:false,error:e.message}}
    await new Promise(res=>setTimeout(res, interval))
  }
}

async function runJobAndPoll(name, url, startBtn, stopBtn){
  if (startBtn) startBtn.disabled = true
  if (stopBtn) stopBtn.disabled = true
  const origStart = startBtn ? startBtn.textContent : null
  const origStop = stopBtn ? stopBtn.textContent : null
  if (startBtn) startBtn.textContent = '...'
  try{
    const res = await action(name, url)
    if (!res || !res.job_id){
      console.error('no job id returned', res)
      alert('Errore: nessun job_id ricevuto')
      return
    }
    const jobId = res.job_id
    const result = await pollJob(jobId)
    if (result.ok){
      const job = result.job
      if (job.status === 'done'){
        // successful
      } else {
        console.error('job failed', job)
        alert('Operazione fallita: ' + (job.result||''))
      }
    } else {
      alert('Errore job: ' + (result.error||''))
    }
  }catch(e){console.error(e); alert('Errore: '+e.message)}
  finally{
    if (startBtn) startBtn.disabled = false
    if (stopBtn) stopBtn.disabled = false
    if (startBtn) startBtn.textContent = origStart
    if (stopBtn) stopBtn.textContent = origStop
  }
}

async function refresh(){
  const services = await fetchServices()
  render(services)
}

document.getElementById('startAll').onclick = async () => { await fetch('/api/start_all', {method:'POST'}); await refresh() }
document.getElementById('stopAll').onclick = async () => { await fetch('/api/stop_all', {method:'POST'}); await refresh() }

// Theme toggle (persisted)
function applyTheme(theme){
  if (theme === 'dark') document.documentElement.classList.add('dark'), document.body.classList.add('dark')
  else document.documentElement.classList.remove('dark'), document.body.classList.remove('dark')
  const btn = document.getElementById('themeToggle')
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙'
}

function initTheme(){
  const saved = localStorage.getItem('hs_theme') || 'dark'
  applyTheme(saved)
  const btn = document.getElementById('themeToggle')
  if (!btn) return
  btn.onclick = (e)=>{
    e.stopPropagation();
    const cur = document.body.classList.contains('dark') ? 'dark' : 'light'
    const next = cur === 'dark' ? 'light' : 'dark'
    localStorage.setItem('hs_theme', next)
    applyTheme(next)
  }
}

initTheme()
refresh()
setInterval(refresh, 30000)
