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


@login_bp.route("/execution-plan", methods=["GET"])
def execution_plan():
    """Retorna o plano de execução para login em massa."""
    users = db.get_active_users()
    proxies = db.list_proxies()
    active_proxies = [p["url"] for p in proxies if p["is_active"]]

    from dashboard.services.proxy_manager import LoginScheduler
    scheduler = LoginScheduler()
    plan = scheduler.get_execution_plan(users, active_proxies)
    return jsonify(plan)


@login_bp.route("/status", methods=["GET"])
def get_status():
    """Retorna status geral do sistema."""
    users = db.list_users()
    total = len(users)
    active = sum(1 for u in users if u.get("is_active", 1))
    human_count = sum(1 for u in users if u["human_mode"])
    with_proxy = sum(1 for u in users if u.get("proxy"))
    auto_login = sum(1 for u in users if u.get("auto_login", 0))

    # Sessões ativas
    active_sessions = 0
    for u in users:
        session = db.get_active_session(u["id"])
        if session and session["status"] == "active":
            active_sessions += 1

    # Proxy pool
    proxies = db.list_proxies()
    active_proxies = sum(1 for p in proxies if p["is_active"])

    recent_logs = db.get_recent_logs(limit=5)

    return jsonify({
        "total_users": total,
        "active_users": active,
        "auto_login_users": auto_login,
        "human_mode_count": human_count,
        "with_proxy": with_proxy,
        "active_sessions": active_sessions,
        "proxy_pool": {"total": len(proxies), "active": active_proxies},
        "recent_logs": recent_logs,
    })


@login_bp.route("/users/<user_id>/full-flow", methods=["POST"])
def full_flow(user_id: str):
    """Executa fluxo completo: login + filtro de vagas com segundo CAPTCHA."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    data = request.get_json(silent=True) or {}
    filter_unit = data.get("filter_unit", user.get("filter_unit", ""))
    filter_date = data.get("filter_date", user.get("filter_date", ""))

    service = _get_service()
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            service.execute_full_flow(
                user_id,
                filter_unit=filter_unit,
                filter_date=filter_date,
            )
        )
    finally:
        loop.close()

    return jsonify(result)


@login_bp.route("/users/<user_id>/close-browser", methods=["POST"])
def close_browser(user_id: str):
    """Fecha o browser persistente de um usuário."""
    service = _get_service()
    loop = asyncio.new_event_loop()
    try:
        closed = loop.run_until_complete(service.close_user_browser(user_id))
    finally:
        loop.close()

    return jsonify({"closed": closed})
