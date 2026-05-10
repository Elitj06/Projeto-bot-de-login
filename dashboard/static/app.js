/**
 * SEAP Sniper Dashboard v4 — Full rewrite.
 * Sniper engine, calendar, NTP sync, real-time countdown.
 */
const API = "";
let socket = null;
let jwtToken = localStorage.getItem("seap_jwt") || null;
let userStatuses = {};
let sniperLog = [];
let countdownInterval = null;
let currentScheduleUserId = null;

const DAYS = ["seg","ter","qua","qui","sex","sab","dom"];
const DAY_LABELS = {seg:"Segunda",ter:"Terça",qua:"Quarta",qui:"Quinta",sex:"Sexta",sab:"Sábado",dom:"Domingo"};
const TIME_SLOTS = ["06:00-08:00","08:00-10:00","10:00-12:00","12:00-14:00","14:00-16:00","16:00-18:00","18:00-20:00","20:00-22:00"];

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    if (jwtToken) checkAuth(); else showLogin();
});

function showLogin() {
    document.getElementById("login-screen").classList.remove("hidden");
    document.getElementById("main-app").classList.add("hidden");
}

function showApp() {
    document.getElementById("login-screen").classList.add("hidden");
    document.getElementById("main-app").classList.remove("hidden");
    initWebSocket();
    loadUsers();
    loadProxies();
    loadSniperStatus();
    updateClock();
    setInterval(updateClock, 1000);
    setInterval(loadSniperStatus, 10000);
    startCountdown();
    ntpSync();

    ["new-username","new-password","new-proxy"].forEach(id => {
        document.getElementById(id).addEventListener("keydown", e => { if(e.key==="Enter")addUser(); });
    });
}

