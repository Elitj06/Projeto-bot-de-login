"""
Calendário de Vagas — API REST.

Endpoints:
  GET    /api/schedule/<user_id>    — Busca agenda do usuário
  PUT    /api/schedule/<user_id>    — Salva agenda do usuário
  GET    /api/schedules             — Lista todas as agendas
  DELETE /api/schedule/<user_id>    — Remove agenda
"""
import json

from flask import Blueprint, request, jsonify

from dashboard.middleware.auth import require_auth
from dashboard.models import database as db
from user_calendar.schedule import (
    UserSchedule, DaySchedule, DAYS_OF_WEEK, DEFAULT_TIME_SLOTS
)
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")


@schedule_bp.route("/<user_id>", methods=["GET"])
@require_auth
def get_schedule(user_id: str):
    """Busca agenda de um usuário."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    schedule = db.get_schedule(user_id)
    if schedule:
        sched_data = json.loads(schedule["schedule_json"])
        return jsonify({"user_id": user_id, "username": user["username"], "schedule": sched_data})
    else:
        # Retorna agenda vazia
        empty = UserSchedule(user_id=user_id, username=user["username"])
        return jsonify({"user_id": user_id, "username": user["username"], "schedule": empty.to_dict()})


@schedule_bp.route("/<user_id>", methods=["PUT"])
@require_auth
def save_schedule(user_id: str):
    """Salva/atualiza agenda de um usuário."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    data = request.get_json(silent=True) or {}
    schedule_data = data.get("schedule", data)

    # Validação básica
    days = schedule_data.get("days", [])
    for d in days:
        if d.get("day") not in DAYS_OF_WEEK:
            return jsonify({"error": f"Dia inválido: {d.get('day')}"}), 400
        for slot in d.get("time_slots", []):
            if "-" not in slot:
                return jsonify({"error": f"Slot inválido: {slot}"}), 400

    schedule_json = json.dumps(schedule_data)
    result = db.save_schedule(user_id, schedule_json)

    db.add_log(user_id, "schedule", "updated", f"Agenda atualizada para {user['username']}")

    return jsonify({"message": "Agenda salva", "schedule": schedule_data})


@schedule_bp.route("/<user_id>", methods=["DELETE"])
@require_auth
def delete_schedule(user_id: str):
    """Remove agenda de um usuário."""
    if db.delete_schedule(user_id):
        return jsonify({"message": "Agenda removida"})
    return jsonify({"error": "Agenda não encontrada"}), 404


@schedule_bp.route("s", methods=["GET"])
@require_auth
def list_schedules():
    """Lista todas as agendas."""
    schedules = db.get_all_schedules()
    result = []
    for s in schedules:
        try:
            sched_data = json.loads(s["schedule_json"])
            result.append({
                "user_id": s["user_id"],
                "username": s.get("username", ""),
                "schedule": sched_data,
                "updated_at": s.get("updated_at"),
            })
        except Exception:
            continue

    return jsonify({"schedules": result, "total": len(result)})


@schedule_bp.route("/defaults", methods=["GET"])
@require_auth
def get_defaults():
    """Retorna dias e slots padrão para o frontend."""
    return jsonify({
        "days": DAYS_OF_WEEK,
        "day_labels": {
            "seg": "Segunda", "ter": "Terça", "qua": "Quarta",
            "qui": "Quinta", "sex": "Sexta", "sab": "Sábado", "dom": "Domingo",
        },
        "default_time_slots": DEFAULT_TIME_SLOTS,
    })
