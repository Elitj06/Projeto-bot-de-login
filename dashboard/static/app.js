/**
 * SEAP Bot Dashboard v3 — Client-side JavaScript.
 * Admin auth, proxy pool, user activation, execution plan.
 */
const API = "";
let socket = null;
let jwtToken = localStorage.getItem("seap_jwt") || null;
let userStatuses = {};

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    if (jwtToken) {
        checkAuth();
    } else {
        showLogin();
    }
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
    loadStatus();
    updateClock();
    setInterval(updateClock, 1000);
    setInterval(loadStatus, 30000);

    ["new-username", "new-password", "new-proxy"].forEach(id => {
        document.getElementById(id).addEventListener("keydown", e => {
            if (e.key === "Enter") addUser();
        });
    });
    ["login-user", "login-pass"].forEach(id => {
        document.getElementById(id).addEventListener("keydown", e => {
            if (e.key === "Enter") doLogin();
        });
    });
}

async function checkAuth() {
    try {
        const res = await fetch(`${API}/api/auth/status`, {
            headers: { "Authorization": `Bearer ${jwtToken}` }
        });
        const data = await res.json();
        if (data.authenticated) {
            showApp();
        } else {
            localStorage.removeItem("seap_jwt");
            jwtToken = null;
            showLogin();
        }
    } catch {
        showLogin();
    }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
async function doLogin() {
    const username = document.getElementById("login-user").value.trim();
    const password = document.getElementById("login-pass").value.trim();
    const errorEl = document.getElementById("login-error");

    if (!username || !password) {
        errorEl.textContent = "Preencha usuário e senha";
        errorEl.classList.remove("hidden");
        return;
    }

    try {
        const res = await fetch(`${API}/api/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Erro no login");

        jwtToken = data.token;
        localStorage.setItem("seap_jwt", jwtToken);
        errorEl.classList.add("hidden");
        showApp();
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove("hidden");
    }
}

function doLogout() {
    localStorage.removeItem("seap_jwt");
    jwtToken = null;
    showLogin();
}

// ---------------------------------------------------------------------------
// API with JWT
// ---------------------------------------------------------------------------
async function apiCall(url, method = "GET", body = null) {
    const opts = {
        method,
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${jwtToken}`,
        },
    };
    if (body) opts.body = JSON.stringify(body);

    try {
        const res = await fetch(`${API}${url}`, opts);
        if (res.status === 401) {
            doLogout();
            throw new Error("Sessão expirada");
        }
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        return data;
    } catch (err) {
        showToast(err.message, "error");
        throw err;
    }
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function initWebSocket() {
    socket = io({ transports: ["websocket", "polling"] });

    socket.on("connect", () => updateConnectionStatus(true));
    socket.on("disconnect", () => updateConnectionStatus(false));

    socket.on("status_update", (data) => handleStatusUpdate(data));
}

function updateConnectionStatus(connected) {
    const indicator = document.getElementById("ws-indicator");
    const status = document.getElementById("connection-status");

    if (connected) {
        indicator.className = "w-3 h-3 rounded-full bg-green-500 pulse-dot";
        status.textContent = "Conectado";
        status.className = "text-sm text-green-400";
    } else {
        indicator.className = "w-3 h-3 rounded-full bg-red-500";
        status.textContent = "Desconectado";
        status.className = "text-sm text-red-400";
    }
}

function handleStatusUpdate(data) {
    const userId = data.user_id;
    if (userId === "__all__") {
        if (data.status === "batch_start") {
            showToast(`Iniciando login de ${data.total} usuários...`, "info");
        } else if (data.status === "batch_complete") {
            const ok = data.results?.filter(r => r.success).length || 0;
            showToast(`Batch: ${ok}/${data.results?.length} sucessos`, ok > 0 ? "success" : "error");
            loadUsers();
        } else if (data.status === "batch_wait") {
            showToast(`Lote ${data.batch}/${data.total_batches} — aguardando ${data.wait_seconds}s...`, "warning");
        }
        return;
    }

    userStatuses[userId] = data;
    const statusCell = document.getElementById(`status-${userId}`);
    const timeCell = document.getElementById(`time-${userId}`);

    if (statusCell) {
        const { status } = data;
        const badges = {
            connecting: '<span class="px-2 py-1 rounded text-xs bg-yellow-900 text-yellow-300 pulse-dot">Conectando</span>',
            navigating: '<span class="px-2 py-1 rounded text-xs bg-blue-900 text-blue-300 pulse-dot">Navegando</span>',
            solving_captcha: '<span class="px-2 py-1 rounded text-xs bg-purple-900 text-purple-300 pulse-dot">Captcha</span>',
            success: '<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">✓ OK</span>',
            failed: '<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">✗ Falha</span>',
            error: '<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">⚠ Erro</span>',
            cancelled: '<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300">Cancelado</span>',
        };
        statusCell.innerHTML = badges[status] || `<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-400">${status || "?"}</span>`;
    }

    if (timeCell && data.elapsed) {
        timeCell.innerHTML = `<span class="text-gray-300">${data.elapsed}s</span>`;
    }
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------
async function loadStatus() {
    try {
        const data = await apiCall("/api/status");
        document.getElementById("stat-users").textContent = data.total_users || 0;
        document.getElementById("stat-active").textContent = data.active_users || 0;
        document.getElementById("stat-proxies").textContent = `${data.proxy_pool?.active || 0}/${data.proxy_pool?.total || 0}`;
        document.getElementById("stat-sessions").textContent = data.active_sessions || 0;
    } catch {}
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
async function loadUsers() {
    try {
        const data = await apiCall("/api/users");
        renderUsers(data.users);
    } catch {}
}

function renderUsers(users) {
    const tbody = document.getElementById("users-table");

    if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="px-4 py-8 text-center text-gray-500">Nenhum usuário cadastrado.</td></tr>';
        return;
    }

    tbody.innerHTML = users.map(u => {
        const status = userStatuses[u.id] || {};
        const active = u.is_active !== 0 && u.is_active !== false;
        const autoLogin = u.auto_login === 1 || u.auto_login === true;
        const human = u.human_mode === 1 || u.human_mode === true;

        const proxyDisplay = u.proxy
            ? `<span class="text-green-400 text-xs">${maskProxy(u.proxy)}</span>`
            : '<span class="text-gray-600 text-xs">—</span>';

        let statusBadge;
        if (status.status === "success") {
            statusBadge = '<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">✓ OK</span>';
        } else if (status.status === "failed" || status.status === "error") {
            statusBadge = '<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">✗ Falha</span>';
        } else if (status.status) {
            statusBadge = `<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-400">${status.status}</span>`;
        } else {
            statusBadge = '<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-500">Inativo</span>';
        }

        const time = status.elapsed ? `${status.elapsed}s` : "—";
        const rowOpacity = active ? "" : "opacity-50";

        return `
        <tr id="row-${u.id}" class="hover:bg-gray-750 transition ${rowOpacity}">
            <td class="px-3 py-3">
                <div class="text-sm text-white font-medium">${escapeHtml(u.username)}</div>
                <div class="text-xs text-gray-500">${u.id.slice(0, 8)}...</div>
            </td>
            <td class="px-3 py-3 text-center">
                <div class="toggle-track ${active ? 'active' : 'inactive'}" onclick="toggleActive('${u.id}')">
                    <div class="toggle-thumb"></div>
                </div>
            </td>
            <td class="px-3 py-3 text-center">
                <div class="toggle-track ${autoLogin ? 'active' : 'inactive'}" onclick="toggleAutoLogin('${u.id}')" title="Login automático">
                    <div class="toggle-thumb"></div>
                </div>
            </td>
            <td class="px-3 py-3">${proxyDisplay}</td>
            <td class="px-3 py-3 text-center" id="human-${u.id}">
                <span class="text-xs ${human ? 'text-green-400' : 'text-gray-500'}">${human ? 'ON' : 'OFF'}</span>
            </td>
            <td class="px-3 py-3" id="status-${u.id}">${statusBadge}</td>
            <td class="px-3 py-3" id="time-${u.id}"><span class="text-gray-400 text-sm">${time}</span></td>
            <td class="px-3 py-3 text-center">
                <div class="flex gap-1 justify-center">
                    <button onclick="loginUser('${u.id}')" class="bg-green-700 hover:bg-green-600 text-white rounded px-2 py-1 text-xs transition" title="Login" ${!active ? 'disabled' : ''}>🔑</button>
                    <button onclick="toggleHuman('${u.id}')" class="bg-purple-700 hover:bg-purple-600 text-white rounded px-2 py-1 text-xs transition" title="Modo Humano">🧑</button>
                    <button onclick="assignProxy('${u.id}')" class="bg-blue-700 hover:bg-blue-600 text-white rounded px-2 py-1 text-xs transition" title="Atribuir Proxy">🌐</button>
                    <button onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')" class="bg-red-800 hover:bg-red-700 text-white rounded px-2 py-1 text-xs transition" title="Remover">🗑️</button>
                </div>
            </td>
        </tr>`;
    }).join("");
}

async function addUser() {
    const username = document.getElementById("new-username").value.trim();
    const password = document.getElementById("new-password").value.trim();
    const proxy = document.getElementById("new-proxy").value.trim();

    if (!username || !password) {
        showToast("Preencha usuário e senha", "error");
        return;
    }

    try {
        await apiCall("/api/users", "POST", { username, password, proxy: proxy || null });
        showToast(`"${username}" cadastrado!`, "success");
        document.getElementById("new-username").value = "";
        document.getElementById("new-password").value = "";
        document.getElementById("new-proxy").value = "";
        loadUsers();
    } catch {}
}

async function deleteUser(id, username) {
    if (!confirm(`Remover "${username}"?`)) return;
    try {
        await apiCall(`/api/users/${id}`, "DELETE");
        showToast(`"${username}" removido`, "info");
        loadUsers();
    } catch {}
}

async function loginUser(id) {
    try {
        showToast("Iniciando login...", "info");
        const result = await apiCall(`/api/users/${id}/login`, "POST");
        showToast(result.success ? `Login OK! ${result.elapsed_seconds}s` : `Falha: ${result.message}`, result.success ? "success" : "error");
        loadUsers();
    } catch {}
}

async function loginAllActive() {
    if (!confirm("Executar login de todos os usuários ATIVOS?")) return;
    try {
        showToast("Iniciando login em massa...", "info");
        const result = await apiCall("/api/login-all", "POST");
        showToast(`${result.success}/${result.total} logins OK`, result.failed > 0 ? "warning" : "success");
        loadUsers();
    } catch {}
}

async function toggleActive(id) {
    try {
        const data = await apiCall(`/api/users/${id}/toggle-active`, "POST");
        showToast(data.message, "info");
        loadUsers();
    } catch {}
}

async function toggleAutoLogin(id) {
    try {
        const data = await apiCall(`/api/users/${id}/toggle-auto-login`, "POST");
        showToast(data.message, "info");
        loadUsers();
    } catch {}
}

async function toggleHuman(id) {
    try {
        const data = await apiCall(`/api/users/${id}/toggle-human`, "POST");
        showToast(data.message, "info");
        loadUsers();
    } catch {}
}

async function assignProxy(id) {
    try {
        const data = await apiCall(`/api/proxies/assign/${id}`, "POST");
        showToast(data.message, "success");
        loadUsers();
    } catch {}
}

// ---------------------------------------------------------------------------
// Proxies
// ---------------------------------------------------------------------------
async function loadProxies() {
    try {
        const data = await apiCall("/api/proxies");
        renderProxies(data.proxies);
    } catch {}
}

function renderProxies(proxies) {
    const tbody = document.getElementById("proxies-table");

    if (!proxies.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-gray-500">Nenhum proxy cadastrado. Adicione proxies para login simultâneo.</td></tr>';
        return;
    }

    tbody.innerHTML = proxies.map(p => {
        const statusBadge = p.is_active
            ? '<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">✓ Ativo</span>'
            : '<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">✗ Inativo</span>';

        const flag = p.country === 'BR' ? '🇧🇷' : p.country === 'US' ? '🇺🇸' : '🌍';

        return `
        <tr class="hover:bg-gray-750 transition">
            <td class="px-3 py-3 text-sm text-white">${escapeHtml(p.label || '—')}</td>
            <td class="px-3 py-3 text-xs text-gray-400 font-mono">${maskProxy(p.url)}</td>
            <td class="px-3 py-3 text-center">${flag} ${p.country}</td>
            <td class="px-3 py-3 text-center">${statusBadge}</td>
            <td class="px-3 py-3 text-center text-sm text-gray-300">${p.assigned_count || 0}</td>
            <td class="px-3 py-3 text-center">
                <div class="flex gap-1 justify-center">
                    <button onclick="testProxy('${p.id}')" class="bg-yellow-700 hover:bg-yellow-600 text-white rounded px-2 py-1 text-xs transition">🧪</button>
                    <button onclick="deleteProxy('${p.id}')" class="bg-red-800 hover:bg-red-700 text-white rounded px-2 py-1 text-xs transition">🗑️</button>
                </div>
            </td>
        </tr>`;
    }).join("");
}

async function addProxy() {
    const url = document.getElementById("new-proxy-url").value.trim();
    const label = document.getElementById("new-proxy-label").value.trim();
    const country = document.getElementById("new-proxy-country").value;

    if (!url) {
        showToast("URL do proxy obrigatória", "error");
        return;
    }

    try {
        await apiCall("/api/proxies", "POST", { url, label, country });
        showToast("Proxy adicionado!", "success");
        document.getElementById("new-proxy-url").value = "";
        document.getElementById("new-proxy-label").value = "";
        loadProxies();
    } catch {}
}

async function addProxiesBatch() {
    const text = document.getElementById("batch-proxies").value.trim();
    if (!text) {
        showToast("Cole os proxies no campo", "error");
        return;
    }

    try {
        const data = await apiCall("/api/proxies/batch", "POST", { proxies: text });
        showToast(data.message, "success");
        document.getElementById("batch-proxies").value = "";
        loadProxies();
    } catch {}
}

async function testProxy(id) {
    showToast("Testando proxy...", "info");
    try {
        const result = await apiCall(`/api/proxies/${id}/test`, "POST");
        if (result.success) {
            showToast(`✓ IP: ${result.ip} (${result.latency_ms}ms)`, "success");
        } else {
            showToast(`✗ Falha: ${result.error}`, "error");
        }
        loadProxies();
    } catch {}
}

async function testAllProxies() {
    showToast("Testando todos os proxies...", "info");
    try {
        const data = await apiCall("/api/proxies/test-all", "POST");
        showToast(`${data.working}/${data.total} proxies OK`, data.failed > 0 ? "warning" : "success");
        loadProxies();
    } catch {}
}

async function deleteProxy(id) {
    if (!confirm("Remover este proxy?")) return;
    try {
        await apiCall(`/api/proxies/${id}`, "DELETE");
        showToast("Proxy removido", "info");
        loadProxies();
    } catch {}
}

// ---------------------------------------------------------------------------
// Execution Plan
// ---------------------------------------------------------------------------
async function showExecutionPlan() {
    try {
        const plan = await apiCall("/api/execution-plan");
        renderPlan(plan);
        switchTab("plan");
    } catch {}
}

function renderPlan(plan) {
    const summary = document.getElementById("plan-summary");
    summary.innerHTML = `
        <div class="bg-gray-700 rounded p-3 text-center">
            <div class="text-2xl font-bold text-white">${plan.total_users}</div>
            <div class="text-xs text-gray-400">Usuários Ativos</div>
        </div>
        <div class="bg-gray-700 rounded p-3 text-center">
            <div class="text-2xl font-bold text-blue-400">${plan.total_proxies}</div>
            <div class="text-xs text-gray-400">Proxies Disponíveis</div>
        </div>
        <div class="bg-gray-700 rounded p-3 text-center">
            <div class="text-2xl font-bold text-yellow-400">${plan.total_batches}</div>
            <div class="text-xs text-gray-400">Lotes</div>
        </div>
        <div class="bg-gray-700 rounded p-3 text-center">
            <div class="text-2xl font-bold text-green-400">~${Math.ceil(plan.estimated_total_seconds / 60)}min</div>
            <div class="text-xs text-gray-400">Tempo Estimado</div>
        </div>
    `;

    const batchesEl = document.getElementById("plan-batches");
    if (!plan.batches || !plan.batches.length) {
        batchesEl.innerHTML = '<div class="text-center text-gray-500 py-8">Nenhum usuário ativo para executar.</div>';
        return;
    }

    batchesEl.innerHTML = plan.batches.map((b, i) => `
        <div class="bg-gray-800 rounded-lg border border-gray-700 p-4 fade-in">
            <div class="flex justify-between items-center mb-3">
                <h3 class="font-semibold text-white">🔄 Lote ${b.batch_number} de ${plan.total_batches}</h3>
                <span class="text-xs text-gray-400">${b.parallel_count} login(s) simultâneo(s) · ~${b.estimated_duration}s</span>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                ${b.users.map(u => `
                    <div class="bg-gray-700 rounded px-3 py-2 flex justify-between items-center">
                        <span class="text-sm text-white">${escapeHtml(u.username)}</span>
                        <span class="text-xs ${u.proxy.includes('socks5') || u.proxy.includes('http') ? 'text-green-400' : 'text-red-400'}">${u.proxy.includes('socks5') || u.proxy.includes('http') ? maskProxy(u.proxy) : 'SEM PROXY'}</span>
                    </div>
                `).join("")}
            </div>
            ${i < plan.batches.length - 1 ? '<div class="text-center text-yellow-400 text-xs mt-2">⏳ Aguarda 45s antes do próximo lote</div>' : ''}
        </div>
    `).join("");
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------
async function loadLogs() {
    try {
        const res = await fetch(`${API}/logs`, {
            headers: { "Authorization": `Bearer ${jwtToken}` }
        });
        const data = await res.json();
        renderLogs(data.logs || []);
    } catch {}
}

function renderLogs(logs) {
    const container = document.getElementById("logs-container");
    if (!logs.length) {
        container.innerHTML = '<div class="text-gray-500">Nenhum log.</div>';
        return;
    }

    container.innerHTML = logs.map(l => {
        const color = l.status === "success" ? "text-green-400"
            : (l.status === "error" || l.status === "failed") ? "text-red-400"
            : l.status === "started" ? "text-yellow-400"
            : "text-gray-400";
        const time = new Date(l.timestamp).toLocaleString("pt-BR");
        return `<div class="${color}">
            <span class="text-gray-600">${time}</span>
            <span class="text-blue-400">[${l.action}]</span>
            <span class="text-gray-300">${l.message}</span>
        </div>`;
    }).join("");
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function switchTab(tab) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
    document.querySelectorAll(".tab-btn").forEach(el => {
        el.classList.remove("text-blue-400", "border-blue-400");
        el.classList.add("text-gray-400", "border-transparent");
    });

    document.getElementById(`tab-${tab}`).classList.remove("hidden");
    const btn = document.querySelector(`[data-tab="${tab}"]`);
    if (btn) {
        btn.classList.remove("text-gray-400", "border-transparent");
        btn.classList.add("text-blue-400", "border-blue-400");
    }

    if (tab === "logs") loadLogs();
    if (tab === "users") loadUsers();
    if (tab === "proxies") loadProxies();
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    const colors = {
        info: "bg-blue-800 border-blue-600",
        success: "bg-green-800 border-green-600",
        error: "bg-red-800 border-red-600",
        warning: "bg-yellow-800 border-yellow-600",
    };
    toast.className = `${colors[type] || colors.info} border rounded px-4 py-2 text-sm text-white shadow-lg fade-in max-w-sm`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.3s";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function maskProxy(proxy) {
    try {
        const url = new URL(proxy);
        const user = url.username ? `${url.username}@` : "";
        return `${user}${url.hostname}:${url.port}`;
    } catch {
        return proxy.length > 25 ? proxy.slice(0, 25) + "..." : proxy;
    }
}

function updateClock() {
    const el = document.getElementById("clock");
    if (el) {
        el.textContent = new Date().toLocaleString("pt-BR", {
            timeZone: "America/Sao_Paule",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
        });
    }
}