async function checkAuth() {
    try {
        const res = await fetch(`${API}/api/auth/status`, {headers:{Authorization:`Bearer ${jwtToken}`}});
        const data = await res.json();
        if (data.authenticated) showApp(); else { localStorage.removeItem("seap_jwt"); jwtToken=null; showLogin(); }
    } catch { showLogin(); }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
async function doLogin() {
    const u = document.getElementById("login-user").value.trim();
    const p = document.getElementById("login-pass").value.trim();
    const err = document.getElementById("login-error");
    if (!u||!p) { err.textContent="Preencha tudo"; err.classList.remove("hidden"); return; }
    try {
        const res = await fetch(`${API}/api/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:u,password:p})});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        jwtToken = data.token; localStorage.setItem("seap_jwt",jwtToken); err.classList.add("hidden"); showApp();
    } catch(e) { err.textContent=e.message; err.classList.remove("hidden"); }
}

function doLogout() { localStorage.removeItem("seap_jwt"); jwtToken=null; showLogin(); }

async function apiCall(url, method="GET", body=null) {
    const opts = {method, headers:{"Content-Type":"application/json","Authorization":`Bearer ${jwtToken}`}};
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(`${API}${url}`, opts);
        if (res.status===401) { doLogout(); throw new Error("Sessão expirada"); }
        const data = await res.json();
        if (!res.ok) throw new Error(data.error||`HTTP ${res.status}`);
        return data;
    } catch(e) { showToast(e.message,"error"); throw e; }
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function initWebSocket() {
    socket = io({transports:["websocket","polling"]});
    socket.on("connect", () => updateConnectionStatus(true));
    socket.on("disconnect", () => updateConnectionStatus(false));
    socket.on("status_update", d => handleStatusUpdate(d));
}

function updateConnectionStatus(ok) {
    const ind = document.getElementById("ws-indicator");
    const st = document.getElementById("connection-status");
    if (ok) { ind.className="w-3 h-3 rounded-full bg-green-500 pulse-dot"; if(st){st.textContent="Conectado";st.className="text-sm text-green-400";} }
    else { ind.className="w-3 h-3 rounded-full bg-red-500"; if(st){st.textContent="Off";st.className="text-sm text-red-400";} }
}

function handleStatusUpdate(data) {
    const uid = data.user_id;
    if (uid === "__all__") {
        addSniperLog(`[${data.type}] ${JSON.stringify(data).slice(0,120)}`);
        if (data.type === "fired") {
            showToast(`🔥 FIRE! Offset: ${data.offset_ms}ms`, "success");
            setPipelineStep("fire");
        } else if (data.type === "prewarm_complete") {
            showToast(`Pre-warm: ${data.ready} prontos`, "info");
            setPipelineStep("prewarm");
        } else if (data.type === "armed") {
            showToast(`🎯 Armado! NTP: ${data.ntp_offset_ms}ms`, "warning");
            setPipelineStep("arm");
        } else if (data.type === "hunt_complete") {
            showToast(`Hunt: ${data.successes} vagas`, "success");
            setPipelineStep("hunt");
        }
        return;
    }
    userStatuses[uid] = data;
}

// ---------------------------------------------------------------------------
// Sniper
// ---------------------------------------------------------------------------
async function loadSniperStatus() {
    try {
        const data = await apiCall("/api/sniper/status");
        document.getElementById("stat-users").textContent = data.users?.total||0;
        document.getElementById("stat-active").textContent = data.users?.active||0;
        document.getElementById("stat-proxies").textContent = `${data.proxies?.active||0}/${data.proxies?.total||0}`;
        document.getElementById("stat-browsers").textContent = data.users_ready||0;
        document.getElementById("stat-sniper").textContent = (data.status||"IDLE").toUpperCase();

        const ntpMs = data.ntp?.offset_ms||0;
        document.getElementById("ntp-badge").textContent = `NTP: ${ntpMs>0?'+':''}${ntpMs}ms`;
        document.getElementById("ntp-offset").textContent = `${ntpMs>0?'+':''}${ntpMs}ms`;
        document.getElementById("ntp-offset").className = `text-2xl font-mono ${Math.abs(ntpMs)<10?'text-green-400':Math.abs(ntpMs)<50?'text-yellow-400':'text-red-400'}`;

        document.getElementById("sniper-status-text").textContent = (data.status||"IDLE").toUpperCase();
        document.getElementById("sniper-status-text").className = `text-2xl font-bold ${
            data.status==="idle"?"text-gray-400":data.status==="armed"?"text-yellow-400":
            data.status==="firing"?"text-red-400":data.status==="hunting"?"text-purple-400":
            data.status==="complete"?"text-green-400":"text-gray-400"
        }`;
    } catch {}
}

async function ntpSync() {
    try {
        const data = await apiCall("/api/sniper/ntp-sync","POST");
        showToast(`NTP sync: ${data.offset_ms}ms (${data.servers_used} servers)`, "success");
        loadSniperStatus();
    } catch {}
}

async function sniperPrewarm() {
    showToast("Pre-warming browsers...","info");
    try {
        const data = await apiCall("/api/sniper/prewarm","POST");
        showToast(`${data.ready} browsers prontos, ${data.failed} falharam`, data.failed>0?"warning":"success");
        setPipelineStep("prewarm");
    } catch {}
}

async function sniperArm() {
    showToast("Armando sniper...","warning");
    try {
        const data = await apiCall("/api/sniper/arm","POST");
        showToast(`Armado! Offset: ${data.offset_ms}ms`,"success");
        setPipelineStep("arm");
    } catch {}
}

async function sniperFire() {
    showToast("🔥 DISPARANDO!","error");
    try {
        const data = await apiCall("/api/sniper/fire","POST");
        showToast(`${data.successes}/${data.total} logins OK`, data.successes===data.total?"success":"warning");
        setPipelineStep("fire");
    } catch {}
}

async function sniperExecute() {
    if (!confirm("⚠️ EXECUTAR PIPELINE COMPLETO?\n\nPre-warm → NTP Sync → Arm → Fire → Hunt\n\nOs browsers vão abrir e aguardar até 06h BRT para disparar.")) return;
    showToast("🚀 Pipeline completo iniciado!","warning");
    addSniperLog("🚀 Pipeline completo iniciado");
    try {
        const data = await apiCall("/api/sniper/execute","POST");
        showToast(`Pipeline: ${data.successes} sucessos em ${data.total_attempts} tentativas`, "success");
        addSniperLog(`✅ Pipeline completo: ${JSON.stringify(data).slice(0,200)}`);
    } catch {}
}

async function sniperCancel() {
    try {
        await apiCall("/api/sniper/cancel","POST");
        showToast("Sniper cancelado","info");
        resetPipeline();
    } catch {}
}

function setPipelineStep(step) {
    const steps = ["prewarm","ntp","arm","fire","hunt"];
    const idx = steps.indexOf(step);
    steps.forEach((s,i) => {
        const el = document.getElementById(`step-${s}`);
        if (i < idx) el.className = "px-3 py-1 rounded bg-green-900 text-green-300";
        else if (i === idx) el.className = "px-3 py-1 rounded bg-yellow-900 text-yellow-300 pulse-dot";
        else el.className = "px-3 py-1 rounded bg-gray-700 text-gray-400";
    });
}

function resetPipeline() {
    ["prewarm","ntp","arm","fire","hunt"].forEach(s => {
        document.getElementById(`step-${s}`).className = "px-3 py-1 rounded bg-gray-700 text-gray-400";
    });
}

function addSniperLog(msg) {
    sniperLog.unshift(`[${new Date().toLocaleTimeString("pt-BR")}] ${msg}`);
    if (sniperLog.length > 100) sniperLog.pop();
    const el = document.getElementById("sniper-log");
    if (el) el.innerHTML = sniperLog.map(l => `<div class="text-gray-400">${escapeHtml(l)}</div>`).join("");
}

// ---------------------------------------------------------------------------
// Countdown
// ---------------------------------------------------------------------------
function startCountdown() {
    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(updateCountdown, 100);
}

async function updateCountdown() {
    try {
        const data = await apiCall("/api/sniper/next-target");
        const s = data.seconds_until;
        if (s <= 0) {
            document.getElementById("countdown").textContent = "AGORA!";
            document.getElementById("countdown-big").textContent = "🔥 AGORA!";
            return;
        }
        const d = Math.floor(s/86400);
        const h = Math.floor((s%86400)/3600);
        const m = Math.floor((s%3600)/60);
        const sec = Math.floor(s%60);
        const str = d>0 ? `${d}d ${h}h ${m}m ${sec}s` : `${h}h ${m}m ${sec}s`;
        document.getElementById("countdown").textContent = str;
        document.getElementById("countdown-big").textContent = str;
    } catch {}
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
async function loadUsers() {
    try {
        const data = await apiCall("/api/users");
        renderUsers(data.users);
        updateScheduleUserSelect(data.users);
    } catch {}
}

function renderUsers(users) {
    const tbody = document.getElementById("users-table");
    if (!users||!users.length) { tbody.innerHTML='<tr><td colspan="5" class="px-4 py-8 text-center text-gray-500">Nenhum usuário</td></tr>'; return; }
    tbody.innerHTML = users.map(u => {
        const active = u.is_active!==0;
        const auto = u.auto_login===1;
        const proxy = u.proxy ? `<span class="text-green-400 text-xs">${maskProxy(u.proxy)}</span>` : '<span class="text-gray-600 text-xs">—</span>';
        return `<tr class="hover:bg-gray-750 ${active?'':'opacity-50'}">
            <td class="px-3 py-3"><div class="text-sm text-white font-medium">${escapeHtml(u.username)}</div></td>
            <td class="px-3 py-3 text-center"><div class="toggle-track ${active?'active':'inactive'}" onclick="toggleActive('${u.id}')"><div class="toggle-thumb"></div></div></td>
            <td class="px-3 py-3 text-center"><div class="toggle-track ${auto?'active':'inactive'}" onclick="toggleAutoLogin('${u.id}')"><div class="toggle-thumb"></div></div></td>
            <td class="px-3 py-3">${proxy}</td>
            <td class="px-3 py-3 text-center"><div class="flex gap-1 justify-center">
                <button onclick="assignProxy('${u.id}')" class="bg-blue-700 hover:bg-blue-600 text-white rounded px-2 py-1 text-xs">🌐</button>
                <button onclick="deleteUser('${u.id}','${escapeHtml(u.username)}')" class="bg-red-800 hover:bg-red-700 text-white rounded px-2 py-1 text-xs">🗑️</button>
            </div></td>
        </tr>`;
    }).join("");
}

async function addUser() {
    const u=document.getElementById("new-username").value.trim();
    const p=document.getElementById("new-password").value.trim();
    const px=document.getElementById("new-proxy").value.trim();
    if(!u||!p){showToast("Preencha usuário e senha","error");return;}
    try{await apiCall("/api/users","POST",{username:u,password:p,proxy:px||null});showToast(`"${u}" cadastrado!`,"success");document.getElementById("new-username").value="";document.getElementById("new-password").value="";document.getElementById("new-proxy").value="";loadUsers();}catch{}
}
async function deleteUser(id,u){if(!confirm(`Remover "${u}"?`))return;try{await apiCall(`/api/users/${id}`,"DELETE");loadUsers();}catch{}}
async function toggleActive(id){try{await apiCall(`/api/users/${id}/toggle-active`,"POST");loadUsers();}catch{}}
async function toggleAutoLogin(id){try{await apiCall(`/api/users/${id}/toggle-auto-login`,"POST");loadUsers();}catch{}}
async function assignProxy(id){try{const d=await apiCall(`/api/proxies/assign/${id}`,"POST");showToast(d.message,"success");loadUsers();}catch{}}

// ---------------------------------------------------------------------------
// Schedule / Calendar
// ---------------------------------------------------------------------------
function updateScheduleUserSelect(users) {
    const sel = document.getElementById("schedule-user-select");
    const current = sel.value;
    sel.innerHTML = '<option value="">Selecione um usuário</option>' + users.map(u => `<option value="${u.id}">${escapeHtml(u.username)}</option>`).join("");
    if (current) sel.value = current;
}

async function loadScheduleForUser() {
    const userId = document.getElementById("schedule-user-select").value;
    if (!userId) { document.getElementById("schedule-grid").innerHTML = ""; currentScheduleUserId = null; return; }
    currentScheduleUserId = userId;

    try {
        const data = await apiCall(`/api/schedule/${userId}`);
        renderScheduleGrid(data.schedule);
    } catch {}
}

function renderScheduleGrid(schedule) {
    const grid = document.getElementById("schedule-grid");
    const days = schedule.days || DAYS.map(d => ({day:d, enabled:false, time_slots:[]}));

    grid.innerHTML = days.map(dayData => {
        const enabled = dayData.enabled;
        return `<div class="bg-gray-700 rounded p-3 ${enabled?'border border-green-600':'border border-gray-600'}">
            <div class="flex items-center gap-3 mb-2">
                <input type="checkbox" id="day-cb-${dayData.day}" ${enabled?'checked':''} onchange="toggleDay('${dayData.day}')" class="w-4 h-4 rounded bg-gray-600 border-gray-500">
                <span class="text-sm font-medium ${enabled?'text-green-400':'text-gray-400'}">${DAY_LABELS[dayData.day]||dayData.day}</span>
            </div>
            <div class="flex flex-wrap gap-2 ${enabled?'':'opacity-40'}" id="slots-${dayData.day}">
                ${TIME_SLOTS.map(slot => {
                    const checked = (dayData.time_slots||[]).includes(slot);
                    return `<label class="flex items-center gap-1 text-xs cursor-pointer">
                        <input type="checkbox" class="slot-cb" data-day="${dayData.day}" data-slot="${slot}" ${checked?'checked':''} ${!enabled?'disabled':''}>
                        <span class="${checked?'text-green-300':'text-gray-400'}">${slot}</span>
                    </label>`;
                }).join("")}
            </div>
        </div>`;
    }).join("");
}

function toggleDay(day) {
    const cb = document.getElementById(`day-cb-${day}`);
    const slotsEl = document.getElementById(`slots-${day}`);
    const checkboxes = slotsEl.querySelectorAll('.slot-cb');
    checkboxes.forEach(c => c.disabled = !cb.checked);
    if (cb.checked) {
        slotsEl.classList.remove('opacity-40');
        slotsEl.parentElement.classList.remove('border-gray-600');
        slotsEl.parentElement.classList.add('border-green-600');
    } else {
        slotsEl.classList.add('opacity-40');
        slotsEl.parentElement.classList.remove('border-green-600');
        slotsEl.parentElement.classList.add('border-gray-600');
    }
}

async function saveCurrentSchedule() {
    if (!currentScheduleUserId) { showToast("Selecione um usuário","error"); return; }

    const days = DAYS.map(day => {
        const cb = document.getElementById(`day-cb-${day}`);
        const enabled = cb ? cb.checked : false;
        const slots = [];
        document.querySelectorAll(`.slot-cb[data-day="${day}"]`).forEach(c => { if(c.checked) slots.push(c.dataset.slot); });
        return {day, enabled, time_slots: slots};
    });

    try {
        await apiCall(`/api/schedule/${currentScheduleUserId}`, "PUT", {schedule:{days}});
        showToast("Agenda salva!","success");
    } catch {}
}

function selectAllSlots() {
    DAYS.forEach(day => {
        const cb = document.getElementById(`day-cb-${day}`);
        if(cb){cb.checked=true;toggleDay(day);}
        document.querySelectorAll(`.slot-cb[data-day="${day}"]`).forEach(c=>{c.checked=true;c.disabled=false;});
    });
}

function clearAllSlots() {
    DAYS.forEach(day => {
        const cb = document.getElementById(`day-cb-${day}`);
        if(cb){cb.checked=false;toggleDay(day);}
    });
}

// ---------------------------------------------------------------------------
// Proxies
// ---------------------------------------------------------------------------
async function loadProxies() {
    try { const d=await apiCall("/api/proxies"); renderProxies(d.proxies); } catch {}
}

function renderProxies(proxies) {
    const t=document.getElementById("proxies-table");
    if(!proxies||!proxies.length){t.innerHTML='<tr><td colspan="5" class="px-4 py-8 text-center text-gray-500">Nenhum proxy</td></tr>';return;}
    t.innerHTML=proxies.map(p=>{
        const badge=p.is_active?'<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">✓</span>':'<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">✗</span>';
        const flag=p.country==='BR'?'🇧🇷':'🌍';
        return `<tr class="hover:bg-gray-750"><td class="px-3 py-3 text-sm text-white">${escapeHtml(p.label||'—')}</td><td class="px-3 py-3 text-xs text-gray-400 font-mono">${maskProxy(p.url)}</td><td class="px-3 py-3 text-center">${flag}</td><td class="px-3 py-3 text-center">${badge}</td><td class="px-3 py-3 text-center"><div class="flex gap-1 justify-center"><button onclick="testProxy('${p.id}')" class="bg-yellow-700 hover:bg-yellow-600 text-white rounded px-2 py-1 text-xs">🧪</button><button onclick="deleteProxy('${p.id}')" class="bg-red-800 hover:bg-red-700 text-white rounded px-2 py-1 text-xs">🗑️</button></div></td></tr>`;
    }).join("");
}

async function addProxy(){const u=document.getElementById("new-proxy-url").value.trim();const l=document.getElementById("new-proxy-label").value.trim();const c=document.getElementById("new-proxy-country").value;if(!u){showToast("URL obrigatória","error");return;}try{await apiCall("/api/proxies","POST",{url:u,label:l,country:c});showToast("Proxy adicionado","success");document.getElementById("new-proxy-url").value="";document.getElementById("new-proxy-label").value="";loadProxies();}catch{}}
async function addProxiesBatch(){const t=document.getElementById("batch-proxies").value.trim();if(!t)return;try{const d=await apiCall("/api/proxies/batch","POST",{proxies:t});showToast(d.message,"success");document.getElementById("batch-proxies").value="";loadProxies();}catch{}}
async function testProxy(id){showToast("Testando...","info");try{const r=await apiCall(`/api/proxies/${id}/test`,"POST");showToast(r.success?`✓ ${r.ip} (${r.latency_ms}ms)`:`✗ ${r.error}`,r.success?"success":"error");loadProxies();}catch{}}
async function testAllProxies(){showToast("Testando todos...","info");try{const d=await apiCall("/api/proxies/test-all","POST");showToast(`${d.working}/${d.total} OK`,d.failed>0?"warning":"success");loadProxies();}catch{}}
async function deleteProxy(id){if(!confirm("Remover?"))return;try{await apiCall(`/api/proxies/${id}`,"DELETE");loadProxies();}catch{}}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------
async function loadLogs() {
    try {
        const res = await fetch(`${API}/logs`, {headers:{Authorization:`Bearer ${jwtToken}`}});
        const data = await res.json();
        const c=document.getElementById("logs-container");
        const logs=data.logs||[];
        if(!logs.length){c.innerHTML='<div class="text-gray-500">Nenhum log</div>';return;}
        c.innerHTML=logs.map(l=>{
            const col=l.status==="success"?"text-green-400":(l.status==="error"||l.status==="failed")?"text-red-400":"text-gray-400";
            return `<div class="${col}"><span class="text-gray-600">${new Date(l.timestamp).toLocaleString("pt-BR")}</span> <span class="text-blue-400">[${l.action}]</span> ${escapeHtml(l.message)}</div>`;
        }).join("");
    } catch {}
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function switchTab(tab) {
    document.querySelectorAll(".tab-content").forEach(el=>el.classList.add("hidden"));
    document.querySelectorAll(".tab-btn").forEach(el=>{el.classList.remove("text-red-400","border-red-400","text-blue-400","border-blue-400");el.classList.add("text-gray-400","border-transparent");});
    document.getElementById(`tab-${tab}`).classList.remove("hidden");
    const btn=document.querySelector(`[data-tab="${tab}"]`);
    if(btn){btn.classList.remove("text-gray-400","border-transparent");btn.classList.add(tab==="sniper"?"text-red-400":"text-blue-400");btn.classList.add(tab==="sniper"?"border-red-400":"border-blue-400");}
    if(tab==="logs")loadLogs();if(tab==="users")loadUsers();if(tab==="proxies")loadProxies();if(tab==="schedule")loadUsers();
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function showToast(msg,type="info"){const c=document.getElementById("toast-container");const t=document.createElement("div");const cols={info:"bg-blue-800 border-blue-600",success:"bg-green-800 border-green-600",error:"bg-red-800 border-red-600",warning:"bg-yellow-800 border-yellow-600"};t.className=`${cols[type]||cols.info} border rounded px-4 py-2 text-sm text-white shadow-lg fade-in max-w-sm`;t.textContent=msg;c.appendChild(t);setTimeout(()=>{t.style.opacity="0";t.style.transition="opacity 0.3s";setTimeout(()=>t.remove(),300);},4000);}
function escapeHtml(s){if(!s)return"";const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function maskProxy(p){try{const u=new URL(p);return `${u.username?u.username+'@':''}${u.hostname}:${u.port}`;}catch{return p.length>25?p.slice(0,25)+'...':p;}}
function updateClock(){const el=document.getElementById("clock");if(el)el.textContent=new Date().toLocaleTimeString("pt-BR",{timeZone:"America/Sao_Paulo"});}
