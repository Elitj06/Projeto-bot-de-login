"""
CRUD de usuários — API REST.

Endpoints:
  POST   /api/users           — cadastrar usuário
  GET    /api/users           — listar usuários
  GET    /api/users/<id>      — buscar usuário
  DELETE /api/users/<id>      — remover usuário
  PUT    /api/users/<id>      — atualizar usuário
  POST   /api/users/<id>/toggle-human — toggle human mode
"""
from flask import Blueprint, request, jsonify

from dashboard.models import database as db

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


@users_bp.route("", methods=["GET"])
def list_users():
    """Lista todos os usuários cadastrados."""
    users = db.list_users()
    # Remove senha do retorno
    for u in users:
        u.pop("password_encrypted", None)
    return jsonify({"users": users, "total": len(users)})


@users_bp.route("", methods=["POST"])
def create_user():
    """Cadastra um novo usuário."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    proxy = data.get("proxy", "").strip() or None

    if not username or not password:
        return jsonify({"error": "username e password são obrigatórios"}), 400

    existing = db.get_user_by_username(username)
    if existing:
        return jsonify({"error": f"Usuário '{username}' já existe"}), 409

    user = db.create_user(username, password, proxy)
    user.pop("password_encrypted", None)
    return jsonify({"user": user, "message": "Usuário criado com sucesso"}), 201


@users_bp.route("/<user_id>", methods=["GET"])
def get_user(user_id: str):
    """Busca usuário por ID."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    user.pop("password_encrypted", None)
    return jsonify({"user": user})


@users_bp.route("/<user_id>", methods=["DELETE"])
def delete_user(user_id: str):
    """Remove um usuário."""
    if db.delete_user(user_id):
        return jsonify({"message": "Usuário removido com sucesso"})
    return jsonify({"error": "Usuário não encontrado"}), 404


@users_bp.route("/<user_id>", methods=["PUT"])
def update_user(user_id: str):
    """Atualiza dados do usuário."""
    data = request.get_json(silent=True) or {}
    allowed = {"username", "proxy", "is_active", "auto_login"}

    # Password atualiza como password_encrypted
    if "password" in data:
        allowed_with_pw = allowed | {"password_encrypted"}
        update_data = {k: v for k, v in data.items() if k in allowed_with_pw}
        if "password" in update_data:
            update_data["password_encrypted"] = update_data.pop("password")
    else:
        update_data = {k: v for k, v in data.items() if k in allowed}

    if not update_data:
        return jsonify({"error": "Nenhum campo válido para atualizar"}), 400

    user = db.update_user(user_id, **update_data)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    user.pop("password_encrypted", None)
    return jsonify({"user": user, "message": "Usuário atualizado"})


@users_bp.route("/<user_id>/toggle-active", methods=["POST"])
def toggle_active(user_id: str):
    """Ativa ou desativa o bot para um usuário."""
    user = db.toggle_user_active(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    user.pop("password_encrypted", None)
    status = "ATIVO" if user["is_active"] else "INATIVO"
    db.add_log(user_id, "toggle_active", "success", f"Usuário {status}")
    return jsonify({"user": user, "message": f"Bot {status} para {user['username']}"})


@users_bp.route("/<user_id>/toggle-auto-login", methods=["POST"])
def toggle_auto_login(user_id: str):
    """Ativa ou desativa login automático para um usuário."""
    user = db.toggle_user_auto_login(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    user.pop("password_encrypted", None)
    status = "ON" if user["auto_login"] else "OFF"
    return jsonify({"user": user, "message": f"Auto-login {status} para {user['username']}"})


@users_bp.route("/<user_id>/toggle-human", methods=["POST"])
def toggle_human(user_id: str):
    """Alterna modo comportamento humano ON/OFF."""
    user = db.toggle_human_mode(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    user.pop("password_encrypted", None)
    mode = "ON" if user["human_mode"] else "OFF"
    return jsonify({"user": user, "message": f"Modo humano: {mode}"})
