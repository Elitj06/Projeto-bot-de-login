"""
Serviço de vagas — lista e candidata vagas no SEAP.

Requer uma sessão ativa (página logada) para funcionar.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import Page

from core.logger import LoggerFactory
from dashboard.models import database as db
from dashboard.services.session_manager import session_manager

logger = LoggerFactory.get_logger(__name__)


class VagaService:
    """Opera sobre vagas do SEAP usando sessões ativas."""

    # URL base para vagas no SEAP (placeholder — ajustar conforme site real)
    VAGAS_URL = "https://seapsistema.rj.gov.br/vagas"
    VAGAS_LIST_SELECTOR = ".vaga-item, .vacancy-item, table tbody tr"
    VAGA_TITULO_SELECTOR = ".vaga-titulo, .vacancy-title, td:nth-child(1)"
    VAGA_DESC_SELECTOR = ".vaga-descricao, .vacancy-description, td:nth-child(2)"
    CANDIDATAR_BTN_SELECTOR = "button.candidatar, a.candidatar, button:has-text('Candidatar')"

    async def listar_vagas(self, user_id: str) -> list[dict]:
        """
        Lista vagas disponíveis para o usuário.

        Returns:
            Lista de dicts com id, titulo, descricao, status
        """
        page = await session_manager.get_session(user_id)
        if not page:
            # Se não tem sessão ativa, retorna vagas do banco
            return db.list_vagas(user_id)

        try:
            await page.goto(self.VAGAS_URL, wait_until="networkidle", timeout=30000)
            vagas_elements = await page.query_selector_all(self.VAGAS_LIST_SELECTOR)

            vagas = []
            for elem in vagas_elements:
                titulo_el = await elem.query_selector(self.VAGA_TITULO_SELECTOR)
                desc_el = await elem.query_selector(self.VAGA_DESC_SELECTOR)
                titulo = await titulo_el.inner_text() if titulo_el else "Sem título"
                descricao = await desc_el.inner_text() if desc_el else ""

                vaga_id = str(uuid.uuid4())
                vaga = db.upsert_vaga(
                    vaga_id=vaga_id,
                    user_id=user_id,
                    titulo=titulo.strip(),
                    descricao=descricao.strip(),
                )
                vagas.append(vaga)

            logger.info(f"{len(vagas)} vagas encontradas para {user_id[:8]}...")
            return vagas

        except Exception as e:
            logger.error(f"Erro ao listar vagas: {e}")
            # Fallback para banco local
            return db.list_vagas(user_id)

    async def candidatar(self, user_id: str, vaga_id: str) -> dict:
        """
        Candidata o usuário a uma vaga.

        Returns:
            Dict com success e message
        """
        vaga = db.get_vaga(vaga_id)
        if not vaga:
            return {"success": False, "message": "Vaga não encontrada"}

        if vaga["candidatou"]:
            return {"success": False, "message": "Já candidatado a esta vaga"}

        page = await session_manager.get_session(user_id)
        if not page:
            return {"success": False, "message": "Sem sessão ativa. Faça login primeiro."}

        try:
            # Navega para a vaga e clica em candidatar
            await page.goto(self.VAGAS_URL, wait_until="networkidle", timeout=30000)

            btn = await page.query_selector(self.CANDIDATAR_BTN_SELECTOR)
            if btn:
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)

            vaga = db.mark_vaga_candidatada(vaga_id)
            db.add_log(user_id, "vaga_candidatar", "success", f"Candidatado a: {vaga['titulo']}")

            return {"success": True, "message": f"Candidatado a: {vaga['titulo']}", "vaga": vaga}

        except Exception as e:
            error_msg = f"Erro ao candidatar: {type(e).__name__}: {e}"
            db.add_log(user_id, "vaga_candidatar", "error", error_msg)
            return {"success": False, "message": error_msg}


# Singleton
vaga_service = VagaService()
