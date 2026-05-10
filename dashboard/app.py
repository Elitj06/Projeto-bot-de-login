"""
Aplicação Flask + Flask-SocketIO para Dashboard SEAP Bot.

- Serve o dashboard HTML em /
- Registra blueprints da API REST
- WebSocket em /ws para updates em tempo real
- CORS configurado para acesso externo
"""
import os
import sys

# Garante que o diretório raiz do projeto está no path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS

from dashboard.models import database as db
from dashboard.api.auth import auth_bp, _ensure_admin_exists
from dashboard.api.users import users_bp
from dashboard.api.login import login_bp, set_login_service
from dashboard.api.vagas import vagas_bp
from dashboard.api.proxies import proxies_bp
from dashboard.api.sniper import sniper_bp
from dashboard.api.schedule import schedule_bp
from dashboard.services.login_service import LoginService
from dashboard.services.session_manager import session_manager
from dashboard.middleware.auth import is_auth_whitelisted, verify_token
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


def create_app() -> tuple[Flask, SocketIO]:
    """
    Cria e configura a aplicação Flask + SocketIO.

    Returns:
        Tupla (app, socketio)
    """
    # Inicializa banco + admin
    db.init_db()
    _ensure_admin_exists()

    # Flask app
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "seap-bot-secret-key-2026")

    # CORS para acesso externo
    CORS(app, resources={r"/api/*": {"origins": "*"}, r"/ws": {"origins": "*"}})

    # SocketIO com eventlet
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        ping_timeout=60,
        ping_interval=25,
    )

    # --- WebSocket event emitter ---
    def ws_emit_event(user_id: str, event_type: str, data: dict) -> None:
        """Emite evento WebSocket para todos os clientes conectados."""
        payload = {"user_id": user_id, "type": event_type, **data}
        socketio.emit("status_update", payload, namespace="/")

    # --- Login Service com WebSocket ---
    login_service = LoginService(emit_event=ws_emit_event)
    set_login_service(login_service)

    # --- Registra blueprints ---
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(login_bp)
    app.register_blueprint(vagas_bp)
    app.register_blueprint(proxies_bp)
    app.register_blueprint(sniper_bp)
    app.register_blueprint(schedule_bp)

    # --- Rotas de páginas ---
    @app.route("/")
    def index():
        """Serve o dashboard."""
        return send_from_directory(
            os.path.join(os.path.dirname(__file__), "templates"),
            "index.html",
        )

    @app.route("/logs")
    def logs_page():
        """Retorna logs recentes como JSON."""
        return {"logs": db.get_recent_logs(limit=200)}

    # --- Auth middleware (before_request) ---
    @app.before_request
    def check_auth():
        """Verifica JWT em todas as rotas /api/* exceto whitelist."""
        if not request.path.startswith("/api/"):
            return None
        if request.path.startswith("/api/auth/"):
            return None
        if is_auth_whitelisted(request.path):
            return None

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Autenticação necessária"}), 401

        payload = verify_token(auth_header[7:])
        if not payload:
            return jsonify({"error": "Token inválido ou expirado"}), 401

        from flask import g
        g.admin = payload
        return None

    # --- WebSocket handlers ---
    @socketio.on("connect")
    def handle_connect():
        """Cliente conectou ao WebSocket."""
        logger.info("Cliente WebSocket conectado")
        emit("connected", {"message": "Conectado ao SEAP Bot Dashboard"})

    @socketio.on("disconnect")
    def handle_disconnect():
        """Cliente desconectou."""
        logger.info("Cliente WebSocket desconectado")

    @socketio.on("request_status")
    def handle_request_status(data):
        """Cliente pediu status de um usuário."""
        user_id = data.get("user_id") if data else None
        if user_id:
            user = db.get_user(user_id)
            if user:
                session = db.get_active_session(user_id)
                emit("status_update", {
                    "user_id": user_id,
                    "type": "current_status",
                    "status": session["status"] if session else "inactive",
                    "username": user["username"],
                    "human_mode": user["human_mode"],
                })

    return app, socketio


def main() -> None:
    """Ponto de entrada do dashboard."""
    app, socketio = create_app()

    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    print()
    print("=" * 60)
    print("  SEAP BOT DASHBOARD v2")
    print(f"  http://{host}:{port}")
    print("=" * 60)
    print()

    logger.info(f"Dashboard iniciando em {host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
