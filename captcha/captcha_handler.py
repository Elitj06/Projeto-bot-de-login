"""
Manipulador de captcha — SEAP WebForms.

O CAPTCHA do SEAP é INLINE base64 (não é tag <img>!):
  div#captcha > div { background: url(data:image/png;base64,...) }

Fluxo:
1. Localizar div#captcha > div
2. Extrair base64 do CSS inline (background: url)
3. Decodificar e salvar como PNG
4. Gerar variantes (original, gray3x, bw3x)
5. Enviar para cadeia de providers (CapSolver → OpenAI Vision)
6. Preencher campo input com digitação humana
"""
import asyncio
import base64
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageOps

if TYPE_CHECKING:
    from playwright.async_api import Page
else:  # pragma: no cover - ambiente de teste sem Playwright
    Page = Any

from captcha.exceptions import (
    CaptchaFieldNotFoundError,
    CaptchaImageNotFoundError,
)
from captcha.provider_chain import (
    CaptchaProviderChain,
    is_plausible_captcha_text,
    normalize_captcha_text,
)
from config import captcha_flow_config, path_config
from core.logger import LoggerFactory
from human.human_actions import HumanActions

logger = LoggerFactory.get_logger(__name__)


class CaptchaHandler:
    """
    Resolve CAPTCHA do SEAP-RJ (ASP.NET WebForms).

    O captcha NÃO é uma tag <img> — é um div com background
    base64 inline. Seletores reais:
    - Container: div#captcha
    - Imagem: div#captcha > div
    - Campo input: input dentro de div#captcha ou próximo a ela
    """

    # Seletores reais — DOM dump (15/05/2026)
    CAPTCHA_CONTAINER = "div#captcha"       # w=546 h=149, display=flex, 2 children
    CAPTCHA_IMAGE_DIV = "div#captcha > div" # imagem inline base64
    CAPTCHA_INPUT = "input#TextCaptcha"     # type=text, name=TextCaptcha
    CAPTCHA_NEW_LINK = "a#lnkNewCaptcha"    # "Gerar Nova Imagem"

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
        solver_chain: CaptchaProviderChain,
        human_actions: HumanActions,
    ) -> None:
        self._page = page
        self._solver_chain = solver_chain
        self._human = human_actions
        path_config.ensure_dirs_exist()

    async def solve_and_fill(self) -> str:
        """
        Fluxo completo: extrai base64 → resolve → preenche.

        Returns:
            Texto resolvido pelo provider chain
        """
        logger.info("=" * 50)
        logger.info("RESOLUÇÃO DE CAPTCHA — SEAP WebForms")
        logger.info("=" * 50)

        image_path = await self._extract_base64_captcha()
        candidate_paths = self._build_captcha_variants(image_path)

        await self._human.think()

        solution = await self._solve_with_variants(candidate_paths)
        await self._fill_captcha_field(solution)

        logger.info("CAPTCHA resolvido e preenchido: '%s'", solution)
        return solution

    async def current_captcha_signature(self) -> str:
        """Retorna uma assinatura estável da imagem atual do captcha."""
        image_div = self._page.locator(self.CAPTCHA_IMAGE_DIV).first
        style = await image_div.get_attribute("style") or ""
        base64_data = self._extract_base64_from_style(style)
        if base64_data:
            return hashlib.sha256(base64_data.encode("utf-8")).hexdigest()

        screenshot_bytes = await image_div.screenshot()
        return hashlib.sha256(screenshot_bytes).hexdigest()

    async def _solve_with_variants(self, candidate_paths: list[Path]) -> str:
        """Tenta resolver o captcha em múltiplas variantes da mesma imagem."""
        errors: list[str] = []

        for candidate_path in candidate_paths:
            try:
                logger.info("Tentando resolver captcha com variante: %s", candidate_path.name)
                solution = await self._solver_chain.solve_image_captcha(candidate_path)
                normalized = normalize_captcha_text(solution)
                if self._is_plausible_solution(normalized):
                    logger.info(
                        "Variante %s resolveu captcha como '%s'",
                        candidate_path.name,
                        normalized,
                    )
                    return normalized
                errors.append(f"{candidate_path.name}: solução improvável '{normalized}'")
            except Exception as error:
                logger.warning(
                    "Falha ao resolver variante %s: %s",
                    candidate_path.name,
                    error,
                )
                errors.append(f"{candidate_path.name}: {error}")

        fallback_solution = await self._validate_or_fallback("", candidate_paths[0])
        if fallback_solution:
            return fallback_solution

        raise ValueError("; ".join(errors) or "Nenhuma variante resolveu o captcha")

    async def _validate_or_fallback(self, solution: str, image_path: Path) -> str:
        """Rejeita soluções obviamente inválidas e oferece fallback manual."""
        normalized = normalize_captcha_text(solution)
        if self._is_plausible_solution(normalized):
            return normalized

        logger.warning(
            "Solução de captcha rejeitada como improvável: '%s' (arquivo: %s)",
            normalized,
            image_path.name,
        )

        if not self._manual_fallback_enabled():
            raise ValueError(
                f"Solução improvável do captcha: '{normalized}'"
            )

        if not os.isatty(0):
            raise ValueError(
                "Captcha inválido e fallback manual indisponível em modo não interativo"
            )

        prompt = (
            f"Digite manualmente o CAPTCHA do arquivo {image_path}: "
        )
        manual = await asyncio.to_thread(input, prompt)
        manual = normalize_captcha_text(manual)
        if self._is_plausible_solution(manual):
            logger.info("Captcha informado manualmente")
            return manual

        raise ValueError(f"Captcha manual inválido: '{manual}'")

    def _is_plausible_solution(self, solution: str) -> bool:
        """Valida formato mínimo para evitar lixo óbvio do solver."""
        return is_plausible_captcha_text(solution)

    @staticmethod
    def _manual_fallback_enabled() -> bool:
        """Mantém fallback manual como última rede de segurança."""
        from captcha.capsolver_client import CapSolverClient

        return CapSolverClient.manual_fallback_enabled()

    async def _extract_base64_captcha(self) -> Path:
        """
        Extrai a imagem do CAPTCHA do CSS inline (background base64).

        O SEAP usa: <div style="background: url(data:image/png;base64,...)">
        Não é tag <img>, então não podemos usar screenshot de elemento
        diretamente com boa qualidade. Extraímos o base64 do style.
        """
        container = self._page.locator(self.CAPTCHA_CONTAINER)
        if not await container.is_visible(timeout=5_000):
            raise CaptchaImageNotFoundError(
                "Container div#captcha não encontrado"
            )

        logger.info("Container div#captcha encontrado")

        image_div = self._page.locator(self.CAPTCHA_IMAGE_DIV).first

        try:
            style = await image_div.get_attribute("style") or ""
            logger.debug("Style do captcha div: %s...", style[:100])
        except Exception as error:
            logger.warning("Falha ao ler style: %s", error)
            style = ""

        base64_data = self._extract_base64_from_style(style)

        if not base64_data:
            logger.warning("Base64 não encontrado no style — usando screenshot")
            return await self._screenshot_fallback(container)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = path_config.captchas_dir / f"captcha_{timestamp}.png"

        image_bytes = base64.b64decode(base64_data)
        with open(filepath, "wb") as file_handle:
            file_handle.write(image_bytes)

        logger.info(
            "CAPTCHA extraído do base64 inline: %s (%s bytes)",
            filepath.name,
            len(image_bytes),
        )
        return filepath

    def _build_captcha_variants(self, image_path: Path) -> list[Path]:
        """Gera variantes locais para aumentar a chance de leitura do captcha."""
        variant_map = {"original": image_path}

        with Image.open(image_path) as original_image:
            original_image.load()
            grayscale = ImageOps.grayscale(original_image)
            gray_upscaled = grayscale.resize(
                (grayscale.width * 3, grayscale.height * 3),
                Image.Resampling.LANCZOS,
            )
            gray_path = image_path.with_name(f"{image_path.stem}_gray3x{image_path.suffix}")
            gray_upscaled.save(gray_path)
            variant_map["gray3x"] = gray_path

            bw_upscaled = gray_upscaled.point(
                self._binarize_pixel,
                mode="1",
            )
            bw_path = image_path.with_name(f"{image_path.stem}_bw3x{image_path.suffix}")
            bw_upscaled.convert("L").save(bw_path)
            variant_map["bw3x"] = bw_path

        ordered_paths: list[Path] = []
        for variant_name in captcha_flow_config.variant_order:
            candidate_path = variant_map.get(variant_name)
            if candidate_path and candidate_path not in ordered_paths:
                ordered_paths.append(candidate_path)

        for fallback_path in variant_map.values():
            if fallback_path not in ordered_paths:
                ordered_paths.append(fallback_path)

        logger.info(
            "Variantes geradas para captcha: %s",
            ", ".join(path.name for path in ordered_paths),
        )
        return ordered_paths

    @staticmethod
    def _binarize_pixel(pixel: int) -> int:
        """Converte um pixel em preto/branco usando threshold fixo."""
        return 255 if int(pixel) >= 170 else 0

    @staticmethod
    def _extract_base64_from_style(style: str) -> str:
        """
        Extrai dados base64 de uma string CSS background.

        Formato esperado:
          background: url(data:image/png;base64,iVBOR...) no-repeat...

        Robusto contra whitespace dentro do base64 (quebras de linha,
        espaços) que podem ocorrer em CSS formatado pelo browser.
        """
        pattern = r'data:image/[^;]+;base64,([A-Za-z0-9+/=\s]+)'
        match = re.search(pattern, style)
        if match:
            return re.sub(r'\s+', '', match.group(1))
        return ""

    async def _screenshot_fallback(self, container) -> Path:
        """Fallback: screenshot do div da imagem quando base64 não disponível."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = path_config.captchas_dir / f"captcha_{timestamp}.png"

        try:
            image_div = self._page.locator(self.CAPTCHA_IMAGE_DIV).first
            if await image_div.is_visible(timeout=2000):
                await image_div.screenshot(path=str(filepath))
                logger.info("CAPTCHA via screenshot do image div: %s", filepath.name)
                return filepath
        except Exception as error:
            logger.warning("Screenshot do image div falhou: %s, tentando container", error)

        await container.screenshot(path=str(filepath))
        logger.info("CAPTCHA via screenshot do container: %s", filepath.name)
        return filepath

    async def _refresh_captcha(self) -> None:
        """Clica no botão de refresh do CAPTCHA para gerar nova imagem."""
        for selector in self.CAPTCHA_REFRESH_SELECTORS:
            try:
                element = self._page.locator(selector).first
                if await element.is_visible(timeout=2000):
                    await self._human.click_humanly(selector)
                    logger.info("CAPTCHA refreshed via: %s", selector)
                    await self._human.think()
                    return
            except Exception:
                continue

        logger.warning("Botão de refresh do CAPTCHA não encontrado")

    async def _fill_captcha_field(self, solution: str) -> None:
        """Preenche input#TextCaptcha com a solução."""
        try:
            element = self._page.locator(self.CAPTCHA_INPUT).first
            if await element.is_visible(timeout=3000):
                await element.fill("")
                await self._human.type_humanly(self.CAPTCHA_INPUT, solution, with_typos=False)
                logger.info("Campo TextCaptcha preenchido: '%s'", solution)
                return
        except Exception as error:
            logger.warning("input#TextCaptcha falhou: %s", error)

        raise CaptchaFieldNotFoundError(
            "Campo input#TextCaptcha não encontrado"
        )
