"""
Bot de login SEAP-RJ — Fluxo multi-página.

Página 1: Login com CAPTCHA
Página 2: Filtro de vagas (FrmEventoAssociar.aspx) com segundo CAPTCHA

Cada etapa é um método claro e auditável, com pausas humanas
naturais entre elas.
"""
from dataclasses import dataclass

from playwright.async_api import Page

from captcha.captcha_handler import CaptchaHandler
from captcha.capsolver_client import CapSolverClient
from config import seap_config, filter_config
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
    filter_captcha_solution: str = ""
    filter_page_reached: bool = False
    filter_submitted: bool = False
    elapsed_seconds: float = 0.0


class SeapLoginBot:
    """
    Bot de login do SEAP-RJ com Camoufox + comportamento humano.

    Fluxo:
      Página 1: navegar → selecionar tipo → credenciais → CAPTCHA → submit
      Verificação: confirmar que login funcionou
      Página 2 (opcional): navegar para filtro → preencher → CAPTCHA → submit
    """

    # ── Página 1: Login ──
    LOGIN_TYPE_DROPDOWN_SELECTORS = [
        "select[name='tipoLogin']",
        "select[id='tipoLogin']",
        "select[name='loginType']",
        "select[id='loginType']",
        "select",
    ]

    USERNAME_SELECTORS = [
        "input[name='username']",
        "input[name='login']",
        "input[name='user']",
        "input[name='email']",
        "input[id='username']",
        "input[id='login']",
        "input[id='user']",
        "input[id='idFuncional']",
        "input[type='text']",
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
        "button:has-text('Avançar')",
        "button:has-text('Entrar')",
        "button:has-text('Login')",
        "button:has-text('Acessar')",
        "a.btn:has-text('Avançar')",
        "input[value='Avançar']",
    ]

    # ── Login verification ──
    LOGIN_SUCCESS_INDICATORS = [
        "span#lblUsuario",
        "span:has-text('Bem-vindo')",
        "div:has-text('Menu')",
    ]

    LOGIN_ERROR_INDICATORS = [
        ".alert-danger",
        ".error-message",
        "div:has-text('inválido')",
        "div:has-text('incorret')",
        "div:has-text('Erro ao confirmar')",
    ]

    def __init__(self, page: Page) -> None:
        self._page = page
        self._human = HumanActions(page)
        self._captcha_handler = CaptchaHandler(
            page=page,
            capsolver_client=CapSolverClient(),
            human_actions=self._human,
        )

    # ──────────────────────────────────────────────
    # ENTRY POINT
    # ──────────────────────────────────────────────

    async def execute_login(
        self,
        credentials: LoginCredentials,
        filter_unit: str = "",
        filter_date: str = "",
    ) -> LoginResult:
        """
        Executa o fluxo completo: página 1 (login) + página 2 (filtro, opcional).

        Se filter_unit ou filter_date forem fornecidos, navega para
        FrmEventoAssociar.aspx após login e resolve o segundo CAPTCHA.
        """
        if not credentials.is_valid():
            return LoginResult(
                success=False,
                message="Credenciais inválidas (usuário ou senha vazios)",
            )

        try:
            # ── PÁGINA 1: Login ──
            await self._navigate_to_login_page()
            await self._select_login_type()
            await self._fill_credentials(credentials)
            captcha_solution = await self._solve_captcha()
            await self._submit_form()

            # ── Verificar se login funcionou ──
            login_ok = await self._verify_login_success()
            if not login_ok:
                return LoginResult(
                    success=False,
                    message="Login falhou — credenciais ou captcha incorretos",
                    captcha_solution=captcha_solution,
                )

            # ── PÁGINA 2: Filtro (opcional) ──
            filter_captcha_solution = ""
            filter_submitted = False
            wants_filter = bool(filter_unit or filter_date)

            if wants_filter:
                await self._human.reading_pause()
                await self._navigate_to_filter_page()
                await self._fill_filter_fields(filter_unit, filter_date)
                filter_captcha_solution = await self._solve_second_captcha()
                await self._submit_filter()
                filter_submitted = True

            return LoginResult(
                success=True,
                message="Login executado com sucesso",
                captcha_solution=captcha_solution,
                filter_captcha_solution=filter_captcha_solution,
                filter_page_reached=wants_filter,
                filter_submitted=filter_submitted,
            )

        except Exception as e:
            logger.exception("Erro durante o login")
            return LoginResult(
                success=False,
                message=f"Erro: {type(e).__name__} - {e}",
            )

    # ──────────────────────────────────────────────
    # PÁGINA 1: LOGIN
    # ──────────────────────────────────────────────

    async def _navigate_to_login_page(self) -> None:
        """Navega para a página de login com pausa humana."""
        url = f"{seap_config.base_url}{seap_config.login_path}"
        logger.info(f"Navegando para: {url}")

        await self._page.goto(
            url,
            wait_until="networkidle",
            timeout=seap_config.page_load_timeout_ms,
        )
        await self._human.reading_pause()

    async def _select_login_type(self) -> None:
        """Seleciona 'ID Funcional' no dropdown de tipo de login."""
        for selector in self.LOGIN_TYPE_DROPDOWN_SELECTORS:
            try:
                element = self._page.locator(selector).first
                if await element.is_visible(timeout=3000):
                    logger.info(f"Dropdown de login encontrado: {selector}")
                    for option in [("label", "ID Funcional"), ("value", "idFuncional"), ("label", "ID")]:
                        try:
                            if option[0] == "label":
                                await element.select_option(label=option[1])
                            else:
                                await element.select_option(value=option[1])
                            logger.info(f"Selecionado: {option[1]}")
                            break
                        except Exception:
                            continue
                    await self._human.think()
                    return
            except Exception:
                continue
        logger.warning("Dropdown de tipo de login não encontrado — pulando seleção")

    async def _fill_credentials(self, credentials: LoginCredentials) -> None:
        """Preenche usuário e senha com digitação humana."""
        username_selector = await self._find_visible_selector(
            self.USERNAME_SELECTORS, "Usuário"
        )
        await self._human.type_humanly(
            username_selector, credentials.username, with_typos=True
        )
        await self._human.think()

        password_selector = await self._find_visible_selector(
            self.PASSWORD_SELECTORS, "Senha"
        )
        await self._human.type_humanly(
            password_selector, credentials.password, with_typos=False
        )
        await self._human.micro_pause()

    async def _solve_captcha(self) -> str:
        """Resolve o captcha da página de login."""
        return await self._captcha_handler.solve_and_fill()

    async def _submit_form(self) -> None:
        """Clica no botão de envio."""
        await self._human.think()
        submit_selector = await self._find_visible_selector(
            self.SUBMIT_SELECTORS, "Botão Entrar"
        )
        await self._human.click_humanly(submit_selector)
        logger.info("Formulário de login submetido")

    # ──────────────────────────────────────────────
    # VERIFICAÇÃO DE LOGIN
    # ──────────────────────────────────────────────

    async def _verify_login_success(self) -> bool:
        """Verifica se o login foi bem-sucedido após submit."""
        await self._page.wait_for_load_state("networkidle", timeout=15000)
        current_url = self._page.url

        # URL mudou para fora de /login = sucesso
        if "login" not in current_url.lower():
            logger.info(f"Login OK — redirecionado para: {current_url}")
            return True

        # Verifica mensagens de erro na página
        for selector in self.LOGIN_ERROR_INDICATORS:
            try:
                el = self._page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    error_text = await el.inner_text()
                    logger.error(f"Login falhou: {error_text}")
                    return False
            except Exception:
                continue

        # Verifica indicadores de sucesso (pode estar na mesma URL)
        for selector in self.LOGIN_SUCCESS_INDICATORS:
            try:
                el = self._page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    logger.info("Login OK — indicador de sucesso encontrado")
                    return True
            except Exception:
                continue

        logger.warning("Não foi possível confirmar status do login")
        return False

    # ──────────────────────────────────────────────
    # PÁGINA 2: FILTRO DE VAGAS
    # ──────────────────────────────────────────────

    async def _navigate_to_filter_page(self) -> None:
        """Navega para FrmEventoAssociar.aspx via menu ou URL direta."""
        # Opção A: clicar no link do menu
        for selector in filter_config.menu_link_selectors:
            try:
                el = self._page.locator(selector).first
                if await el.is_visible(timeout=3000):
                    await self._human.click_humanly(selector)
                    await self._page.wait_for_load_state("networkidle", timeout=15000)
                    await self._human.reading_pause()
                    logger.info(f"Navegou para filtro via menu: {selector}")
                    return
            except Exception:
                continue

        # Opção B: navegação direta por URL
        filter_url = f"{seap_config.base_url}{seap_config.filter_path}"
        await self._page.goto(filter_url, wait_until="networkidle", timeout=30000)
        await self._human.reading_pause()
        logger.info(f"Navegou para filtro via URL: {filter_url}")

    async def _fill_filter_fields(self, unit: str, date: str) -> None:
        """Preenche dropdown de unidade e campo de data."""
        if unit:
            await self._select_dropdown_option(
                list(filter_config.unit_selectors), "Unidade", unit
            )
            await self._human.think()

        if date:
            date_selector = await self._find_visible_selector(
                list(filter_config.date_selectors), "Data"
            )
            await self._human.type_humanly(date_selector, date, with_typos=False)
            logger.info(f"Data preenchida: {date}")
            await self._human.think()

    async def _solve_second_captcha(self) -> str:
        """Resolve o segundo CAPTCHA na página de filtro."""
        logger.info("Resolvendo segundo CAPTCHA (página de filtro)...")
        return await self._captcha_handler.solve_and_fill()

    async def _submit_filter(self) -> None:
        """Submete o formulário de filtro."""
        await self._human.think()
        submit_selector = await self._find_visible_selector(
            list(filter_config.submit_selectors), "Botão Filtrar"
        )
        await self._human.click_humanly(submit_selector)
        logger.info("Filtro submetido")

    # ──────────────────────────────────────────────
    # UTILITÁRIOS
    # ──────────────────────────────────────────────

    async def _find_visible_selector(
        self, selectors: list, label: str
    ) -> str:
        """Retorna o primeiro seletor cujo elemento esteja visível."""
        for selector in selectors:
            try:
                element = self._page.locator(selector).first
                if await element.is_visible(timeout=2000):
                    logger.debug(f"{label} localizado: {selector}")
                    return selector
            except Exception:
                continue
        raise ValueError(f"Elemento '{label}' não encontrado na página")

    async def _select_dropdown_option(
        self, selectors: list, label: str, value: str
    ) -> None:
        """Seleciona uma opção em um dropdown (por label ou value)."""
        selector = await self._find_visible_selector(selectors, label)
        element = self._page.locator(selector).first

        for method in [("label", value), ("value", value)]:
            try:
                if method[0] == "label":
                    await element.select_option(label=method[1])
                else:
                    await element.select_option(value=method[1])
                logger.info(f"{label} selecionado: {value}")
                return
            except Exception:
                continue

        logger.warning(f"Falha ao selecionar {label}: {value}")
