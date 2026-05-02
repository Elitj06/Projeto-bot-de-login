"""
Simulador de comportamento humano.

Cada ação tem variabilidade realista para imitar uma pessoa real:
- Digitação com velocidades variadas (não constante)
- Pausas aleatórias entre ações ("pensar")
- Movimentos de mouse antes de clicar
- Pausas de leitura ao chegar em uma página

Princípio: Anti-bot baseado em comportamento mede TIMING.
Eliminando padrões mecânicos, eliminamos a detecção comportamental.
"""
import asyncio
import random
import string
from typing import Optional

from playwright.async_api import Page, ElementHandle

from config import human_behavior_config as cfg
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


class HumanActions:
    """
    Conjunto de ações que simulam comportamento humano realista.

    Use ao invés de page.fill() ou page.click() diretamente,
    para evitar padrões mecânicos detectáveis.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    # ------------------------------------------------------------------
    # PAUSAS HUMANAS
    # ------------------------------------------------------------------

    async def think(self) -> None:
        """
        Pausa de 'pensamento' antes de uma ação.
        Simula o tempo que humanos levam para ler/processar/decidir.
        """
        delay = random.uniform(cfg.think_min_seconds, cfg.think_max_seconds)
        logger.debug(f"Pausando {delay:.2f}s para 'pensar'")
        await asyncio.sleep(delay)

    async def micro_pause(self) -> None:
        """Pausa muito curta entre ações próximas (200-500ms)."""
        await asyncio.sleep(random.uniform(0.2, 0.5))

    async def reading_pause(self) -> None:
        """
        Pausa longa simulando leitura de uma página nova.
        Usar ao chegar em uma URL pela primeira vez.
        """
        delay = random.uniform(2.0, 4.5)
        logger.debug(f"Pausando {delay:.2f}s para 'ler' a página")
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # DIGITAÇÃO HUMANA
    # ------------------------------------------------------------------

    async def type_humanly(
        self,
        selector: str,
        text: str,
        with_typos: bool = True,
    ) -> None:
        """
        Digita texto caractere por caractere com velocidade variável.

        Args:
            selector: Seletor CSS do campo
            text: Texto a digitar
            with_typos: Se deve simular erros e correções (~5% chance)
        """
        # Foca o campo de forma natural (clique + pequena pausa)
        await self._click_naturally(selector)
        await self.micro_pause()

        # Limpa o campo se já tiver conteúdo
        await self._page.locator(selector).clear()
        await self.micro_pause()

        for char in text:
            # Simula erro de digitação ocasional
            if with_typos and random.random() < cfg.typo_probability:
                wrong_char = self._random_typo(char)
                await self._type_char(wrong_char)
                # Percebe o erro e corrige após 200-500ms
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await self._page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.1, 0.3))

            await self._type_char(char)

        # Pausa após terminar de digitar (humano "respira")
        delay = random.uniform(
            cfg.field_complete_min_seconds,
            cfg.field_complete_max_seconds,
        )
        await asyncio.sleep(delay)
        logger.debug(f"Digitou {len(text)} caracteres no campo {selector}")

    async def _type_char(self, char: str) -> None:
        """Digita um único caractere com delay variável."""
        await self._page.keyboard.type(char)
        delay_ms = random.randint(
            cfg.typing_min_delay_ms,
            cfg.typing_max_delay_ms,
        )
        await asyncio.sleep(delay_ms / 1000)

    @staticmethod
    def _random_typo(correct_char: str) -> str:
        """Retorna um caractere 'próximo' no teclado para simular typo."""
        # Mapa simplificado de proximidade no teclado QWERTY
        nearby = {
            "a": "s", "s": "a", "d": "f", "f": "d", "g": "h", "h": "g",
            "j": "k", "k": "j", "l": "k", "q": "w", "w": "e", "e": "r",
            "r": "t", "t": "y", "y": "u", "u": "i", "i": "o", "o": "p",
            "z": "x", "x": "c", "c": "v", "v": "b", "b": "n", "n": "m",
        }
        lower = correct_char.lower()
        if lower in nearby:
            return nearby[lower]
        return random.choice(string.ascii_lowercase)

    # ------------------------------------------------------------------
    # CLIQUES HUMANOS
    # ------------------------------------------------------------------

    async def click_humanly(self, selector: str) -> None:
        """
        Clica em um elemento com movimento de mouse realista.

        Em vez de teleportar o cursor, move suavemente até o alvo.
        """
        await self._click_naturally(selector)
        logger.debug(f"Clicou em {selector} de forma humana")

    async def _click_naturally(self, selector: str) -> None:
        """Clique com movimento de mouse anterior."""
        element = self._page.locator(selector).first

        # Pega a posição do elemento
        box = await element.bounding_box()
        if box is None:
            # Fallback: clique direto se não conseguir posição
            await element.click()
            return

        # Posição aleatória DENTRO do elemento (não centro exato)
        target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

        # Move o mouse em vários "passos" para simular movimento humano
        steps = random.randint(15, 30)
        await self._page.mouse.move(target_x, target_y, steps=steps)

        # Pequena pausa antes de clicar (humano "mira")
        await asyncio.sleep(random.uniform(0.05, 0.2))

        await self._page.mouse.click(target_x, target_y)

    # ------------------------------------------------------------------
    # SCROLL HUMANO (caso precise)
    # ------------------------------------------------------------------

    async def scroll_humanly(self, pixels: int = 300) -> None:
        """
        Faz scroll de forma humana (vários pequenos scrolls, não um grande).
        """
        chunks = random.randint(3, 6)
        chunk_size = pixels // chunks

        for _ in range(chunks):
            variation = random.randint(-30, 30)
            await self._page.mouse.wheel(0, chunk_size + variation)
            await asyncio.sleep(random.uniform(0.1, 0.3))

        logger.debug(f"Scroll humanizado de {pixels}px")
