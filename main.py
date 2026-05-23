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


def load_filter_params() -> tuple:
    """Carrega parâmetros de filtro do .env (página 2)."""
    return (
        os.getenv("SEAP_FILTER_UNIT", ""),
        os.getenv("SEAP_FILTER_DATE", ""),
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
        print(f"  Captcha 1:         {result.captcha_solution}")
    if result.filter_captcha_solution:
        print(f"  Captcha 2 (filtro): {result.filter_captcha_solution}")
    if result.filter_submitted:
        print(f"  Filtro submetido:  SIM")
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

    filter_unit, filter_date = load_filter_params()
    if filter_unit or filter_date:
        logger.info(f"Filtro: unidade={filter_unit or '(vazio)'}, data={filter_date or '(vazio)'}")

    start_time = time.time()
    result = None

    try:
        async with StealthBrowserManager() as page:
            bot = SeapLoginBot(page)
            result = await bot.execute_login(
                credentials,
                filter_unit=filter_unit,
                filter_date=filter_date,
            )

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
