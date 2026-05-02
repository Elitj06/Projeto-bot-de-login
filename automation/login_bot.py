"""
Bot de login SEAP-RJ.

Combina os componentes em um fluxo de alto nível:
1. Navegar para o site (com pausa "lendo" a página)
2. Preencher credenciais (digitação humana)
3. Resolver captcha (CapSolver + comportamento humano)
4. Submeter formulário (clique humano)

Cada etapa é um método claro e auditável, com pausas humanas
naturais entre elas.
"""
from dataclasses import dataclass

from playwright.async_api import Page

from captcha.captcha_handler import CaptchaHandler
from captcha.capsolver_client import CapSolverClient
from config import seap_config
from core.logger import LoggerFactory
from human.human_actions import HumanActions

logger = LoggerFactory.get_logger(__name__)


@dataclass
class LoginCredentials:
    """Credenciais de acesso ao SEAP."""
    username: str
    password: str

    def is_valid(self) -> bool:
        return bool(self.username) and bool(self.password)


@dataclass
class LoginResult:
    """Resultado de uma tentativa de login."""
    success: bool
    message: str
    captcha_solution: str = ""
    elapsed_seconds: float = 0.0


class SeapLoginBot:
    """
    Bot de login do SEAP-RJ com Camoufox + comportamento humano.

    Recebe uma página Camoufox/Playwright já inicializada e coordena
    os componentes para realizar o login de forma indistinguível
    de uma pessoa real.
    """

    USERNAME_SELECTORS = [
        "input[name='username']",
        "input[name='login']",
        "input[name='user']",
        "input[name='email']",
        "input[id='username']",
        "input[id='login']",
        "input[id='user']",
        "input[type='email']",
    ]

    PASSWORD_SELECTORS = [
        "input[name='password']",
        "input[name='senha']",
        "input[id='password']",
        "input[id='senha']",
        "input[type='password']",
    ]

    SUBMIT_SELECTORS = [
        "button[type='submit']",
        "input[type='submit']",
        "button.btn-primary",
        "button.login-btn",
        "button:has-text('Entrar')",
        "button:has-text('Login')",
        "button:has-text('Acessar')",
    ]

    def __init__(self, page: Page) -> None:
        """
        Args:
            page: Página Camoufox já inicializada
        """
        self._page = page
        self._human = HumanActions(page)
        self._captcha_handler = CaptchaHandler(
            page=page,
            capsolver_client=CapSolverClient(),
            human_actions=self._human,
        )

    async def execute_login(
        self, credentials: LoginCredentials
    ) -> LoginResult:
        """
        Executa o fluxo completo de login.

        Args:
            credentials: Usuário e senha

        Returns:
            LoginResult indicando sucesso ou falha
        """
        if not credentials.is_valid():
            return LoginResult(
                success=False,
                message="Credenciais inválidas (usuário ou senha vazios)",
            )

        try:
            await self._navigate_to_login_page()
            await self._fill_credentials(credentials)
            captcha_solution = await self._solve_captcha()
            await self._submit_form()

            return LoginResult(
                success=True,
                message="Login executado com sucesso",
                captcha_solution=captcha_solution,
            )

        except Exception as e:
            logger.exception("Erro durante o login")
            return LoginResult(
                success=False,
                message=f"Erro: {type(e).__name__} - {e}",
            )

    async def _navigate_to_login_page(self) -> None:
        """Navega para a página de login com pausa humana."""
        url = f"{seap_config.base_url}{seap_config.login_path}"
        logger.info(f"Navegando para: {url}")

        await self._page.goto(
            url,
            wait_until="networkidle",
            timeout=seap_config.page_load_timeout_ms,
        )

        # Humano "lê" a página antes de agir
        await self._human.reading_pause()

    async def _fill_credentials(
        self, credentials: LoginCredentials
    ) -> None:
        """Preenche usuário e senha com digitação humana."""
        # Encontra e preenche campo de usuário
        username_selector = await self._find_visible_selector(
            self.USERNAME_SELECTORS, "Usuário"
        )
        await self._human.type_humanly(
            username_selector, credentials.username, with_typos=True
        )

        # Pausa entre campos (humano não digita os dois sem pausa)
        await self._human.think()

        # Encontra e preenche campo de senha (sem typos para não errar!)
        password_selector = await self._find_visible_selector(
            self.PASSWORD_SELECTORS, "Senha"
        )
        await self._human.type_humanly(
            password_selector, credentials.password, with_typos=False
        )

        await self._human.micro_pause()

    async def _solve_captcha(self) -> str:
        """Resolve o captcha usando CapSolver + comportamento humano."""
        return await self._captcha_handler.solve_and_fill()

    async def _submit_form(self) -> None:
        """Clica no botão de envio com pausa humana antes."""
        # Humano "revisa" antes de clicar
        await self._human.think()

        submit_selector = await self._find_visible_selector(
            self.SUBMIT_SELECTORS, "Botão Entrar"
        )
        await self._human.click_humanly(submit_selector)
        logger.info("Formulário submetido")

    async def _find_visible_selector(
        self, selectors: list, label: str
    ) -> str:
        """
        Retorna o primeiro seletor cujo elemento esteja visível.

        Raises:
            ValueError: Se nenhum elemento for encontrado
        """
        for selector in selectors:
            try:
                element = self._page.locator(selector).first
                if await element.is_visible(timeout=2000):
                    logger.debug(f"{label} localizado: {selector}")
                    return selector
            except Exception:
                continue

        raise ValueError(f"Elemento '{label}' não encontrado na página")
