"""
Bot de login SEAP-RJ — ASP.NET WebForms.

Fluxo baseado em análise real do DevTools (15/05/2026):
1. Navegar para seapsistema.rj.gov.br
2. Selecionar 'ID Funcional' no dropdown ddlTipoAcesso (__doPostBack)
3. Aguardar reload (WebForms postback)
4. Preencher ID + Senha
5. Resolver CAPTCHA (imagem base64 inline)
6. Submeter 'Avançar'
"""
from dataclasses import dataclass
import asyncio
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page
else:  # pragma: no cover - ambiente de teste sem Playwright
    Page = Any

from captcha.captcha_handler import CaptchaHandler
from captcha.provider_chain import CaptchaProviderChain
from config import captcha_flow_config, seap_config
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


@dataclass
class LoginAttemptEvaluation:
    """Classificação do resultado de uma tentativa de login."""

    status: str
    message: str
    current_url: str
    login_message: str = ""
    general_message: str = ""
    user_label: str = ""


class SeapLoginBot:
    """
    Bot de login do SEAP-RJ — ASP.NET WebForms.

    Seletores mapeados via DevTools (15/05/2026):
    - select#ddlTipoAcesso  → dropdown tipo de login
    - div#pnlEntrar         → painel com campos de login
    - div#captcha > div     → imagem CAPTCHA (base64 inline)
    - form#form1            → form principal (action=./)
    """

    LOGIN_TYPE_DROPDOWN = "select#ddlTipoAcesso"
    LOGIN_PANEL = "div#pnlEntrar"
    USERNAME_FIELD = "input#txtLogin"
    PASSWORD_FIELD = "input#txtSenha"
    CAPTCHA_INPUT = "input#TextCaptcha"

    CAPTCHA_NEW_LINK = "a#lnkNewCaptcha"
    SUBMIT_BUTTON = "input#btnEntrar"
    LOGIN_MESSAGE = "span#lblLoginMsg"
    GENERAL_MESSAGE = "span#lblMsg"
    USER_LABEL = "span#lblUsuario"

    DROPDOWN_VALUE_ID = "ID"
    MAX_CAPTCHA_RETRIES = 3

    def __init__(self, page: Page) -> None:
        self._page = page
        self._human = HumanActions(page)
        self._captcha_handler = CaptchaHandler(
            page=page,
            solver_chain=CaptchaProviderChain(),
            human_actions=self._human,
        )

    async def execute_login(self, credentials: LoginCredentials) -> LoginResult:
        """Executa o fluxo completo de login com retry guiado pela resposta do site."""
        if not credentials.is_valid():
            return LoginResult(
                success=False,
                message="Credenciais inválidas (usuário ou senha vazios)",
            )

        import time

        start = time.time()

        try:
            await self._navigate_to_login_page()
            await self._prepare_login_form()
            await self._fill_credentials(credentials)

            captcha_solution = ""
            last_evaluation: LoginAttemptEvaluation | None = None

            for attempt in range(1, self.MAX_CAPTCHA_RETRIES + 1):
                logger.info("Tentativa de captcha %s/%s", attempt, self.MAX_CAPTCHA_RETRIES)
                try:
                    captcha_solution = await self._solve_captcha()
                    await self._submit_form()
                    last_evaluation = await self._evaluate_login_attempt()

                    if last_evaluation.status == "success":
                        elapsed = time.time() - start
                        return LoginResult(
                            success=True,
                            message=last_evaluation.message,
                            captcha_solution=captcha_solution,
                            elapsed_seconds=round(elapsed, 2),
                        )

                    logger.warning(
                        "Tentativa %s rejeitada pelo site: %s",
                        attempt,
                        last_evaluation.message,
                    )
                    if last_evaluation.status == "fatal_credentials":
                        elapsed = time.time() - start
                        await self._save_failure_artifact("debug_after_submit.png")
                        return LoginResult(
                            success=False,
                            message=last_evaluation.message,
                            captcha_solution=captcha_solution,
                            elapsed_seconds=round(elapsed, 2),
                        )
                except Exception as error:
                    logger.warning("Captcha falhou na tentativa %s: %s", attempt, error)
                    if attempt == self.MAX_CAPTCHA_RETRIES:
                        raise
                    await self._reset_captcha_flow(credentials)
                    continue

                if attempt == self.MAX_CAPTCHA_RETRIES:
                    break

                await self._reset_captcha_flow(credentials)

            await self._save_failure_artifact("debug_after_submit.png")
            elapsed = time.time() - start
            failure_message = (
                last_evaluation.message
                if last_evaluation
                else "Login não confirmado após esgotar tentativas de captcha"
            )
            return LoginResult(
                success=False,
                message=failure_message,
                captcha_solution=captcha_solution,
                elapsed_seconds=round(elapsed, 2),
            )

        except Exception as error:
            logger.exception("Erro durante o login")
            return LoginResult(
                success=False,
                message=f"Erro: {type(error).__name__} - {error}",
            )

    async def _navigate_to_login_page(self) -> None:
        """Navega direto para o sistema SEAP (WebForms)."""
        url = seap_config.base_url
        logger.info("Navegando para: %s", url)

        await self._page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await asyncio.sleep(3)
        await self._human.reading_pause()

        try:
            await self._page.wait_for_selector("form#form1", timeout=15_000)
            logger.info("Formulário form1 carregado")
        except Exception:
            logger.warning("form1 não encontrado — página pode ter redirecionado")

        try:
            debug_dir = os.path.dirname(os.path.abspath(__file__))
            parent = os.path.dirname(debug_dir)
            await self._page.screenshot(path=os.path.join(parent, "debug_page.png"))
            html = await self._page.content()
            with open(os.path.join(parent, "debug_page.html"), "w", encoding="utf-8") as file_handle:
                file_handle.write(html)
            logger.info("Debug screenshot + HTML salvos")
        except Exception as error:
            logger.warning("Falha ao salvar debug: %s", error)

    async def _prepare_login_form(self) -> None:
        """Seleciona o tipo de acesso e aguarda o estado pós-postback."""
        await self._select_login_type()
        await self._wait_for_postback_state()

    async def _select_login_type(self) -> None:
        """Seleciona 'ID Funcional' no dropdown ddlTipoAcesso."""
        try:
            select2_container = self._page.locator(".select2-container").first
            uses_select2 = False
            try:
                uses_select2 = await select2_container.is_visible(timeout=2000)
            except Exception:
                pass

            if uses_select2:
                logger.info("Detectado Select2 — interagindo via widget")
                await select2_container.click()
                await asyncio.sleep(0.5)
                option = self._page.locator(".select2-results__option:has-text('ID Funcional')").first
                try:
                    await option.click(timeout=3000)
                    logger.info("Select2: ID Funcional selecionado")
                except Exception:
                    options = self._page.locator(".select2-results__option")
                    count = await options.count()
                    if count > 1:
                        await options.nth(1).click()
                        logger.info("Select2: segunda opção selecionada")
                await self._assert_login_type_selected()
                return

            dropdown = self._page.locator(self.LOGIN_TYPE_DROPDOWN).first
            if not await dropdown.is_visible(timeout=5_000):
                logger.warning("Dropdown ddlTipoAcesso não visível — pulando")
                return

            logger.info("Dropdown nativo ddlTipoAcesso encontrado")
            try:
                await dropdown.select_option(value=self.DROPDOWN_VALUE_ID)
                logger.info("Selecionado: value='%s'", self.DROPDOWN_VALUE_ID)
            except Exception as error:
                logger.warning("select_option falhou: %s", error)
                try:
                    await dropdown.select_option(label="ID Funcional")
                    logger.info("Selecionado: ID Funcional (label)")
                except Exception:
                    options = await dropdown.locator("option").all()
                    for option in options[1:]:
                        value = await option.get_attribute("value")
                        if value and value != "0":
                            await dropdown.select_option(value=value)
                            logger.info("Selecionado: %s", value)
                            break
            await self._assert_login_type_selected()
        except Exception as error:
            logger.warning("Erro ao selecionar tipo de login: %s", error)
            raise

    async def _assert_login_type_selected(self) -> None:
        """Confirma que o dropdown realmente ficou em ID Funcional."""
        dropdown = self._page.locator(self.LOGIN_TYPE_DROPDOWN).first
        selected_value = await dropdown.input_value(timeout=3000)
        if selected_value == self.DROPDOWN_VALUE_ID:
            return

        selected_label = await dropdown.locator("option:checked").inner_text(timeout=3000)
        if "id funcional" in selected_label.lower():
            return

        raise ValueError(
            f"Tipo de login não confirmado após seleção (value='{selected_value}', label='{selected_label}')"
        )

    async def _wait_for_postback_state(self) -> None:
        """Aguarda os campos reais de login aparecerem após o postback."""
        logger.info("Aguardando estado pós-postback do WebForms...")
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass

        await self._page.wait_for_selector(self.USERNAME_FIELD, timeout=15_000)
        await self._page.wait_for_selector(self.PASSWORD_FIELD, timeout=15_000)
        await self._page.wait_for_selector(self.CAPTCHA_INPUT, timeout=15_000)
        await self._human.reading_pause()

    async def _fill_credentials(self, credentials: LoginCredentials) -> None:
        """Preenche ID e senha com digitação humana."""
        await self._ensure_visible(self.USERNAME_FIELD, "ID Funcional")
        await self._human.type_humanly(
            self.USERNAME_FIELD,
            credentials.username,
            with_typos=True,
        )

        await self._human.think()

        await self._ensure_visible(self.PASSWORD_FIELD, "Senha")
        await self._human.type_humanly(
            self.PASSWORD_FIELD,
            credentials.password,
            with_typos=False,
        )
        await self._human.micro_pause()

    async def _solve_captcha(self) -> str:
        """Resolve o captcha usando CapSolver + comportamento humano."""
        return await self._captcha_handler.solve_and_fill()

    async def _submit_form(self) -> None:
        """Submete o login com fallback apropriado para WebForms."""
        await self._human.think()

        submit_strategies = [
            ("click", self._click_submit_button),
            ("postback", self._submit_via_postback),
            ("form-submit", self._submit_via_form),
        ]
        for label, strategy in submit_strategies:
            try:
                await strategy()
                logger.info("Submit executado via %s", label)
                await asyncio.sleep(3)
                if not await self._login_form_still_visible():
                    return
            except Exception:
                continue
        raise ValueError("Botão submit não conseguiu disparar o login")

    async def _click_submit_button(self) -> None:
        """Tenta clicar no botão principal ou em fallbacks visuais."""
        selectors = [
            self.SUBMIT_BUTTON,
            "input[type='submit']",
            "button[type='submit']",
            "button.btn-primary",
        ]
        for selector in selectors:
            element = self._page.locator(selector).first
            if await element.is_visible(timeout=2000):
                await self._human.click_humanly(selector)
                return
        raise ValueError("Nenhum botão de submit visível")

    async def _submit_via_postback(self) -> None:
        """Fallback específico para WebForms."""
        await self._page.evaluate(
            """() => {
                if (typeof __doPostBack === 'function') {
                    __doPostBack('btnEntrar', '');
                } else {
                    throw new Error('WebForms __doPostBack indisponível');
                }
            }"""
        )

    async def _submit_via_form(self) -> None:
        """Último fallback: submit do form diretamente."""
        await self._page.locator("form#form1").evaluate("form => form.submit()")

    async def _login_form_still_visible(self) -> bool:
        """Detecta se continuamos na tela de login após uma tentativa de submit."""
        try:
            locator = self._page.locator(self.USERNAME_FIELD).first
            return await locator.is_visible(timeout=1500)
        except Exception:
            return False

    async def _evaluate_login_attempt(self) -> LoginAttemptEvaluation:
        """Lê o feedback real do site após o submit e classifica a tentativa."""
        await asyncio.sleep(captcha_flow_config.retry_result_wait_seconds)
        current_url = self._page.url
        login_message = await self._read_optional_text(self.LOGIN_MESSAGE)
        general_message = await self._read_optional_text(self.GENERAL_MESSAGE)
        user_label = await self._read_optional_text(self.USER_LABEL)
        form_visible = await self._login_form_still_visible()
        status, message = self._classify_attempt_feedback(
            current_url=current_url,
            form_visible=form_visible,
            login_message=login_message,
            general_message=general_message,
            user_label=user_label,
        )
        return LoginAttemptEvaluation(
            status=status,
            message=message,
            current_url=current_url,
            login_message=login_message,
            general_message=general_message,
            user_label=user_label,
        )

    @staticmethod
    def _classify_attempt_feedback(
        current_url: str,
        form_visible: bool,
        login_message: str,
        general_message: str,
        user_label: str,
    ) -> tuple[str, str]:
        """Decide se a resposta do site indica sucesso, erro fatal ou retry."""
        normalized_url = current_url.rstrip("/").lower()
        login_urls = {
            seap_config.base_url.rstrip("/").lower(),
            f"{seap_config.base_url.rstrip('/')}/default.aspx".lower(),
        }

        if user_label.strip():
            return "success", f"Login executado com sucesso para '{user_label.strip()}'"

        combined_message = " | ".join(
            part.strip() for part in (login_message, general_message) if part and part.strip()
        )
        normalized_message = combined_message.lower()

        credential_keywords = (
            "senha",
            "usuário",
            "usuario",
            "login inválido",
            "login invalido",
            "credencial",
        )
        captcha_keywords = (
            "captcha",
            "código",
            "codigo",
            "imagem",
            "incorreto",
        )

        if normalized_message and any(keyword in normalized_message for keyword in captcha_keywords):
            return "retry_captcha", combined_message

        if normalized_message and any(keyword in normalized_message for keyword in credential_keywords):
            return "fatal_credentials", combined_message

        if not form_visible and normalized_url not in login_urls:
            return "success", "Login executado com sucesso"

        if combined_message:
            return "retry_captcha", combined_message

        return "retry_captcha", "Tela de login permaneceu aberta sem confirmação do acesso"

    async def _read_optional_text(self, selector: str) -> str:
        """Lê texto opcional de um seletor sem falhar o fluxo."""
        try:
            locator = self._page.locator(selector).first
            text = await locator.inner_text(timeout=2000)
            return (text or "").strip()
        except Exception:
            return ""

    async def _reset_captcha_flow(self, credentials: LoginCredentials) -> None:
        """Gera novo captcha ou refaz a página de login de forma completa."""
        logger.info("Gerando novo captcha...")
        try:
            previous_signature = await self._safe_get_captcha_signature()
            if not previous_signature:
                raise RuntimeError("Assinatura anterior do captcha indisponível")
            new_image = self._page.locator(self.CAPTCHA_NEW_LINK).first
            if await new_image.is_visible(timeout=3000):
                await new_image.click()
                await self._wait_for_captcha_refresh(previous_signature)
                await self._fill_credentials(credentials)
                return
        except Exception as error:
            logger.warning("Link de novo captcha falhou; recarregando página: %s", error)

        await self._page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(2)
        await self._prepare_login_form()
        await self._fill_credentials(credentials)

    async def _wait_for_captcha_refresh(self, previous_signature: str | None) -> None:
        """Espera até que o captcha realmente mude após o refresh."""
        await self._wait_for_postback_state()
        if not previous_signature:
            return

        timeout_seconds = captcha_flow_config.refresh_timeout_seconds
        poll_interval = captcha_flow_config.refresh_poll_interval_seconds
        attempts = max(1, int(timeout_seconds / poll_interval))

        for _ in range(attempts):
            await asyncio.sleep(poll_interval)
            current_signature = await self._safe_get_captcha_signature()
            if current_signature and current_signature != previous_signature:
                logger.info("Captcha renovado com nova assinatura")
                return

        raise TimeoutError("Captcha não mudou após solicitar nova imagem")

    async def _safe_get_captcha_signature(self) -> str | None:
        """Obtém a assinatura do captcha atual sem interromper o fluxo."""
        try:
            return await self._captcha_handler.current_captcha_signature()
        except Exception as error:
            logger.warning("Não foi possível capturar assinatura do captcha: %s", error)
            return None

    async def _save_failure_artifact(self, filename: str) -> None:
        """Salva screenshot de apoio quando a tentativa não confirma o login."""
        screenshot_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            filename,
        )
        try:
            await self._page.screenshot(path=str(screenshot_path))
            logger.warning("Artefato de falha salvo em: %s", screenshot_path)
        except Exception as error:
            logger.warning("Falha ao salvar artefato de erro: %s", error)

    async def _ensure_visible(self, selector: str, label: str) -> None:
        """Garante que o elemento está visível antes de interagir."""
        element = self._page.locator(selector).first
        if not await element.is_visible(timeout=5000):
            raise ValueError(f"{label} ({selector}) não está visível")
        logger.debug("%s visível: %s", label, selector)
