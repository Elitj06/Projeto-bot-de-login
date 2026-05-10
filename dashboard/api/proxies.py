"""
Gerenciamento do Pool de Proxies — API REST.

Endpoints:
  GET    /api/proxies             — listar proxies
  POST   /api/proxies             — adicionar proxy
  DELETE /api/proxies/<id>        — remover proxy
  PUT    /api/proxies/<id>        — atualizar proxy
  POST   /api/proxies/<id>/test   — testar conectividade
  POST   /api/proxies/test-all    — testar todos
  GET    /api/proxies/stats       — estatísticas do pool
"""
import asyncio
import time
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from dashboard.middleware.auth import require_auth
from dashboard.models import database as db
from dashboard.services.proxy_manager import ProxyManager
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

proxies_bp = Blueprint("proxies", __name__, url_prefix="/api/proxies")

proxy_manager = ProxyManager()


@proxies_bp.route("", methods=["GET"])
@require_auth
def list_proxies():
    """Lista todos os proxies do pool."""
    proxies = db.list_proxies()
    return jsonify({"proxies": proxies, "total": len(proxies)})


@proxies_bp.route("", methods=["POST"])
@require_auth
def add_proxy():
    """Adiciona um proxy ao pool."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    country = data.get("country", "BR").strip().upper()
    proxy_type = data.get("type", "socks5").strip()
    label = data.get("label", "").strip()

    if not url:
        return jsonify({"error": "URL do proxy obrigatória (socks5://user:pass@host:port)"}), 400

    existing = db.get_proxy_by_url(url)
    if existing:
        return jsonify({"error": "Proxy já existe no pool"}), 409

    proxy = db.create_proxy(url=url, country=country, proxy_type=proxy_type, label=label)
    db.add_log(None, "proxy", "added", f"Proxy adicionado: {label or url[:30]}")
    return jsonify({"proxy": proxy, "message": "Proxy adicionado"}), 201


@proxies_bp.route("/batch", methods=["POST"])
@require_auth
def add_proxies_batch():
    """Adiciona múltiplos proxies de uma vez (texto, um por linha)."""
    data = request.get_json(silent=True) or {}
    text = data.get("proxies", "").strip()
    country = data.get("country", "BR").strip().upper()

    if not text:
        return jsonify({"error": "Envie os proxies no campo 'proxies', um por linha"}), 400

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    added = 0
    skipped = 0
    errors = []

    for line in lines:
        # Parse: socks5://user:pass@host:port ou host:port:user:pass
        url = line
        if not line.startswith(("socks5://", "socks4://", "http://", "https://")):
            # Formato host:port:user:pass
            parts = line.split(":")
            if len(parts) == 4:
                url = f"socks5://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
            elif len(parts) == 2:
                url = f"socks5://{parts[0]}:{parts[1]}"
            else:
                errors.append(f"Formato inválido: {line}")
                continue

        existing = db.get_proxy_by_url(url)
        if existing:
            skipped += 1
            continue

        db.create_proxy(url=url, country=country)
        added += 1

    db.add_log(None, "proxy", "batch_add", f"Batch: {added} adicionados, {skipped} duplicados, {len(errors)} erros")
    return jsonify({
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "message": f"{added} proxies adicionados, {skipped} duplicados ignorados",
    })


@proxies_bp.route("/<proxy_id>", methods=["GET"])
@require_auth
def get_proxy(proxy_id: str):
    """Busca proxy por ID."""
    proxy = db.get_proxy(proxy_id)
    if not proxy:
        return jsonify({"error": "Proxy não encontrado"}), 404
    return jsonify({"proxy": proxy})


@proxies_bp.route("/<proxy_id>", methods=["DELETE"])
@require_auth
def delete_proxy(proxy_id: str):
    """Remove um proxy do pool."""
    if db.delete_proxy(proxy_id):
        db.add_log(None, "proxy", "removed", f"Proxy {proxy_id[:8]} removido")
        return jsonify({"message": "Proxy removido"})
    return jsonify({"error": "Proxy não encontrado"}), 404


@proxies_bp.route("/<proxy_id>", methods=["PUT"])
@require_auth
def update_proxy(proxy_id: str):
    """Atualiza dados do proxy."""
    data = request.get_json(silent=True) or {}
    allowed = {"url", "country", "proxy_type", "label", "is_active"}

    update_data = {k: v for k, v in data.items() if k in allowed}
    if not update_data:
        return jsonify({"error": "Nenhum campo válido"}), 400

    proxy = db.update_proxy(proxy_id, **update_data)
    if not proxy:
        return jsonify({"error": "Proxy não encontrado"}), 404
    return jsonify({"proxy": proxy, "message": "Proxy atualizado"})


@proxies_bp.route("/<proxy_id>/test", methods=["POST"])
@require_auth
def test_proxy(proxy_id: str):
    """Testa conectividade de um proxy."""
    proxy = db.get_proxy(proxy_id)
    if not proxy:
        return jsonify({"error": "Proxy não encontrado"}), 404

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(proxy_manager.test_proxy(proxy["url"]))
    finally:
        loop.close()

    # Atualiza status no banco
    db.update_proxy(proxy_id, is_active=1 if result["success"] else 0)

    return jsonify(result)


@proxies_bp.route("/test-all", methods=["POST"])
@require_auth
def test_all_proxies():
    """Testa todos os proxies do pool."""
    proxies = db.list_proxies()

    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(proxy_manager.test_all([p["url"] for p in proxies]))
    finally:
        loop.close()

    # Atualiza status no banco
    working = 0
    for proxy, result in zip(proxies, results):
        if result["success"]:
            working += 1
            db.update_proxy(proxy["id"], is_active=1, last_check=result["timestamp"])
        else:
            db.update_proxy(proxy["id"], is_active=0, last_check=result["timestamp"])

    return jsonify({
        "total": len(proxies),
        "working": working,
        "failed": len(proxies) - working,
        "results": results,
    })


@proxies_bp.route("/stats", methods=["GET"])
@require_auth
def proxy_stats():
    """Estatísticas do pool de proxies."""
    proxies = db.list_proxies()
    active = sum(1 for p in proxies if p["is_active"])
    by_country = {}
    for p in proxies:
        c = p.get("country", "??")
        by_country[c] = by_country.get(c, 0) + 1

    return jsonify({
        "total": len(proxies),
        "active": active,
        "inactive": len(proxies) - active,
        "by_country": by_country,
    })


@proxies_bp.route("/assign/<user_id>", methods=["POST"])
@require_auth
def assign_proxy(user_id: str):
    """Atribui automaticamente o melhor proxy disponível a um usuário."""
    user = db.get_user(user_id)
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    # Busca proxy menos usado que esteja ativo
    proxy = db.get_least_used_proxy()
    if not proxy:
        return jsonify({"error": "Nenhum proxy disponível no pool"}), 404

    # Atribui ao usuário
    db.update_user(user_id, proxy=proxy["url"])
    db.update_proxy(proxy["id"], assigned_count=proxy.get("assigned_count", 0) + 1)

    return jsonify({
        "proxy": proxy,
        "message": f"Proxy {proxy.get('label', proxy['url'][:30])} atribuído a {user['username']}",
    })
