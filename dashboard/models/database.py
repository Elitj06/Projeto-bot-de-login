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
    allowed = {"username", "password_encrypted", "proxy", "human_mode"}
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
