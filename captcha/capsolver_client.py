"""
Cliente assíncrono para o serviço CapSolver.

Encapsula a comunicação com a API do CapSolver:
1. Cria uma tarefa enviando a imagem do captcha
2. Aguarda o resultado (polling assíncrono)
3. Retorna o texto resolvido (geralmente em 2-5 segundos)

Documentação oficial: https://docs.capsolver.com/

Princípios aplicados:
- Single Responsibility: só comunica com CapSolver
- Async/await: não bloqueia outras operações
- Type hints: código autodocumentado
"""
import asyncio
import base64
from pathlib import Path

import aiohttp

from captcha.exceptions import (
    CapSolverApiError,
    CapSolverConnectionError,
    CaptchaTimeoutError,
    InvalidApiKeyError,
)
from config import capsolver_config
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


class CapSolverClient:
    """
    Cliente assíncrono para resolução de captchas via CapSolver.

    Responsabilidade ÚNICA: se comunicar com a API do CapSolver.
    Não captura imagens nem preenche campos — isso é responsabilidade
    de outros módulos (princípio da responsabilidade única).
    """

    def __init__(self) -> None:
        """Inicializa o cliente validando a configuração."""
        try:
            capsolver_config.validate()
        except ValueError as e:
            raise InvalidApiKeyError(str(e))

        self._api_key = capsolver_config.api_key
        self._base_url = capsolver_config.base_url
        logger.info("CapSolverClient inicializado")

    async def solve_image_captcha(self, image_path: Path) -> str:
        """
        Resolve um captcha de imagem.

        Args:
            image_path: Caminho do arquivo de imagem (.png/.jpg)

        Returns:
            Texto resolvido do captcha (ex: "aB7xK9")

        Raises:
            CapSolverConnectionError: Falha de conexão
            CapSolverApiError: Erro retornado pela API
            CaptchaTimeoutError: Resolução demorou demais
        """
        logger.info(f"Resolvendo captcha: {image_path.name}")

        image_base64 = self._encode_image_to_base64(image_path)

        async with aiohttp.ClientSession() as session:
            task_id = await self._create_task(session, image_base64)
            logger.debug(f"Tarefa criada: {task_id}")

            solution = await self._poll_for_result(session, task_id)
            logger.info(f"Captcha resolvido: '{solution}'")

            return solution

    @staticmethod
    def _encode_image_to_base64(image_path: Path) -> str:
        """Converte arquivo de imagem para string base64."""
        if not image_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")

        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    async def _create_task(
        self,
        session: aiohttp.ClientSession,
        image_base64: str,
    ) -> str:
        """Cria uma tarefa de resolução no CapSolver."""
        endpoint = f"{self._base_url}{capsolver_config.create_task_endpoint}"
        payload = {
            "clientKey": self._api_key,
            "task": {
                "type": "ImageToTextTask",
                "body": image_base64,
                "module": "common",
            },
        }

        response_data = await self._send_request(session, endpoint, payload)
        self._check_api_error(response_data)

        task_id = response_data.get("taskId")
        if not task_id:
            raise CapSolverApiError(
                error_id=-1,
                error_code="NO_TASK_ID",
                error_description="API não retornou taskId",
            )

        return task_id

    async def _poll_for_result(
        self,
        session: aiohttp.ClientSession,
        task_id: str,
    ) -> str:
        """Consulta o resultado da tarefa periodicamente."""
        endpoint = f"{self._base_url}{capsolver_config.get_result_endpoint}"
        payload = {"clientKey": self._api_key, "taskId": task_id}

        for attempt in range(capsolver_config.max_polling_attempts):
            await asyncio.sleep(capsolver_config.polling_interval_seconds)

            response_data = await self._send_request(
                session, endpoint, payload
            )
            self._check_api_error(response_data)

            status = response_data.get("status")
            logger.debug(f"Polling tentativa {attempt + 1}: '{status}'")

            if status == "ready":
                solution = response_data.get("solution", {}).get("text", "")
                if not solution:
                    raise CapSolverApiError(
                        error_id=-1,
                        error_code="EMPTY_SOLUTION",
                        error_description="Solução veio vazia",
                    )
                return solution

            if status == "failed":
                raise CapSolverApiError(
                    error_id=response_data.get("errorId", -1),
                    error_code=response_data.get("errorCode", "FAILED"),
                    error_description=response_data.get(
                        "errorDescription", "Tarefa falhou"
                    ),
                )

            # status == "processing", continua aguardando

        raise CaptchaTimeoutError(
            f"Captcha não resolvido após "
            f"{capsolver_config.max_polling_attempts} tentativas"
        )

    @staticmethod
    async def _send_request(
        session: aiohttp.ClientSession,
        endpoint: str,
        payload: dict,
    ) -> dict:
        """Envia requisição POST assíncrona e retorna o JSON."""
        try:
            async with session.post(
                endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            raise CapSolverConnectionError(
                f"Falha ao conectar com CapSolver: {e}"
            )
        except asyncio.TimeoutError:
            raise CapSolverConnectionError(
                "Timeout na conexão com CapSolver (>15s)"
            )

    @staticmethod
    def _check_api_error(response_data: dict) -> None:
        """Verifica se a resposta da API contém erro."""
        if response_data.get("errorId", 0) != 0:
            raise CapSolverApiError(
                error_id=response_data.get("errorId"),
                error_code=response_data.get("errorCode", "UNKNOWN"),
                error_description=response_data.get(
                    "errorDescription", "Erro desconhecido"
                ),
            )
