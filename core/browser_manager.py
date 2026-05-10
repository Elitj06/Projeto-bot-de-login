"""
Gerenciador do navegador com fallback (Camoufox → Playwright Firefox).

Camoufox é um Firefox modificado que aplica anti-detecção no nível C++,
não JavaScript. Isso o torna praticamente invisível para sistemas
de detecção de bot em 2026.

Se Camoufox falhar (timeout, profile error, incompatibilidade),
cai automaticamente para Playwright Firefox nativo com anti-detecção básica.
"""
import asyncio
import os
import tempfile
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from config import camoufox_config
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

# Prefs para desabilitar GPU/shader cache (evita erros em Windows/VMs)
_FIREFOX_GPU_PREFS = {
    "browser.cache.disk.enable": False,
    "gfx.webrender.all": False,
    "layers.gpu-process.enabled": False,
    "media.hardware-video-decoding.enabled": False,
}

# Prefs de anti-detecção básica (fallback)
_STEALTH_PREFS = {
    "dom.webdriver.enabled": False,
    **_FIREFOX_GPU_PREFS,
}

LAUNCH_TIMEOUT_MS = 120_000  # 2 minutos


class StealthBrowserManager:
    """
    Gerencia o ciclo de vida do navegador com fallback automático.

    Estratégia:
    1. Tenta Camoufox (stealth máximo)
    2. Se falhar, cai para Playwright Firefox nativo + anti-detecção

    Use como context manager assíncrono:

        async with StealthBrowserManager() as page:
            await page.goto("https://...")
    """

    def __init__(self) -> None:
        self._playwright = None
        self._camoufox: Optional[object] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._using_camoufox: bool = False

    async def __aenter__(self) -> Page:
        """Inicia o navegador (Camoufox com fallback para Playwright)."""
        self._playwright = await async_playwright().start()

        # Garantir diretório de profile (evita "Can't find profile directory")
        profile_dir = os.path.join(tempfile.gettempdir(), "seap_camoufox_profile")
        os.makedirs(profile_dir, exist_ok=True)

        # Tentativa 1: Camoufox
        try:
            from camoufox.async_api import AsyncCamoufox

            logger.info("Tentando Camoufox (Firefox stealth)...")

            self._camoufox = AsyncCamoufox(
                headless=camoufox_config.headless,
                humanize=(
                    camoufox_config.humanize_max_seconds
                    if camoufox_config.humanize
                    else False
                ),
                os=camoufox_config.os_simulation,
                block_images=camoufox_config.block_images,
                locale=camoufox_config.locale,
                geoip=False,
                i_know_what_im_doing=True,
            )

            self._browser = await asyncio.wait_for(
                self._camoufox.__aenter__(),
                timeout=LAUNCH_TIMEOUT_MS / 1000,
            )
            self._using_camoufox = True
            logger.info("✅ Camoufox iniciado com sucesso")

        except Exception as e:
            logger.warning(f"Camoufox falhou ({type(e).__name__}: {e})")
            logger.info("Fallback: Playwright Firefox nativo + anti-detecção")
            await self._launch_fallback()

        # Cria página
        self._page = await self._browser.new_page()

        # Configura timezone via JavaScript (camuflagem extra)
        await self._page.evaluate(
            "() => { "
            "  Intl.DateTimeFormat = (function(orig) { "
            "    return function() { "
            "      const result = new orig(...arguments); "
            "      return result; "
            "    }; "
            "  })(Intl.DateTimeFormat); "
            "}"
        )

        engine = "Camoufox" if self._using_camoufox else "Playwright Firefox (fallback)"
        logger.info(f"Navegador ativo: {engine}")
        logger.info(f"  - Headless: {camoufox_config.headless}")
        logger.info(f"  - Humanize: {camoufox_config.humanize}")
        logger.info(f"  - OS simulado: {camoufox_config.os_simulation}")
        logger.info(f"  - Locale: {camoufox_config.locale}")

        return self._page

    async def _launch_fallback(self) -> None:
        """Inicia Playwright Firefox nativo com prefs de anti-detecção."""
        # Limpa camoufox se parcialmente inicializado
        if self._camoufox is not None:
            try:
                await self._camoufox.__aexit__(None, None, None)
            except Exception:
                pass
            self._camoufox = None

        self._browser = await self._playwright.firefox.launch(
            headless=camoufox_config.headless,
            timeout=60_000,
            firefox_user_prefs=_STEALTH_PREFS,
        )
        self._using_camoufox = False

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Fecha o navegador ao sair do contexto."""
        try:
            if self._page is not None:
                await self._page.close()

            if self._camoufox is not None:
                await self._camoufox.__aexit__(exc_type, exc_val, exc_tb)
            elif self._browser is not None:
                await self._browser.close()

            logger.info("Navegador fechado")
        except Exception as e:
            logger.warning(f"Erro ao fechar navegador: {e}")
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
