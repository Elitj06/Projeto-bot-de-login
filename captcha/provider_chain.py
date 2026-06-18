"""
Orquestra a cadeia de providers de captcha.

Fluxo:
1. Tenta os providers configurados na ordem do .env
2. Normaliza a resposta de cada provider
3. Aceita a primeira solução plausível
4. Se todos falharem, propaga o último erro relevante
"""
from __future__ import annotations

import re
from typing import Iterable, Protocol

from captcha.capsolver_client import CapSolverClient
from captcha.exceptions import (
    CaptchaProviderConfigError,
    CaptchaProviderError,
)
from captcha.openai_vision_client import OpenAIVisionClient
from config import captcha_provider_config
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

CAPTCHA_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9]{4,6}$")


class CaptchaProvider(Protocol):
    """Contrato mínimo para providers de captcha."""

    name: str

    async def solve_image_captcha(self, image_path) -> str:
        """Retorna a leitura bruta do captcha."""


def normalize_captcha_text(value: str) -> str:
    """Remove ruído textual comum sem alterar os caracteres do captcha."""
    normalized = re.sub(r"\s+", "", value or "")
    normalized = normalized.replace("'", "").replace('"', "")
    return normalized.strip()


def is_plausible_captcha_text(value: str) -> bool:
    """Valida o formato mínimo esperado do captcha do SEAP."""
    normalized = normalize_captcha_text(value)
    length = len(normalized)
    if not (captcha_provider_config.expected_min_chars <= length <= captcha_provider_config.expected_max_chars):
        return False
    return bool(CAPTCHA_TEXT_PATTERN.fullmatch(normalized))


class CaptchaProviderChain:
    """Executa fallback entre múltiplos providers."""

    def __init__(self, providers: Iterable[CaptchaProvider] | None = None) -> None:
        self._providers = list(providers) if providers is not None else self._build_default_providers()

    @staticmethod
    def _build_default_providers() -> list[CaptchaProvider]:
        """Monta a cadeia padrão a partir da configuração."""
        providers: list[CaptchaProvider] = []
        for provider_name in captcha_provider_config.providers:
            try:
                if provider_name == "capsolver":
                    providers.append(CapSolverClient())
                elif provider_name == "openai_vision":
                    providers.append(OpenAIVisionClient())
                else:
                    logger.warning("Provider de captcha desconhecido ignorado: %s", provider_name)
            except CaptchaProviderConfigError as error:
                logger.warning(
                    "Provider de captcha %s ignorado por configuração incompleta: %s",
                    provider_name,
                    error,
                )
        return providers

    async def solve_image_captcha(self, image_path) -> str:
        """Retorna a primeira solução plausível dentre os providers disponíveis."""
        if not self._providers:
            raise CaptchaProviderConfigError(
                "Nenhum provider de captcha configurado. "
                "Defina CAPTCHA_PROVIDERS no .env."
            )

        last_error: Exception | None = None
        rejected_solutions: list[str] = []

        for provider in self._providers:
            try:
                raw_solution = await provider.solve_image_captcha(image_path)
                solution = normalize_captcha_text(raw_solution)
                logger.info("Provider %s retornou '%s'", provider.name, solution)
                if is_plausible_captcha_text(solution):
                    return solution
                rejected_solutions.append(f"{provider.name}='{solution}'")
                logger.warning(
                    "Provider %s retornou solução improvável: '%s'",
                    provider.name,
                    solution,
                )
            except CaptchaProviderConfigError as error:
                last_error = error
                logger.warning("Provider %s indisponível: %s", provider.name, error)
            except Exception as error:
                last_error = error
                logger.warning("Provider %s falhou: %s", provider.name, error)

        if rejected_solutions:
            raise CaptchaProviderError(
                "Todos os providers retornaram soluções improváveis: "
                + ", ".join(rejected_solutions)
            )
        if last_error:
            raise last_error
        raise CaptchaProviderError("Nenhum provider conseguiu resolver o captcha")
