"""
Manipulador de captcha.

Orquestra o fluxo completo:
1. Localizar imagem do captcha na página
2. Capturar a imagem
3. Enviar para CapSolver (assíncrono)
4. Preencher o campo com comportamento humano

Este módulo é o "maestro" que coordena os outros componentes.
"""
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, ElementHandle

from captcha.capsolver_client import CapSolverClient
from captcha.exceptions import (
    CaptchaFieldNotFoundError,
    CaptchaImageNotFoundError,
)
from config import path_config, seap_config
from core.logger import LoggerFactory
from human.human_actions import HumanActions

logger = LoggerFactory.get_logger(__name__)


class CaptchaHandler:
    """
    Coordena a resolução completa de captcha.

    Usa CapSolverClient para a parte da resolução (IA),
    e HumanActions para preencher o campo de forma humana.
    """

    # Seletores específicos do SEAP-RJ (confirmados via inspeção DOM)
    CAPTCHA_IMAGE_SELECTORS = [
        "div#captcha > div",         # SEAP: div com CSS background base64
        "div#captcha",               # SEAP: container do CAPTCHA
        "img[src*='captcha']",
        "img[src*='Captcha']",
        "img[id*='captcha']",
        "img[class*='captcha']",
    ]

    CAPTCHA_INPUT_SELECTORS = [
        "input#TextCaptcha",          # SEAP: campo de input do CAPTCHA
        "input[name*='captcha']",
        "input[id*='captcha']",
        "input[placeholder*='captcha']",
        "input[placeholder*='código']",
        "input[placeholder*='verificação']",
    ]

    CAPTCHA_REFRESH_SELECTORS = [
        "a#lnkNewCaptcha",            # SEAP: botão refresh do CAPTCHA
        "a[href*='captcha']",
        "img[src*='refresh']",
        "a:has-text('Atualizar')",
    ]

    MAX_SOLVE_ATTEMPTS = 3

    def __init__(
        self,
        page: Page,
        capsolver_client: CapSolverClient,
        human_actions: HumanActions,
    ) -> None:
        """
        Args:
            page: Página Playwright/Camoufox
            capsolver_client: Cliente CapSolver (Dependency Injection)
            human_actions: Simulador de ações humanas (DI)
        """
        self._page = page
        self._capsolver = capsolver_client
        self._human = human_actions
        path_config.ensure_dirs_exist()

    async def solve_and_fill(self) -> str:
        """
        Executa o fluxo completo com retry: captura, resolve e preenche o captcha.

        Tenta até MAX_SOLVE_ATTEMPTS vezes, refreshando o CAPTCHA entre tentativas.

        Returns:
            Texto que foi preenchido no campo

        Raises:
            CaptchaImageNotFoundError: Imagem não localizada após todas tentativas
            CaptchaFieldNotFoundError: Campo de input não localizado
        """
        logger.info("=" * 60)
        logger.info("INICIANDO RESOLUÇÃO DE CAPTCHA")
        logger.info("=" * 60)

        last_error = None

        for attempt in range(1, self.MAX_SOLVE_ATTEMPTS + 1):
            logger.info(f"Tentativa {attempt}/{self.MAX_SOLVE_ATTEMPTS}")

            try:
                solution = await self._solve_once()
                logger.info(f"✓ Captcha resolvido e preenchido: '{solution}' (tentativa {attempt})")
                return solution
            except (CaptchaImageNotFoundError, CaptchaFieldNotFoundError) as e:
                last_error = e
                logger.error(f"Tentativa {attempt} falhou: {e}")
            except Exception as e:
                last_error = e
                logger.error(f"Tentativa {attempt} — erro inesperado: {e}")

            # Refresh do CAPTCHA antes da próxima tentativa (se houver)
            if attempt < self.MAX_SOLVE_ATTEMPTS:
                await self._refresh_captcha()

        raise CaptchaImageNotFoundError(
            f"Captcha não resolvido após {self.MAX_SOLVE_ATTEMPTS} tentativas. "
            f"Último erro: {last_error}"
        )

    async def _solve_once(self) -> str:
        """Executa uma única tentativa de resolução: captura → resolve → preenche."""
        # 1. Encontra a imagem do captcha
        captcha_element = await self._locate_captcha_image()

        # 2. Captura screenshot do elemento (funciona com div e img)
        image_path = await self._save_captcha_image(captcha_element)

        # 3. Pausa "pensando" como um humano olharia
        await self._human.think()

        # 4. Envia para CapSolver (passa URL do site para melhor acurácia)
        page_url = self._page.url
        solution = await self._capsolver.solve_image_captcha(
            image_path, website_url=page_url
        )

        # 5. Preenche o campo com digitação humana
        await self._fill_captcha_field(solution)

        return solution

    async def _locate_captcha_image(self) -> ElementHandle:
        """Localiza a imagem do captcha usando vários seletores."""
        for selector in self.CAPTCHA_IMAGE_SELECTORS:
            try:
                elements = await self._page.query_selector_all(selector)
                for element in elements:
                    is_visible = await element.is_visible()
                    if is_visible:
                        logger.info(f"Captcha localizado: {selector}")
                        return element
            except Exception as e:
                logger.debug(f"Seletor '{selector}' falhou: {e}")

        # Diagnóstico: lista o que existe na página para debug
        await self._log_page_diagnostic()
        raise CaptchaImageNotFoundError(
            "Imagem do captcha não encontrada na página"
        )

    async def _log_page_diagnostic(self) -> None:
        """Loga elementos da página para diagnóstico quando CAPTCHA não é encontrado."""
        try:
            all_divs = await self._page.query_selector_all("div[id]")
            for div in all_divs:
                div_id = await div.get_attribute("id")
                if div_id and "captcha" in div_id.lower():
                    logger.debug(f"DIAG: Encontrado div#{div_id} (captcha-related)")

            all_inputs = await self._page.query_selector_all("input")
            for inp in all_inputs:
                inp_id = await inp.get_attribute("id") or ""
                inp_name = await inp.get_attribute("name") or ""
                inp_type = await inp.get_attribute("type") or ""
                if any(k in (inp_id + inp_name).lower() for k in ["captcha", "text"]):
                    logger.debug(f"DIAG: input#{inp_id} name={inp_name} type={inp_type}")
        except Exception as e:
            logger.debug(f"DIAG: Falha no diagnóstico: {e}")

    async def _save_captcha_image(self, element: ElementHandle) -> Path:
        """Captura screenshot do elemento e salva em disco."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"captcha_{timestamp}.png"
        filepath = path_config.captchas_dir / filename

        await element.screenshot(path=str(filepath))
        logger.info(f"Imagem do captcha salva: {filepath.name}")

        return filepath

    async def _refresh_captcha(self) -> None:
        """Clica no botão de refresh do CAPTCHA para gerar nova imagem."""
        for selector in self.CAPTCHA_REFRESH_SELECTORS:
            try:
                element = self._page.locator(selector).first
                if await element.is_visible(timeout=2000):
                    await self._human.click_humanly(selector)
                    logger.info(f"CAPTCHA refreshed via: {selector}")
                    # Aguarda nova imagem carregar
                    await self._human.think()
                    return
            except Exception:
                continue

        logger.warning("Botão de refresh do CAPTCHA não encontrado")

    async def _fill_captcha_field(self, solution: str) -> None:
        """Preenche o campo de input do captcha com digitação humana."""
        for selector in self.CAPTCHA_INPUT_SELECTORS:
            try:
                elements = await self._page.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        # Usa digitação humana, sem typos no captcha
                        # (não queremos errar a resposta!)
                        await self._human.type_humanly(
                            selector, solution, with_typos=False
                        )
                        logger.info(
                            f"Campo do captcha preenchido (seletor: {selector})"
                        )
                        return
            except Exception as e:
                logger.debug(f"Seletor '{selector}' falhou: {e}")

        raise CaptchaFieldNotFoundError(
            "Campo de input do captcha não encontrado"
        )
