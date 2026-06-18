"""
Provider multimodal para leitura de captcha via API compatível com OpenAI.

Usa endpoint de chat completions com imagem inline em base64.
Serve como fallback quando o CapSolver erra ou não está configurado.
"""
from __future__ import annotations

import base64
from pathlib import Path

import aiohttp

from captcha.exceptions import (
    CaptchaProviderConfigError,
    CaptchaProviderError,
)
from config import openai_vision_config
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


class OpenAIVisionClient:
    """Lê o captcha via modelo multimodal compatível com OpenAI."""

    name = "openai_vision"

    PROMPT = (
        "Leia o captcha desta imagem e responda somente com os caracteres do captcha, "
        "sem explicacao, sem espacos e sem pontuacao extra."
    )

    def __init__(self) -> None:
        if not openai_vision_config.enabled():
            raise CaptchaProviderConfigError(
                "CAPTCHA_VISION_API_KEY/OPENAI_API_KEY ou CAPTCHA_VISION_MODEL ausentes"
            )
        self._api_key = openai_vision_config.api_key
        self._base_url = openai_vision_config.base_url
        self._model = openai_vision_config.model
        self._timeout_seconds = openai_vision_config.timeout_seconds
        self._max_tokens = openai_vision_config.max_tokens

    async def solve_image_captcha(self, image_path: Path) -> str:
        """Envia o captcha como data URI e retorna o texto extraído."""
        if not image_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

        image_data_uri = self._build_data_uri(image_path)
        payload = {
            "model": self._model,
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_uri},
                        },
                    ],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self._timeout_seconds),
                ) as response:
                    if response.status >= 400:
                        body = await response.text()
                        raise CaptchaProviderError(
                            f"Vision API HTTP {response.status}: {body[:300]}"
                        )
                    data = await response.json()
        except aiohttp.ClientError as error:
            raise CaptchaProviderError(f"Falha na Vision API: {error}") from error

        message = data.get("choices", [{}])[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
            ]
            content = "".join(text_parts)

        content = (content or "").strip()
        if not content:
            raise CaptchaProviderError("Vision API retornou resposta vazia")

        logger.info("Vision API retornou '%s'", content)
        return content

    @staticmethod
    def _build_data_uri(image_path: Path) -> str:
        """Converte PNG/JPEG em data URI para enviar ao endpoint multimodal."""
        mime_type = "image/png"
        if image_path.suffix.lower() in {".jpg", ".jpeg"}:
            mime_type = "image/jpeg"

        encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"
