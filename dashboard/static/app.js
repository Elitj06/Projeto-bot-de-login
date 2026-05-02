/**
 * SEAP Bot Dashboard — Client-side JavaScript.
 *
 * WebSocket + REST API integration.
 */
const API = "";
let socket = null;
let globalHumanMode = false;
let userStatuses = {};

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
    loadUsers();
    updateClock();
    setInterval(updateClock, 1000);

    // Enter key on add user form
    ["new-username", "new-password", "new-proxy"].forEach(id => {
        document.getElementById(id).addEventListener("keydown", e => {
            if (e.key === "Enter") addUser();
        });
    });
});

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function initWebSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    socket = io({ transports: ["websocket", "polling"] });

    socket.on("connect", () => {
        updateConnectionStatus(true);
    });

    socket.on("disconnect", () => {
        updateConnectionStatus(false);
    });

    socket.on("status_update", (data) => {
        handleStatusUpdate(data);
    });
}

function updateConnectionStatus(connected) {
    const indicator = document.getElementById("ws-indicator");
    const status = document.getElementById("connection-status");
    const wsText = document.getElementById("ws-status-text");

    if (connected) {
        indicator.className = "w-3 h-3 rounded-full bg-green-500 pulse-dot";
        status.textContent = "Conectado";
        status.className = "text-sm text-green-400";
        wsText.textContent = "Conectado";
        wsText.className = "text-green-400";
    } else {
        indicator.className = "w-3 h-3 rounded-full bg-red-500";
        status.textContent = "Desconectado";
        status.className = "text-sm text-red-400";
        wsText.textContent = "Desconectado";
        wsText.className = "text-red-400";
    }
}

function handleStatusUpdate(data) {
    const userId = data.user_id;
    if (userId === "__all__") {
        // Batch event
        if (data.status === "batch_start") {
            showToast(`Iniciando login de ${data.total} usuários...`, "info");
        } else if (data.status === "batch_complete") {
            const ok = data.results?.filter(r => r.success).length || 0;
            showToast(`Batch completo: ${ok}/${data.results?.length} sucessos`, "success");
            loadUsers();
        }
        return;
    }

    userStatuses[userId] = data;

    // Update table row if visible
    const statusCell = document.getElementById(`status-${userId}`);
    const timeCell = document.getElementById(`time-${userId}`);
    const row = document.getElementById(`row-${userId}`);

    if (statusCell) {
        const { status, message } = data;
        let badge = "";

        switch (status) {
            case "connecting":
                badge = `<span class="px-2 py-1 rounded text-xs bg-yellow-900 text-yellow-300 pulse-dot">Conectando</span>`;
                break;
            case "navigating":
                badge = `<span class="px-2 py-1 rounded text-xs bg-blue-900 text-blue-300 pulse-dot">Navegando</span>`;
                break;
            case "success":
                badge = `<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">✓ Sucesso</span>`;
                break;
            case "failed":
                badge = `<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">✗ Falha</span>`;
                break;
            case "error":
                badge = `<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">⚠ Erro</span>`;
                break;
            case "cancelled":
                badge = `<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300">Cancelado</span>`;
                break;
            default:
                badge = `<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-400">${status || "?"}</span>`;
        }
        statusCell.innerHTML = badge;
    }

    if (timeCell && data.elapsed) {
        timeCell.innerHTML = `<span class="text-gray-300">${data.elapsed}s</span>`;
    }

    if (row) {
        row.classList.add("fade-in");
    }
}

// ---------------------------------------------------------------------------
// API Calls
// ---------------------------------------------------------------------------
async function apiCall(url, method = "GET", body = null) {
    const opts = {
        method,
        headers: { "Content-Type": "application/json" },
    };
    if (body) opts.body = JSON.stringify(body);

    try {
        const res = await fetch(`${API}${url}`, opts);
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || `HTTP ${res.status}`);
        }
        return data;
    } catch (err) {
        showToast(err.message, "error");
        throw err;
    }
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
async function loadUsers() {
    try {
        const data = await apiCall("/api/users");
        renderUsers(data.users);
        document.getElementById("total-users").textContent = data.total;
        updateVagaUserSelect(data.users);
    } catch (e) {
        console.error("Erro ao carregar usuários:", e);
    }
}

