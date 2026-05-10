"""
Middleware de autenticação JWT para o Dashboard.

Protege todos os endpoints /api/* exceto /api/auth/login.
Token JWT no header Authorization: Bearer <token>.
"""
import os
import functools
from datetime import datetime, timezone, timedelta

import jwt
from flask import request, jsonify, g

JWT_SECRET = os.getenv("JWT_SECRET", "seap-bot-jwt-secret-2026-CHANGE-ME")
JWT_EXPIRATION_HOURS = 24
ALGORITHM = "HS256"


def generate_token(admin_id: str, username: str) -> str:
    """Gera JWT token para admin."""
    payload = {
        "sub": admin_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    """Verifica e decodifica JWT. Retorna payload ou None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_auth(f):
    """Decorator que exige JWT válido em endpoints Flask."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token não fornecido"}), 401

        token = auth_header[7:]
        payload = verify_token(token)
        if not payload:
            return jsonify({"error": "Token inválido ou expirado"}), 401

        g.admin = payload
        return f(*args, **kwargs)

    return decorated


def is_auth_whitelisted(path: str) -> bool:
    """Retorna True se o path não precisa de autenticação."""
    whitelist = [
        "/api/auth/login",
        "/api/auth/status",
    ]
    return path in whitelist
