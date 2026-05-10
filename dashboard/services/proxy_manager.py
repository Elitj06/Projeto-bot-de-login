"""
Gerenciador de Proxies — Rotação e Testes.

Estratégias de rotação:
1. Round-robin: cada login pega o próximo proxy da fila
2. Least-recently-used: pega o proxy que foi usado há mais tempo
3. Por país: prioriza proxies brasileiros

Para contornar o limite de 1 login/IP do SEAP:
- Cada usuário recebe um proxy diferente → IP diferente
- Se não há proxies suficientes, faz fila com delay entre logins
- Suporta proxies residenciais rotativos (1 request = 1 IP)
"""
import asyncio
import time
import aiohttp
from datetime import datetime, timezone
from typing import Optional

from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


class ProxyManager:
    """Gerencia pool de proxies com rotação inteligente."""

    # URL de teste para verificar conectividade do proxy
    TEST_URL = "https://httpbin.org/ip"
    TEST_TIMEOUT = 15  # segundos

    async def test_proxy(self, proxy_url: str) -> dict:
        """
        Testa se um proxy está funcionando.

        Returns:
            {"success": bool, "ip": str, "latency_ms": int, "error": str|None, "timestamp": str}
        """
        start = time.time()
        now = datetime.now(timezone.utc).isoformat()

        try:
            connector = aiohttp.TCPConnector(limit=1)
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=self.TEST_TIMEOUT)) as session:
                async with session.get(
                    self.TEST_URL,
                    proxy=proxy_url,
                    ssl=False,
                ) as resp:
                    latency = int((time.time() - start) * 1000)
                    if resp.status == 200:
                        data = await resp.json()
                        exit_ip = data.get("origin", "unknown")
                        logger.info(f"Proxy OK: {proxy_url[:30]}... → IP {exit_ip} ({latency}ms)")
                        return {
                            "success": True,
                            "ip": exit_ip,
                            "latency_ms": latency,
                            "error": None,
                            "timestamp": now,
                        }
                    else:
                        return {
                            "success": False,
                            "ip": None,
                            "latency_ms": latency,
                            "error": f"HTTP {resp.status}",
                            "timestamp": now,
                        }
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {
                "success": False,
                "ip": None,
                "latency_ms": latency,
                "error": str(e)[:100],
                "timestamp": now,
            }

    async def test_all(self, proxy_urls: list[str], concurrency: int = 5) -> list[dict]:
        """Testa múltiplos proxies em paralelo."""
        semaphore = asyncio.Semaphore(concurrency)

        async def _limited_test(url):
            async with semaphore:
                return await self.test_proxy(url)

        tasks = [_limited_test(url) for url in proxy_urls]
        return await asyncio.gather(*tasks)

    @staticmethod
    def format_proxy_url(raw: str) -> str:
        """
        Normaliza URL de proxy para formato Playwright.

        Aceita:
          - socks5://user:pass@host:port
          - host:port:user:pass
          - http://user:pass@host:port
        """
        raw = raw.strip()
        if raw.startswith(("socks5://", "socks4://", "http://", "https://")):
            return raw

        parts = raw.split(":")
        if len(parts) == 4:
            return f"socks5://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        elif len(parts) == 2:
            return f"socks5://{parts[0]}:{parts[1]}"
        return raw


class LoginScheduler:
    """
    Escalonador de logins simultâneos.

    Resolve o problema de "1 login por IP" do SEAP:

    Estratégia:
    1. Se há N proxies disponíveis → N logins em paralelo (1 proxy por login)
    2. Se há mais usuários que proxies → lotes de N, com delay entre lotes
    3. Cada lote usa todos os proxies disponíveis simultaneamente
    4. Delay entre lotes = 30-60s (configurável) para evitar detecção

    Exemplo com 5 usuários e 2 proxies:
      Lote 1: User1 (Proxy1) || User2 (Proxy2)     → paralelo
      [wait 45s]
      Lote 2: User3 (Proxy1) || User4 (Proxy2)     → paralelo
      [wait 45s]
      Lote 3: User5 (Proxy1)                        → sozinho
    """

    def __init__(self, batch_delay_seconds: int = 45, stagger_seconds: float = 2.0):
        """
        Args:
            batch_delay_seconds: Delay entre lotes de login
            stagger_seconds: Delay entre logins dentro do mesmo lote (evita burst)
        """
        self.batch_delay = batch_delay_seconds
        self.stagger = stagger_seconds

    def calculate_batches(self, users: list[dict], proxies: list[str]) -> list[list[dict]]:
        """
        Divide usuários em lotes baseado no número de proxies.

        Returns:
            Lista de lotes, cada lote = lista de users com proxy atribuído
        """
        if not proxies:
            # Sem proxies — login sequencial com delay grande
            return [[u] for u in users]

        batches = []
        proxy_count = len(proxies)

        for i in range(0, len(users), proxy_count):
            batch = []
            for j in range(proxy_count):
                if i + j < len(users):
                    user = users[i + j].copy()
                    user["_assigned_proxy"] = proxies[j]
                    batch.append(user)
            batches.append(batch)

        return batches

    def get_execution_plan(self, users: list[dict], proxies: list[str]) -> dict:
        """
        Retorna plano de execução completo para preview no dashboard.
        """
        batches = self.calculate_batches(users, proxies)
        total_time_estimate = 0

        plan_batches = []
        for i, batch in enumerate(batches):
            batch_info = {
                "batch_number": i + 1,
                "users": [
                    {
                        "username": u.get("username", "?"),
                        "proxy": u.get("_assigned_proxy", "Direto (sem proxy)"),
                    }
                    for u in batch
                ],
                "parallel_count": len(batch),
                "estimated_duration": 30 * len(batch),  # ~30s por login
            }
            plan_batches.append(batch_info)
            total_time_estimate += 30  # login time
            if i < len(batches) - 1:
                total_time_estimate += self.batch_delay

        return {
            "total_users": len(users),
            "total_proxies": len(proxies),
            "total_batches": len(batches),
            "estimated_total_seconds": total_time_estimate,
            "batch_delay_seconds": self.batch_delay,
            "stagger_seconds": self.stagger,
            "batches": plan_batches,
        }
