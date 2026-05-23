"""
Camada de acesso ao banco SQLite.

Cria tabelas automaticamente na primeira execução.
Fornece funções CRUD para users, sessions, logs e vagas.
"""
import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "seap_bot.db"


def get_connection() -> sqlite3.Connection:
    """Retorna conexão com o banco SQLite."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Cria todas as tabelas se não existirem."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_encrypted TEXT NOT NULL,
                proxy TEXT DEFAULT NULL,
                human_mode INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                auto_login INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'inactive',
                login_at TEXT,
                expires_at TEXT,
                cookies TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS admins (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proxy_pool (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                proxy_type TEXT DEFAULT 'socks5',
                country TEXT DEFAULT 'BR',
                label TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                assigned_count INTEGER DEFAULT 0,
                last_check TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_schedules (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                schedule_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sniper_sessions (
                id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'idle',
                target_time TEXT,
                ntp_offset_ms REAL DEFAULT 0,
                results_json TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS vagas (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                vaga_external_id TEXT,
                titulo TEXT,
                descricao TEXT,
                status TEXT DEFAULT 'disponivel',
                candidatou INTEGER DEFAULT 0,
                data_candidatura TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        conn.commit()

        # Migrações para tabelas existentes
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN auto_login INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN filter_unit TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN filter_date TEXT DEFAULT ''")
        except Exception:
            pass

        conn.commit()
        logger.info("Banco de dados inicializado com sucesso")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Users CRUD
# ---------------------------------------------------------------------------

def create_user(username: str, password: str, proxy: Optional[str] = None) -> dict:
    """Cria um novo usuário. Retorna dict com os dados."""
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_encrypted, proxy, human_mode, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (user_id, username, password, proxy, now, now),
        )
        conn.commit()
        logger.info(f"Usuário criado: {username} ({user_id[:8]}...)")
        return get_user(user_id)
    finally:
        conn.close()


def get_user(user_id: str) -> Optional[dict]:
    """Busca usuário por ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[dict]:
    """Busca usuário por username."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users() -> list[dict]:
    """Retorna todos os usuários cadastrados."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_user(user_id: str, **kwargs) -> Optional[dict]:
    """Atualiza campos do usuário. Retorna o usuário atualizado ou None."""
    allowed = {"username", "password_encrypted", "proxy", "human_mode", "is_active", "auto_login", "filter_unit", "filter_date"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_user(user_id)

    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]

    conn = get_connection()
    try:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return get_user(user_id)
    finally:
        conn.close()


def delete_user(user_id: str) -> bool:
    """Remove um usuário. Retorna True se removido."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def toggle_human_mode(user_id: str) -> Optional[dict]:
    """Alterna human_mode entre 0 e 1."""
    user = get_user(user_id)
    if not user:
        return None
    new_mode = 0 if user["human_mode"] else 1
    return update_user(user_id, human_mode=new_mode)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(user_id: str) -> dict:
    """Cria uma nova sessão para o usuário."""
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (id, user_id, status, login_at) VALUES (?, ?, 'active', ?)",
            (session_id, user_id, now),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
    finally:
        conn.close()


def get_active_session(user_id: str) -> Optional[dict]:
    """Retorna a sessão ativa do usuário, se houver."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND status = 'active' ORDER BY login_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_session_status(session_id: str, status: str) -> None:
    """Atualiza o status de uma sessão."""
    conn = get_connection()
    try:
        conn.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))
        conn.commit()
    finally:
        conn.close()


