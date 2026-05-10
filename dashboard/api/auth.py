"""
Autenticação do admin — API REST.

Endpoints:
  POST /api/auth/login   — login do admin (retorna JWT)
  GET  /api/auth/status   — verifica se token é válido
  POST /api/auth/change-password — altera senha do admin
"""
import os
import uuid
from datetime import datetime, timezone

import bcrypt
from flask import Blueprint, request, jsonify, g

from dashboard.middleware.auth import generate_token, require_auth
from dashboard.models import database as db
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Admin defaults — pode ser alterado via env
DEFAULT_ADMIN_USER = os.getenv("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.getenv("ADMIN_PASS", "seap2026")


def _ensure_admin_exists():
    """Garante que o admin padrão existe no banco."""
    admin = db.get_admin_by_username(DEFAULT_ADMIN_USER)
    if not admin:
        hashed = bcrypt.hashpw(DEFAULT_ADMIN_PASS.encode(), bcrypt.gensalt()).decode()
        db.create_admin(DEFAULT_ADMIN_USER, hashed)
        logger.info(f"Admin padrão criado: {DEFAULT_ADMIN_USER}")


@auth_bp.route("/login", methods=["POST"])
def login():
    """Login do admin — retorna JWT."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "username e password obrigatórios"}), 400

    admin = db.get_admin_by_username(username)
    if not admin:
        return jsonify({"error": "Credenciais inválidas"}), 401

    if not bcrypt.checkpw(password.encode(), admin["password_hash"].encode()):
        db.add_log(None, "auth", "failed", f"Tentativa de login falha: {username}")
        return jsonify({"error": "Credenciais inválidas"}), 401

    token = generate_token(admin["id"], admin["username"])
    db.add_log(None, "auth", "success", f"Admin {username} logou")

    return jsonify({
        "token": token,
        "username": admin["username"],
        "expires_in_hours": 24,
    })


@auth_bp.route("/status", methods=["GET"])
def status():
    """Verifica se o token atual é válido (sem requerir auth)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"authenticated": False}), 200

    from dashboard.middleware.auth import verify_token
    payload = verify_token(auth_header[7:])
    if payload:
        return jsonify({"authenticated": True, "username": payload.get("username")})
    return jsonify({"authenticated": False}), 200


@auth_bp.route("/change-password", methods=["POST"])
@require_auth
def change_password():
    """Altera a senha do admin."""
    data = request.get_json(silent=True) or {}
    current = data.get("current_password", "")
    new = data.get("new_password", "")

    if not current or not new:
        return jsonify({"error": "current_password e new_password obrigatórios"}), 400

    if len(new) < 6:
        return jsonify({"error": "Nova senha deve ter no mínimo 6 caracteres"}), 400

    admin = db.get_admin_by_username(g.admin["username"])
    if not admin:
        return jsonify({"error": "Admin não encontrado"}), 404

    if not bcrypt.checkpw(current.encode(), admin["password_hash"].encode()):
        return jsonify({"error": "Senha atual incorreta"}), 401

    hashed = bcrypt.hashpw(new.encode(), bcrypt.gensalt()).decode()
    db.update_admin_password(admin["id"], hashed)
    db.add_log(None, "auth", "password_change", f"Senha alterada para {admin['username']}")

    return jsonify({"message": "Senha alterada com sucesso"})
