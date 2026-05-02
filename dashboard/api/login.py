"""
Endpoints de login — API REST.

Endpoints:
  POST /api/users/<id>/login  — executar login
  POST /api/login-all         — login de todos em paralelo
  GET  /api/status            — status geral
"""
import asyncio

from flask import Blueprint, request, jsonify

from dashboard.models import database as db
from dashboard.services.login_service import LoginService

login_bp = Blueprint("login", __name__, url_prefix="/api")

# Referência global ao login_service — configurada em app.py
_login_service: LoginService | None = None


def set_login_service(service: LoginService) -> None:
    """Injeta o LoginService compartilhado."""
    global _login_service
    _login_service = service


def _get_service() -> LoginService:
    if not _login_service:
        raise RuntimeError("LoginService não inicializado")
    return _login_service


@login_bp.route("/users/<user_id>/login", methods=["POST"])
def login_user(user_id: str):
    """Executa login para um usuário específico."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    service = _get_service()

    # Executa login assíncrono dentro do loop do Flask-SocketIO
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(service.execute_login(user_id))
    finally:
        loop.close()

    return jsonify(result)


@login_bp.route("/login-all", methods=["POST"])
def login_all():
    """Executa login de todos os usuários em paralelo."""
    service = _get_service()
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(service.execute_login_all())
    finally:
        loop.close()

    success_count = sum(1 for r in results if r.get("success"))
    return jsonify({
        "results": results,
        "total": len(results),
        "success": success_count,
        "failed": len(results) - success_count,
    })


@login_bp.route("/status", methods=["GET"])
def get_status():
    """Retorna status geral do sistema."""
    users = db.list_users()
    total = len(users)
    human_count = sum(1 for u in users if u["human_mode"])
    with_proxy = sum(1 for u in users if u.get("proxy"))

    # Sessões ativas
    active_sessions = 0
    for u in users:
        session = db.get_active_session(u["id"])
        if session and session["status"] == "active":
            active_sessions += 1

    recent_logs = db.get_recent_logs(limit=5)

    return jsonify({
        "total_users": total,
        "human_mode_count": human_count,
        "with_proxy": with_proxy,
        "active_sessions": active_sessions,
        "recent_logs": recent_logs,
    })
