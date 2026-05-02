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
from config import path_config
from core.logger import LoggerFactory
from human.human_actions import HumanActions

logger = LoggerFactory.get_logger(__name__)


class CaptchaHandler:
    """
    Coordena a resolução completa de captcha.

    Usa CapSolverClient para a parte da resolução (IA),
    e HumanActions para preencher o campo de forma humana.
    """

    # Seletores em ordem de prioridade (mais específico → mais genérico)
    CAPTCHA_IMAGE_SELECTORS = [
        "img[src*='captcha']",
        "img[src*='Captcha']",
        "img[src*='CAPTCHA']",
        "img[id*='captcha']",
        "img[class*='captcha']",
        "img[alt*='captcha']",
        "img[id*='Captcha']",
        "img[class*='Captcha']",
    ]

    CAPTCHA_INPUT_SELECTORS = [
        "input[name*='captcha']",
        "input[id*='captcha']",
        "input[name*='Captcha']",
        "input[id*='Captcha']",
        "input[placeholder*='captcha']",
        "input[placeholder*='código']",
        "input[placeholder*='verificação']",
        "input[placeholder*='Captcha']",
    ]

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
        Executa o fluxo completo: captura, resolve e preenche o captcha.

        Returns:
            Texto que foi preenchido no campo

        Raises:
            CaptchaImageNotFoundError: Imagem não localizada
            CaptchaFieldNotFoundError: Campo de input não localizado
            CapSolverApiError: Falha na resolução
        """
        logger.info("=" * 60)
        logger.info("INICIANDO RESOLUÇÃO DE CAPTCHA")
        logger.info("=" * 60)

        # 1. Encontra a imagem do captcha
        captcha_element = await self._locate_captcha_image()

        # 2. Captura screenshot da imagem
        image_path = await self._save_captcha_image(captcha_element)

        # 3. Pausa "pensando" como um humano olharia
        await self._human.think()

        # 4. Envia para CapSolver (resolve em 2-5 segundos)
        solution = await self._capsolver.solve_image_captcha(image_path)

        # 5. Preenche o campo com digitação humana
        await self._fill_captcha_field(solution)

        logger.info(f"✓ Captcha resolvido e preenchido: '{solution}'")
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

        raise CaptchaImageNotFoundError(
            "Imagem do captcha não encontrada na página"
        )

    async def _save_captcha_image(self, element: ElementHandle) -> Path:
        """Captura screenshot do elemento e salva em disco."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"captcha_{timestamp}.png"
        filepath = path_config.captchas_dir / filename

        await element.screenshot(path=str(filepath))
        logger.info(f"Imagem do captcha salva: {filepath.name}")

        return filepath

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
