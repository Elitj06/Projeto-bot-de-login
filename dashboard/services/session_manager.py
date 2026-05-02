"""
Gerenciador de sessões persistentes.

Mantém pool de sessões ativas (navegadores abertos) para reutilização.
Se a sessão expirar, refaz login automaticamente.
"""
import asyncio
from typing import Optional

from playwright.async_api import Page

from core.logger import LoggerFactory
from dashboard.models import database as db

logger = LoggerFactory.get_logger(__name__)


class SessionManager:
    """
    Pool de sessões ativas.

    Cada sessão mapeia um user_id para uma Page do Camoufox.
    """

    def __init__(self):
        self._sessions: dict[str, Page] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, user_id: str) -> Optional[Page]:
        """Retorna a sessão ativa de um usuário, se existir."""
        async with self._lock:
            return self._sessions.get(user_id)

    async def register_session(self, user_id: str, page: Page) -> None:
        """Registra uma sessão ativa."""
        async with self._lock:
            self._sessions[user_id] = page
            logger.info(f"Sessão registrada para {user_id[:8]}...")

    async def remove_session(self, user_id: str) -> None:
        """Remove e fecha uma sessão."""
        async with self._lock:
            page = self._sessions.pop(user_id, None)
            if page and not page.is_closed():
                try:
                    await page.close()
                except Exception as e:
                    logger.warning(f"Erro ao fechar página: {e}")

    async def is_session_valid(self, user_id: str) -> bool:
        """Verifica se a sessão do usuário ainda é válida."""
        async with self._lock:
            page = self._sessions.get(user_id)
            if not page:
                return False
            if page.is_closed():
                self._sessions.pop(user_id, None)
                return False
            # Tenta verificar se a página ainda responde
            try:
                url = page.url
                return True
            except Exception:
                self._sessions.pop(user_id, None)
                return False

    async def get_all_active(self) -> dict[str, str]:
        """Retorna dict de user_id -> URL atual para todas as sessões."""
        result = {}
        async with self._lock:
            for uid, page in self._sessions.items():
                try:
                    result[uid] = page.url if not page.is_closed() else "closed"
                except Exception:
                    result[uid] = "error"
        return result

    async def cleanup_all(self) -> None:
        """Fecha todas as sessões."""
        async with self._lock:
            for uid, page in self._sessions.items():
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass
            self._sessions.clear()
            logger.info("Todas as sessões foram encerradas")


# Singleton
session_manager = SessionManager()