def deactivate_user_sessions(user_id: str) -> None:
    """Marca todas as sessões do usuário como expiradas."""
    conn = get_connection()
    try:
        conn.execute("UPDATE sessions SET status = 'expired' WHERE user_id = ? AND status = 'active'", (user_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def add_log(user_id: Optional[str], action: str, status: str, message: str = "") -> None:
    """Registra uma entrada de log."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO logs (user_id, action, status, message, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, status, message, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_logs(user_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Retorna os logs mais recentes."""
    conn = get_connection()
    try:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Vagas
# ---------------------------------------------------------------------------

def upsert_vaga(vaga_id: str, user_id: str, titulo: str, descricao: str = "",
                vaga_external_id: str = "") -> dict:
    """Cria ou atualiza uma vaga."""
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM vagas WHERE id = ?", (vaga_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE vagas SET titulo=?, descricao=?, vaga_external_id=? WHERE id=?",
                (titulo, descricao, vaga_external_id, vaga_id),
            )
        else:
            conn.execute(
                "INSERT INTO vagas (id, user_id, vaga_external_id, titulo, descricao) VALUES (?, ?, ?, ?, ?)",
                (vaga_id, user_id, vaga_external_id, titulo, descricao),
            )
        conn.commit()
        return dict(conn.execute("SELECT * FROM vagas WHERE id = ?", (vaga_id,)).fetchone())
    finally:
        conn.close()


def list_vagas(user_id: str) -> list[dict]:
    """Lista vagas de um usuário."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM vagas WHERE user_id = ? ORDER BY titulo", (user_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_vaga(vaga_id: str) -> Optional[dict]:
    """Busca uma vaga pelo ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM vagas WHERE id = ?", (vaga_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_vaga_candidatada(vaga_id: str) -> Optional[dict]:
    """Marca vaga como candidatada."""
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE vagas SET candidatou=1, data_candidatura=?, status='candidatado' WHERE id=?",
            (now, vaga_id),
        )
        conn.commit()
        return get_vaga(vaga_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admins
# ---------------------------------------------------------------------------

def create_admin(username: str, password_hash: str) -> dict:
    """Cria um admin."""
    admin_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO admins (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (admin_id, username, password_hash, now),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone())
    finally:
        conn.close()


def get_admin_by_username(username: str) -> Optional[dict]:
    """Busca admin por username."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_admin_password(admin_id: str, new_hash: str) -> None:
    """Atualiza senha do admin."""
    conn = get_connection()
    try:
        conn.execute("UPDATE admins SET password_hash = ? WHERE id = ?", (new_hash, admin_id))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Proxy Pool
# ---------------------------------------------------------------------------

def create_proxy(url: str, country: str = "BR", proxy_type: str = "socks5", label: str = "") -> dict:
    """Adiciona proxy ao pool."""
    proxy_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO proxy_pool (id, url, proxy_type, country, label, is_active, assigned_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, 0, ?)",
            (proxy_id, url, proxy_type, country, label, now),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM proxy_pool WHERE id = ?", (proxy_id,)).fetchone())
    finally:
        conn.close()


def list_proxies() -> list[dict]:
    """Lista todos os proxies do pool."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM proxy_pool ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_proxy(proxy_id: str) -> Optional[dict]:
    """Busca proxy por ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM proxy_pool WHERE id = ?", (proxy_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_proxy_by_url(url: str) -> Optional[dict]:
    """Busca proxy pela URL."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM proxy_pool WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_least_used_proxy() -> Optional[dict]:
    """Retorna o proxy ativo menos usado (round-robin simples)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM proxy_pool WHERE is_active = 1 ORDER BY assigned_count ASC, last_check ASC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_proxy(proxy_id: str, **kwargs) -> Optional[dict]:
    """Atualiza campos do proxy."""
    allowed = {"url", "country", "proxy_type", "label", "is_active", "assigned_count", "last_check"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_proxy(proxy_id)

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [proxy_id]

    conn = get_connection()
    try:
        conn.execute(f"UPDATE proxy_pool SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return get_proxy(proxy_id)
    finally:
        conn.close()


def delete_proxy(proxy_id: str) -> bool:
    """Remove proxy do pool."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM proxy_pool WHERE id = ?", (proxy_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# User Activation
# ---------------------------------------------------------------------------

def toggle_user_active(user_id: str) -> Optional[dict]:
    """Alterna is_active entre 0 e 1."""
    user = get_user(user_id)
    if not user:
        return None
    new_val = 0 if user.get("is_active", 1) else 1
    return update_user(user_id, is_active=new_val)


def toggle_user_auto_login(user_id: str) -> Optional[dict]:
    """Alterna auto_login entre 0 e 1."""
    user = get_user(user_id)
    if not user:
        return None
    new_val = 0 if user.get("auto_login", 0) else 1
    return update_user(user_id, auto_login=new_val)


def get_active_users() -> list[dict]:
    """Retorna apenas usuários ativos."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM users WHERE is_active = 1 ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# User Schedules
# ---------------------------------------------------------------------------

def save_schedule(user_id: str, schedule_json: str) -> dict:
    """Salva ou atualiza a agenda de um usuário."""
    import json as _json
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM user_schedules WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE user_schedules SET schedule_json=?, updated_at=? WHERE user_id=?",
                (schedule_json, now, user_id),
            )
        else:
            sid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO user_schedules (id, user_id, schedule_json, updated_at) VALUES (?, ?, ?, ?)",
                (sid, user_id, schedule_json, now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM user_schedules WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_schedule(user_id: str) -> Optional[dict]:
    """Busca agenda de um usuário."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM user_schedules WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_schedules() -> list[dict]:
    """Retorna todas as agendas."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT us.*, u.username FROM user_schedules us
            JOIN users u ON us.user_id = u.id
            ORDER BY u.username
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_schedule(user_id: str) -> bool:
    """Remove agenda de um usuário."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM user_schedules WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sniper Sessions
# ---------------------------------------------------------------------------

def create_sniper_session(session_id: str, target_time: str, ntp_offset_ms: float = 0) -> dict:
    """Cria registro de sessão sniper."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sniper_sessions (id, status, target_time, ntp_offset_ms, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, "armed", target_time, ntp_offset_ms, now),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM sniper_sessions WHERE id = ?", (session_id,)).fetchone())
    finally:
        conn.close()


def update_sniper_session(session_id: str, **kwargs) -> Optional[dict]:
    """Atualiza sessão sniper."""
    allowed = {"status", "ntp_offset_ms", "results_json", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return None

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]

    conn = get_connection()
    try:
        conn.execute(f"UPDATE sniper_sessions SET {set_clause} WHERE id = ?", values)
        conn.commit()
        row = conn.execute("SELECT * FROM sniper_sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_sniper_sessions(limit: int = 20) -> list[dict]:
    """Lista sessões sniper recentes."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM sniper_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
