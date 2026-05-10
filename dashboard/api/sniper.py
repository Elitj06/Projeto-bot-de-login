"""
Sniper API — Controle do motor de disparo de vagas.

Endpoints:
  GET  /api/sniper/status           — Status do sniper
  POST /api/sniper/ntp-sync          — Força sync NTP
  GET  /api/sniper/next-target       — Próxima quinta 06h BRT
  POST /api/sniper/prewarm           — Prepara browsers
  POST /api/sniper/fire              — Dispara login simultâneo
  POST /api/sniper/execute           — Pipeline completo
  POST /api/sniper/cancel            — Cancela execução
  GET  /api/sniper/sessions          — Histórico de sessões
  GET  /api/sniper/sessions/<id>     — Detalhe de sessão
"""
import asyncio
import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g

from dashboard.middleware.auth import require_auth
from dashboard.models import database as db
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

sniper_bp = Blueprint("sniper", __name__, url_prefix="/api/sniper")

# Instância global do engine
_sniper_engine = None


def get_engine():
    """Retorna instância singleton do SniperEngine."""
    global _sniper_engine
    if _sniper_engine is None:
        from sniper.engine import SniperEngine
        _sniper_engine = SniperEngine()
    return _sniper_engine


@sniper_bp.route("/status", methods=["GET"])
@require_auth
def status():
    """Status atual do sniper."""
    engine = get_engine()
    engine_status = engine.get_status()

    # NTP info
    from sniper.ntp_clock import ntp_clock
    ntp_info = {
        "offset_ms": round(ntp_clock.offset_ms, 2),
        "last_sync_ago": round(ntp_clock.last_sync_ago, 1),
        "sync_count": ntp_clock._sync_count,
    }

    # Stats
    users = db.list_users()
    active = sum(1 for u in users if u.get("is_active", 1))
    proxies = db.list_proxies()
    active_proxies = sum(1 for p in proxies if p["is_active"])

    return jsonify({
        **engine_status,
        "ntp": ntp_info,
        "users": {"total": len(users), "active": active},
        "proxies": {"total": len(proxies), "active": active_proxies},
    })


@sniper_bp.route("/ntp-sync", methods=["POST"])
@require_auth
def ntp_sync():
    """Força sincronização NTP."""
    from sniper.ntp_clock import ntp_clock

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(ntp_clock.sync(samples=5))
    finally:
        loop.close()

    return jsonify(result)


@sniper_bp.route("/next-target", methods=["GET"])
@require_auth
def next_target():
    """Retorna próxima quinta-feira 06h BRT."""
    from sniper.ntp_clock import get_thursday_6am_brt, ntp_clock, BRT

    target = get_thursday_6am_brt()
    now = ntp_clock.now()

    delta = (target - now).total_seconds()

    return jsonify({
        "target_utc": target.isoformat(),
        "target_brt": target.astimezone(BRT).isoformat(),
        "seconds_until": round(delta, 1),
        "hours_until": round(delta / 3600, 2),
        "days_until": round(delta / 86400, 2),
        "ntp_offset_ms": round(ntp_clock.offset_ms, 2),
    })


@sniper_bp.route("/prewarm", methods=["POST"])
@require_auth
def prewarm():
    """Prepara browsers de todos os usuários ativos."""
    data = request.get_json(silent=True) or {}
    user_ids = data.get("user_ids")  # Opcional: lista específica

    if user_ids:
        users = [db.get_user(uid) for uid in user_ids]
        users = [u for u in users if u]
    else:
        users = db.get_active_users()

    if not users:
        return jsonify({"error": "Nenhum usuário ativo encontrado"}), 400

    from sniper.engine import SniperUser

    sniper_users = []
    for u in users:
        su = SniperUser(
            id=u["id"],
            username=u["username"],
            password=u["password_encrypted"],
            proxy=u.get("proxy"),
            is_active=u.get("is_active", 1),
            auto_snipe=u.get("auto_login", 0),
        )

        # Carrega schedule do usuário
        schedule = db.get_schedule(u["id"])
        if schedule:
            sched_data = json.loads(schedule["schedule_json"])
            for day_data in sched_data.get("days", []):
                if day_data.get("enabled"):
                    su.target_days.append(day_data["day"])
                    su.target_times.extend(day_data.get("time_slots", []))

        sniper_users.append(su)

    engine = get_engine()

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(engine.prewarm(sniper_users))
    finally:
        loop.close()

    return jsonify(result)


@sniper_bp.route("/fire", methods=["POST"])
@require_auth
def fire():
    """Dispara submissão simultânea."""
    engine = get_engine()

    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(engine.fire())
    finally:
        loop.close()

    return jsonify({
        "results": [
            {"user_id": r.user_id, "username": r.username, "success": r.success,
             "time_ms": r.submit_time_ms, "error": r.error}
            for r in results
        ],
        "total": len(results),
        "successes": sum(1 for r in results if r.success),
    })


@sniper_bp.route("/arm", methods=["POST"])
@require_auth
def arm():
    """Arma o sniper e aguarda até o horário exato."""
    engine = get_engine()

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(engine.arm_and_wait())
    finally:
        loop.close()

    return jsonify(result)


@sniper_bp.route("/execute", methods=["POST"])
@require_auth
def execute():
    """Pipeline completo: prewarm → arm → fire → hunt."""
    data = request.get_json(silent=True) or {}
    user_ids = data.get("user_ids")

    if user_ids:
        users = [db.get_user(uid) for uid in user_ids]
        users = [u for u in users if u]
    else:
        users = db.get_active_users()

    if not users:
        return jsonify({"error": "Nenhum usuário ativo"}), 400

    from sniper.engine import SniperUser

    sniper_users = []
    for u in users:
        su = SniperUser(
            id=u["id"],
            username=u["username"],
            password=u["password_encrypted"],
            proxy=u.get("proxy"),
            is_active=u.get("is_active", 1),
            auto_snipe=u.get("auto_login", 0),
        )

        schedule = db.get_schedule(u["id"])
        if schedule:
            sched_data = json.loads(schedule["schedule_json"])
            for day_data in sched_data.get("days", []):
                if day_data.get("enabled"):
                    su.target_days.append(day_data["day"])
                    su.target_times.extend(day_data.get("time_slots", []))

        sniper_users.append(su)

    engine = get_engine()

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(engine.execute_full_pipeline(sniper_users))
    finally:
        loop.close()

    # Salva no banco
    if result.get("session_id"):
        db.create_sniper_session(
            session_id=result["session_id"],
            target_time=result.get("fired_at", ""),
            ntp_offset_ms=result.get("ntp_offset_ms", 0),
        )
        db.update_sniper_session(
            result["session_id"],
            status="complete",
            results_json=json.dumps(result.get("login_results", [])),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    return jsonify(result)


@sniper_bp.route("/cancel", methods=["POST"])
@require_auth
def cancel():
    """Cancela execução atual."""
    engine = get_engine()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(engine.cancel())
    finally:
        loop.close()

    return jsonify({"message": "Sniper cancelado"})


@sniper_bp.route("/sessions", methods=["GET"])
@require_auth
def list_sessions():
    """Lista sessões sniper."""
    sessions = db.list_sniper_sessions()
    return jsonify({"sessions": sessions})


@sniper_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth
def get_session(session_id: str):
    """Detalhe de uma sessão."""
    sessions = db.list_sniper_sessions(limit=100)
    for s in sessions:
        if s["id"] == session_id:
            return jsonify({"session": s})
    return jsonify({"error": "Sessão não encontrada"}), 404
