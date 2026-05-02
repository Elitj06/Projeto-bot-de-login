"""
Endpoints de vagas — API REST.

Endpoints:
  POST /api/users/<id>/vagas                        — listar vagas
  POST /api/users/<id>/vagas/<vaga_id>/candidatar    — candidatar a vaga
  GET  /api/users/<id>/vagas                        — listar vagas do banco
"""
import asyncio

from flask import Blueprint, jsonify

from dashboard.models import database as db
from dashboard.services.vaga_service import vaga_service
from dashboard.services.session_manager import session_manager

vagas_bp = Blueprint("vagas", __name__, url_prefix="/api/users")


@vagas_bp.route("/<user_id>/vagas", methods=["GET"])
def list_vagas(user_id: str):
    """Lista vagas do banco local para o usuário."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    vagas = db.list_vagas(user_id)
    return jsonify({"vagas": vagas, "total": len(vagas)})


@vagas_bp.route("/<user_id>/vagas", methods=["POST"])
def fetch_vagas(user_id: str):
    """Busca vagas no SEAP (requer sessão ativa)."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    loop = asyncio.new_event_loop()
    try:
        vagas = loop.run_until_complete(vaga_service.listar_vagas(user_id))
    finally:
        loop.close()

    return jsonify({"vagas": vagas, "total": len(vagas)})


@vagas_bp.route("/<user_id>/vagas/<vaga_id>/candidatar", methods=["POST"])
def candidatar_vaga(user_id: str, vaga_id: str):
    """Candidata o usuário a uma vaga."""
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(vaga_service.candidatar(user_id, vaga_id))
    finally:
        loop.close()

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code