function renderUsers(users) {
    const tbody = document.getElementById("users-table");

    if (!users.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-gray-500">Nenhum usuário cadastrado.</td></tr>`;
        return;
    }

    tbody.innerHTML = users.map(u => {
        const status = userStatuses[u.id] || {};
        const proxy = u.proxy ? `<span class="text-green-400 text-xs">${maskProxy(u.proxy)}</span>` : `<span class="text-gray-600 text-xs">Direto</span>`;
        const human = u.human_mode
            ? `<span class="text-green-400">ON</span>`
            : `<span class="text-gray-500">OFF</span>`;

        let statusBadge;
        if (status.status === "success") {
            statusBadge = `<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">✓ Sucesso</span>`;
        } else if (status.status === "failed" || status.status === "error") {
            statusBadge = `<span class="px-2 py-1 rounded text-xs bg-red-900 text-red-300">✗ Falha</span>`;
        } else if (status.status) {
            statusBadge = `<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-400">${status.status}</span>`;
        } else {
            statusBadge = `<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-500">Inativo</span>`;
        }

        const time = status.elapsed ? `${status.elapsed}s` : "—";

        return `
        <tr id="row-${u.id}" class="hover:bg-gray-750 transition">
            <td class="px-4 py-3">
                <div class="text-sm text-white font-medium">${escapeHtml(u.username)}</div>
                <div class="text-xs text-gray-500">${u.id.slice(0, 8)}...</div>
            </td>
            <td class="px-4 py-3">${proxy}</td>
            <td class="px-4 py-3 text-center" id="human-${u.id}">${human}</td>
            <td class="px-4 py-3" id="status-${u.id}">${statusBadge}</td>
            <td class="px-4 py-3" id="time-${u.id}"><span class="text-gray-400 text-sm">${time}</span></td>
            <td class="px-4 py-3 text-center">
                <div class="flex gap-1 justify-center">
                    <button onclick="loginUser('${u.id}')" class="bg-green-700 hover:bg-green-600 text-white rounded px-2 py-1 text-xs transition" title="Login">
                        🔑
                    </button>
                    <button onclick="toggleHuman('${u.id}')" class="bg-purple-700 hover:bg-purple-600 text-white rounded px-2 py-1 text-xs transition" title="Toggle Humano">
                        🧑
                    </button>
                    <button onclick="deleteUser('${u.id}', '${escapeHtml(u.username)}')" class="bg-red-800 hover:bg-red-700 text-white rounded px-2 py-1 text-xs transition" title="Remover">
                        🗑️
                    </button>
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
        showToast(`Usuário "${username}" cadastrado!`, "success");
        document.getElementById("new-username").value = "";
        document.getElementById("new-password").value = "";
        document.getElementById("new-proxy").value = "";
        loadUsers();
    } catch (e) {}
}

async function deleteUser(id, username) {
    if (!confirm(`Remover usuário "${username}"?`)) return;

    try {
        await apiCall(`/api/users/${id}`, "DELETE");
        showToast(`Usuário "${username}" removido`, "info");
        loadUsers();
    } catch (e) {}
}

async function loginUser(id) {
    try {
        showToast("Iniciando login...", "info");
        const result = await apiCall(`/api/users/${id}/login`, "POST");
        if (result.success) {
            showToast(`Login OK! ${result.elapsed_seconds}s`, "success");
        } else {
            showToast(`Falha: ${result.message}`, "error");
        }
        loadUsers();
    } catch (e) {}
}

async function loginAll() {
    try {
        showToast("Iniciando login de todos...", "info");
        const result = await apiCall("/api/login-all", "POST");
        showToast(`${result.success}/${result.total} logins com sucesso`, result.failed > 0 ? "warning" : "success");
        loadUsers();
    } catch (e) {}
}

async function toggleHuman(id) {
    try {
        const data = await apiCall(`/api/users/${id}/toggle-human`, "POST");
        showToast(data.message, "info");
        loadUsers();
    } catch (e) {}
}

function toggleAllHuman() {
    globalHumanMode = !globalHumanMode;
    const btn = document.getElementById("global-human-btn");
    btn.textContent = globalHumanMode ? "🧑 Modo Humano: ON" : "🧑 Modo Humano: OFF";
    btn.className = globalHumanMode
        ? "bg-purple-600 hover:bg-purple-700 text-white rounded px-4 py-2 text-sm font-medium transition"
        : "bg-purple-800 hover:bg-purple-700 text-white rounded px-4 py-2 text-sm font-medium transition";
    // Apply to all users
    loadUsers().then(() => {
        document.querySelectorAll("[id^='human-']").forEach(el => {
            // Just visual — individual toggles still work via API
        });
    });
}

// ---------------------------------------------------------------------------
// Vagas
// ---------------------------------------------------------------------------
function updateVagaUserSelect(users) {
    const select = document.getElementById("vaga-user-select");
    const current = select.value;
    select.innerHTML = '<option value="">Selecione um usuário...</option>';
    users.forEach(u => {
        select.innerHTML += `<option value="${u.id}">${escapeHtml(u.username)}</option>`;
    });
    select.value = current;
}

async function fetchVagas() {
    const userId = document.getElementById("vaga-user-select").value;
    if (!userId) {
        showToast("Selecione um usuário", "error");
        return;
    }

    try {
        const data = await apiCall(`/api/users/${userId}/vagas`, "POST");
        renderVagas(data.vagas || []);
        showToast(`${data.total || 0} vagas encontradas`, "info");
    } catch (e) {}
}

async function candidatarVaga(userId, vagaId, titulo) {
    if (!confirm(`Candidatar a "${titulo}"?`)) return;

    try {
        const data = await apiCall(`/api/users/${userId}/vagas/${vagaId}/candidatar`, "POST");
        if (data.success) {
            showToast(data.message, "success");
            fetchVagas();
        } else {
            showToast(data.message || data.error, "error");
        }
    } catch (e) {}
}

function renderVagas(vagas) {
    const tbody = document.getElementById("vagas-table");

    if (!vagas.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-8 text-center text-gray-500">Nenhuma vaga encontrada.</td></tr>';
        return;
    }

    const userId = document.getElementById("vaga-user-select").value;

    tbody.innerHTML = vagas.map(v => {
        const statusBadge = v.candidatou
            ? '<span class="px-2 py-1 rounded text-xs bg-green-900 text-green-300">Candidatado</span>'
            : '<span class="px-2 py-1 rounded text-xs bg-gray-700 text-gray-400">Disponível</span>';

        const actionBtn = v.candidatou
            ? '<span class="text-gray-600 text-xs">—</span>'
            : `<button onclick="candidatarVaga('${userId}','${v.id}','${escapeHtml(v.titulo)}')" class="bg-blue-700 hover:bg-blue-600 text-white rounded px-2 py-1 text-xs transition">Candidatar</button>`;

        return `
        <tr class="hover:bg-gray-750">
            <td class="px-4 py-3 text-sm text-white">${escapeHtml(v.titulo)}</td>
            <td class="px-4 py-3 text-xs text-gray-400">${escapeHtml(v.descricao || "").slice(0, 80)}</td>
            <td class="px-4 py-3 text-center">${statusBadge}</td>
            <td class="px-4 py-3 text-center">${actionBtn}</td>
        </tr>`;
    }).join("");
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------
async function loadLogs() {
    try {
        const res = await fetch(`${API}/logs`);
        const data = await res.json();
        renderLogs(data.logs || []);
    } catch (e) {
        console.error("Erro ao carregar logs:", e);
    }
}

function renderLogs(logs) {
    const container = document.getElementById("logs-container");

    if (!logs.length) {
        container.innerHTML = '<div class="text-gray-500">Nenhum log encontrado.</div>';
        return;
    }

    container.innerHTML = logs.map(l => {
        const color = l.status === "success" ? "text-green-400"
            : l.status === "error" || l.status === "failed" ? "text-red-400"
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
    // Hide all
    document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
    document.querySelectorAll(".tab-btn").forEach(el => {
        el.classList.remove("text-blue-400", "border-blue-400");
        el.classList.add("text-gray-400", "border-transparent");
    });

    // Show selected
    document.getElementById(`tab-${tab}`).classList.remove("hidden");
    document.querySelector(`[data-tab="${tab}"]`).classList.remove("text-gray-400", "border-transparent");
    document.querySelector(`[data-tab="${tab}"]`).classList.add("text-blue-400", "border-blue-400");

    // Load data for tab
    if (tab === "logs") loadLogs();
    if (tab === "users") loadUsers();
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

    toast.className = `${colors[type] || colors.info} border rounded px-4 py-2 text-sm text-white shadow-lg fade-in`;
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
    // Show only host:port
    try {
        const url = new URL(proxy);
        return `${url.hostname}:${url.port}`;
    } catch {
        return proxy.slice(0, 20) + "...";
    }
}

function updateClock() {
    const now = new Date();
    document.getElementById("clock").textContent = now.toLocaleString("pt-BR", {
        timeZone: "America/Sao_Paulo",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}
