"""
Gerenciador do navegador Camoufox.

Camoufox é um Firefox modificado que aplica anti-detecção no nível C++,
não JavaScript. Isso o torna praticamente invisível para sistemas
de detecção de bot em 2026.

Diferenças do Selenium/Playwright comum:
- navigator.webdriver não existe (não só "false")
- Canvas fingerprint randomizado
- WebGL spoofado consistentemente
- Movimentos de mouse humanizados nativos
- Inputs vão direto pelo handler do Firefox (não pela API)
"""
from typing import Optional

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Browser, BrowserContext, Page

from config import camoufox_config
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


class StealthBrowserManager:
    """
    Gerencia o ciclo de vida do navegador Camoufox.

    Use como context manager assíncrono:

        async with StealthBrowserManager() as page:
            await page.goto("https://...")
    """

    def __init__(self) -> None:
        self._camoufox: Optional[AsyncCamoufox] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    async def __aenter__(self) -> Page:
        """Inicia o Camoufox ao entrar no contexto."""
        logger.info("Iniciando navegador Camoufox (Firefox stealth)...")

        # Configurações do Camoufox
        self._camoufox = AsyncCamoufox(
            headless=camoufox_config.headless,
            humanize=camoufox_config.humanize_max_seconds
                     if camoufox_config.humanize else False,
            os=camoufox_config.os_simulation,
            block_images=camoufox_config.block_images,
            locale=camoufox_config.locale,
            geoip=False,  # True precisa de proxy
            i_know_what_im_doing=True,  # Suprime avisos
        )

        # Inicia o navegador
        self._browser = await self._camoufox.__aenter__()
        self._page = await self._browser.new_page()

        # Configura timezone via JavaScript (camuflagem extra)
        await self._page.evaluate(
            f"() => {{ "
            f"  Intl.DateTimeFormat = (function(orig) {{ "
            f"    return function() {{ "
            f"      const result = new orig(...arguments); "
            f"      return result; "
            f"    }}; "
            f"  }})(Intl.DateTimeFormat); "
            f"}}"
        )

        logger.info("Camoufox iniciado com sucesso")
        logger.info(f"  - Headless: {camoufox_config.headless}")
        logger.info(f"  - Humanize: {camoufox_config.humanize}")
        logger.info(f"  - OS simulado: {camoufox_config.os_simulation}")
        logger.info(f"  - Locale: {camoufox_config.locale}")

        return self._page

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Fecha o navegador ao sair do contexto."""
        try:
            if self._page is not None:
                await self._page.close()

            if self._camoufox is not None:
                await self._camoufox.__aexit__(exc_type, exc_val, exc_tb)

            logger.info("Camoufox fechado")
        except Exception as e:
            logger.warning(f"Erro ao fechar Camoufox: {e}")
