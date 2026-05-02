"""
Serviço de login — orquestra o bot SEAP com suporte a proxy e modo humano.

Usa o código existente (StealthBrowserManager, SeapLoginBot) e adiciona:
- Suporte a proxy SOCKS5 por usuário
- Toggle modo rápido vs comportamento humano
- Emissão de eventos WebSocket em tempo real
"""
import asyncio
import time
from typing import Optional, Callable

from automation.login_bot import LoginCredentials, SeapLoginBot
from core.browser_manager import StealthBrowserManager
from core.logger import LoggerFactory
from dashboard.models import database as db

from camoufox.async_api import AsyncCamoufox

logger = LoggerFactory.get_logger(__name__)


class LoginService:
    """
    Executa logins SEAP integrados com o dashboard.

    Emite eventos via callback para WebSocket em tempo real.
    Suporta proxy SOCKS5 e toggle human/fast mode.
    """

    def __init__(self, emit_event: Optional[Callable] = None):
        """
        Args:
            emit_event: Função para emitir eventos WebSocket.
                        Assinatura: emit_event(user_id, event_type, data)
        """
        self._emit_event = emit_event or self._noop_emit
        self._active_tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def _noop_emit(user_id: str, event_type: str, data: dict) -> None:
        """No-op emitter para quando não há WebSocket conectado."""
        pass

    async def execute_login(self, user_id: str) -> dict:
        """
        Executa login para um usuário específico.

        Returns:
            Dict com success, message, elapsed_seconds
        """
        user = db.get_user(user_id)
        if not user:
            return {"success": False, "message": "Usuário não encontrado"}

        credentials = LoginCredentials(
            username=user["username"],
            password=user["password_encrypted"],
        )
        if not credentials.is_valid():
            return {"success": False, "message": "Credenciais inválidas"}

        human_mode = bool(user["human_mode"])
        proxy = user.get("proxy")
        start_time = time.time()

        try:
            self._emit(user_id, "status", {"status": "connecting", "message": "Iniciando navegador..."})
            db.add_log(user_id, "login", "started", "Iniciando processo de login")

            async with self._create_browser(proxy, human_mode) as page:
                bot = SeapLoginBot(page)

                self._emit(user_id, "status", {"status": "navigating", "message": "Navegando para SEAP..."})
                result = await bot.execute_login(credentials)

                elapsed = time.time() - start_time

                if result.success:
                    # Registra sessão ativa
                    db.deactivate_user_sessions(user_id)
                    db.create_session(user_id)
                    db.add_log(user_id, "login", "success", f"Login OK em {elapsed:.1f}s")
                    self._emit(user_id, "status", {
                        "status": "success",
                        "message": f"Login realizado em {elapsed:.1f}s",
                        "elapsed": round(elapsed, 1),
                    })
                else:
                    db.add_log(user_id, "login", "failed", result.message)
                    self._emit(user_id, "status", {
                        "status": "failed",
                        "message": result.message,
                        "elapsed": round(elapsed, 1),
                    })

                return {
                    "success": result.success,
                    "message": result.message,
                    "elapsed_seconds": round(elapsed, 1),
                }

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"{type(e).__name__}: {e}"
            db.add_log(user_id, "login", "error", error_msg)
            self._emit(user_id, "status", {
                "status": "error",
                "message": error_msg,
                "elapsed": round(elapsed, 1),
            })
            logger.exception(f"Erro no login de {user['username']}")
            return {"success": False, "message": error_msg, "elapsed_seconds": round(elapsed, 1)}

    async def execute_login_all(self) -> list[dict]:
        """Executa login de todos os usuários em paralelo."""
        users = db.list_users()
        if not users:
            return []

        self._emit("__all__", "status", {"status": "batch_start", "total": len(users)})

        tasks = []
        for user in users:
            task = asyncio.create_task(self.execute_login(user["id"]))
            self._active_tasks[user["id"]] = task
            tasks.append((user["id"], task))

        results = []
        for user_id, task in tasks:
            try:
                result = await task
                result["user_id"] = user_id
                results.append(result)
            except Exception as e:
                results.append({"user_id": user_id, "success": False, "message": str(e)})
            finally:
                self._active_tasks.pop(user_id, None)

        self._emit("__all__", "status", {"status": "batch_complete", "results": results})
        return results

    def cancel_login(self, user_id: str) -> bool:
        """Cancela uma tarefa de login em andamento."""
        task = self._active_tasks.get(user_id)
        if task and not task.done():
            task.cancel()
            self._active_tasks.pop(user_id, None)
            self._emit(user_id, "status", {"status": "cancelled", "message": "Login cancelado"})
            return True
        return False

    def _emit(self, user_id: str, event_type: str, data: dict) -> None:
        """Emite evento com user_id embutido."""
        try:
            self._emit_event(user_id, event_type, data)
        except Exception as e:
            logger.warning(f"Erro ao emitir evento WebSocket: {e}")

    def _create_browser(self, proxy: Optional[str], human_mode: bool):
        """
        Cria instância do Camoufox com proxy opcional.

        Retorna um context manager assíncrono que entrega uma Page.
        """
        from config import camoufox_config

        return _BrowserContext(proxy, human_mode)


class _BrowserContext:
    """Context manager que cria browser Camoufox com proxy."""

    def __init__(self, proxy: Optional[str], human_mode: bool):
        self._proxy = proxy
        self._human_mode = human_mode
        self._camoufox: Optional[AsyncCamoufox] = None
        self._browser = None
        self._page = None

    async def __aenter__(self):
        from config import camoufox_config

        kwargs = dict(
            headless=camoufox_config.headless,
            humanize=camoufox_config.humanize_max_seconds if self._human_mode else False,
            os=camoufox_config.os_simulation,
            block_images=camoufox_config.block_images,
            locale=camoufox_config.locale,
            geoip=bool(self._proxy),
            i_know_what_im_doing=True,
        )

        if self._proxy:
            kwargs["proxy"] = {"server": self._proxy}

        self._camoufox = AsyncCamoufox(**kwargs)
        self._browser = await self._camoufox.__aenter__()
        self._page = await self._browser.new_page()
        return self._page

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._page:
                await self._page.close()
            if self._camoufox:
                await self._camoufox.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.warning(f"Erro ao fechar browser: {e}")
