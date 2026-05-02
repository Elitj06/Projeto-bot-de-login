"""
Ponto de entrada do Bot SEAP v2 (Camoufox + Comportamento Humano).

Para executar:
    python main.py

Antes de rodar pela primeira vez:
    1. Instalar Python 3.10+
    2. pip install -r requirements.txt
    3. python -m camoufox fetch (baixa Firefox stealth, ~150MB - só primeira vez)
    4. Criar arquivo .env com suas credenciais (veja .env.example)
"""
import asyncio
import os
import sys
import time

from dotenv import load_dotenv

from automation.login_bot import LoginCredentials, SeapLoginBot
from core.browser_manager import StealthBrowserManager
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


def load_credentials() -> LoginCredentials:
    """Carrega credenciais do arquivo .env."""
    load_dotenv()
    return LoginCredentials(
        username=os.getenv("SEAP_USERNAME", ""),
        password=os.getenv("SEAP_PASSWORD", ""),
    )


def print_banner() -> None:
    """Exibe banner de inicialização."""
    print()
    print("=" * 70)
    print("  BOT DE LOGIN SEAP-RJ  |  Versão 2.0")
    print("  Engine: Camoufox (stealth máximo) + CapSolver")
    print("=" * 70)
    print()


def print_result(result, elapsed_seconds: float) -> None:
    """Exibe o resultado final formatado."""
    print()
    print("=" * 70)
    print("  RESULTADO")
    print("=" * 70)
    status = "SUCESSO ✓" if result.success else "FALHA ✗"
    print(f"  Status:           {status}")
    print(f"  Mensagem:         {result.message}")
    if result.captcha_solution:
        print(f"  Captcha resolvido: {result.captcha_solution}")
    print(f"  Tempo total:      {elapsed_seconds:.2f}s")
    print("=" * 70)
    print()


async def run_bot() -> int:
    """
    Função principal assíncrona.

    Returns:
        0 se sucesso, 1 se falha (padrão Unix)
    """
    print_banner()

    credentials = load_credentials()
    if not credentials.is_valid():
        logger.error(
            "Credenciais não configuradas. "
            "Edite o arquivo .env (veja .env.example)."
        )
        return 1

    start_time = time.time()
    result = None

    try:
        async with StealthBrowserManager() as page:
            bot = SeapLoginBot(page)
            result = await bot.execute_login(credentials)

            # Mantém navegador aberto por alguns segundos para visualização
            if result.success:
                logger.info("Login concluído. Aguardando 10s antes de fechar.")
                await asyncio.sleep(10)

    except Exception as e:
        logger.exception("Erro fatal na execução")
        elapsed = time.time() - start_time
        print(f"\n[ERRO FATAL] {e} (após {elapsed:.2f}s)")
        return 1

    elapsed = time.time() - start_time
    print_result(result, elapsed)

    return 0 if result and result.success else 1


def main() -> int:
    """Wrapper síncrono para executar a função assíncrona."""
    try:
        return asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n\nExecução interrompida pelo usuário (Ctrl+C)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
