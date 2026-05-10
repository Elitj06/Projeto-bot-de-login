"""
Sniper Engine — Motor principal de disparo de vagas.

Coordena o fluxo completo de disputa de vagas:
  1. Pre-warm: abre browsers, carrega página, preenche credenciais
  2. Arm: NTP sync, timer preciso, aguarda 06:00:00.000 BRT
  3. FIRE: submit simultâneo de todos os usuários
  4. Hunt: busca vagas, preenche, submete em loop
  5. Report: resultados em tempo real via WebSocket

Tudo é feito em paralelo — cada usuário tem seu próprio browser+proxy.
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable, Awaitable

from sniper.ntp_clock import ntp_clock, get_thursday_6am_brt, BRT
from core.logger import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class SniperUser:
    """Usuário pronto para o sniper."""
    id: str
    username: str
    password: str
    proxy: Optional[str] = None
    target_days: list[str] = field(default_factory=list)  # ["seg", "ter", "qua", "qui", "sex", "sab"]
    target_times: list[str] = field(default_factory=list)  # ["06:00-08:00", "08:00-10:00"]
    is_active: bool = True
    auto_snipe: bool = True


@dataclass
class SniperResult:
    """Resultado de uma tentativa de vaga."""
    user_id: str
    username: str
    success: bool
    vacancy_id: str = ""
    vacancy_title: str = ""
    submit_time_ms: float = 0.0
    error: str = ""
    timestamp: str = ""


@dataclass
class SniperSession:
    """Sessão completa do sniper."""
    session_id: str
    target_time: datetime  # 06:00:00.000 BRT
    users: list[SniperUser]
    status: str = "idle"  # idle, prewarming, armed, firing, hunting, complete
    results: list[SniperResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    fired_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Sniper Engine
# ---------------------------------------------------------------------------
class SniperEngine:
    """
    Motor de disparo de precisão para vagas SEAP.

    Orquestra múltiplos browsers em paralelo, disparando
    submissões simultâneas no milissegundo exato.
    """

    # Horários de referência
    FIRE_HOUR_UTC = 9   # 06h BRT = 09h UTC
    FIRE_MIN_UTC = 0
    FIRE_SEC_UTC = 0

    def __init__(self, emit_event: Optional[Callable] = None):
        """
        Args:
            emit_event: Callback para emitir eventos WebSocket
                        async emit_event(user_id, event_type, data)
        """
        self._emit = emit_event or self._default_emit
        self._active_session: Optional[SniperSession] = None
        self._browser_pages: dict[str, any] = {}  # user_id -> Playwright Page
        self._is_running = False

    @staticmethod
    async def _default_emit(user_id: str, event_type: str, data: dict):
        """Emit padrão (no-op se não configurado)."""
        pass

    def _emit_event(self, user_id: str, event_type: str, **kwargs):
        """Helper para emitir eventos."""
        try:
            data = {"type": event_type, **kwargs}
            if asyncio.iscoroutinefunction(self._emit):
                asyncio.create_task(self._emit(user_id, event_type, data))
        except Exception as e:
            logger.warning(f"Erro ao emitir evento: {e}")

    # -----------------------------------------------------------------------
    # Phase 1: Pre-warm (abrir browsers, carregar página)
    # -----------------------------------------------------------------------
    async def prewarm(self, users: list[SniperUser]) -> dict:
        """
        Prepara todos os browsers antes do horário alvo.

        Para cada usuário:
        1. Abre Camoufox com proxy dedicado
        2. Navega para a página de login
        3. Preenche credenciais (NÃO submete ainda)
        4. Fica aguardando o sinal de fogo

        Returns:
            {"ready": int, "failed": int, "details": list}
        """
        self._is_running = True
        session_id = f"sniper_{int(time.time())}"
        target = get_thursday_6am_brt()

        session = SniperSession(
            session_id=session_id,
            target_time=target,
            users=[u for u in users if u.is_active and u.auto_snipe],
            status="prewarming",
        )
        self._active_session = session

        logger.info(f"🔥 PREWARM: {len(session.users)} usuários, alvo: {target.astimezone(BRT).isoformat()}")

        # NTP sync antes de tudo
        sync_result = await ntp_clock.sync(samples=5)
        logger.info(f"NTP offset: {sync_result['offset_ms']}ms")

        self._emit_event("__all__", "prewarm_start", total=len(session.users), ntp_offset_ms=sync_result["offset_ms"])

        # Abre browsers em paralelo
        tasks = [self._prewarm_user(u) for u in session.users]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ready = sum(1 for r in results if isinstance(r, dict) and r.get("ready"))
        failed = len(results) - ready

        session.status = "armed" if ready > 0 else "failed"
        logger.info(f"🔥 PREWARM COMPLETE: {ready} prontos, {failed} falharam")

        self._emit_event("__all__", "prewarm_complete", ready=ready, failed=failed)

        return {
            "session_id": session_id,
            "ready": ready,
            "failed": failed,
            "target_time": target.isoformat(),
            "ntp_offset_ms": sync_result["offset_ms"],
        }

    async def _prewarm_user(self, user: SniperUser) -> dict:
        """Prepara browser para um usuário."""
        try:
            self._emit_event(user.id, "prewarming", username=user.username)

            from core.browser_manager import BrowserManager
            browser_mgr = BrowserManager()

            # Abre Camoufox com proxy do usuário
            page = await browser_mgr.create_page(proxy=user.proxy)

            # Navega para login
            from config import seap_config
            await page.goto(
                f"{seap_config.base_url}{seap_config.login_path}",
                wait_until="networkidle",
                timeout=30000,
            )

            # Preenche credenciais mas NÃO submete
            # (seletores serão atualizados quando o site voltar)
            username_filled = False
            for selector in [
                "input[name='username']", "input[name='login']",
                "input[id='username']", "input[id='login']",
                "input[type='text']", "input[type='email']",
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=2000):
                        await el.fill(user.username)
                        username_filled = True
                        break
                except Exception:
                    continue

            if not username_filled:
                logger.warning(f"Campo usuário não encontrado para {user.username}")

            # Preenche senha
            for selector in [
                "input[name='password']", "input[name='senha']",
                "input[id='password']", "input[type='password']",
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=2000):
                        await el.fill(user.password)
                        break
                except Exception:
                    continue

            # Armazena referência da página
            self._browser_pages[user.id] = {
                "page": page,
                "browser_mgr": browser_mgr,
                "user": user,
                "ready": True,
            }

            self._emit_event(user.id, "ready", username=user.username)
            logger.info(f"✓ {user.username} pronto (proxy: {user.proxy or 'direto'})")

            return {"user_id": user.id, "ready": True}

        except Exception as e:
            logger.error(f"✗ {user.username} falhou no prewarm: {e}")
            self._emit_event(user.id, "prewarm_failed", error=str(e))
            return {"user_id": user.id, "ready": False, "error": str(e)}

    # -----------------------------------------------------------------------
    # Phase 2: ARM — Aguarda o horário exato
    # -----------------------------------------------------------------------
    async def arm_and_wait(self) -> dict:
        """
        Aguarda até o horário exato de disparo usando NTP.

        Retorna quando faltam 0ms para o alvo.
        """
        session = self._active_session
        if not session:
            return {"error": "Nenhuma sessão ativa"}

        session.status = "armed"
        target = session.target_time

        # Re-sync NTP para máxima precisão
        sync_result = await ntp_clock.sync(samples=3)
        logger.info(f"🔥 ARMED: NTP offset={sync_result['offset_ms']}ms, aguardando {target.astimezone(BRT).isoformat()}")

        self._emit_event("__all__", "armed", target=target.isoformat(), ntp_offset_ms=sync_result["offset_ms"])

        # Wait until exact time
        await ntp_clock.wait_until(target, wake_early_ms=100)

        session.fired_at = ntp_clock.now()
        session.status = "firing"

        fire_offset_ms = (ntp_clock.now() - target).total_seconds() * 1000
        logger.info(f"🔥🔥🔥 FIRE! Offset: {fire_offset_ms:+.1f}ms")

        self._emit_event("__all__", "fired", offset_ms=round(fire_offset_ms, 1))

        return {"fired": True, "offset_ms": fire_offset_ms}

    # -----------------------------------------------------------------------
    # Phase 3: FIRE — Submit simultâneo
    # -----------------------------------------------------------------------
    async def fire(self) -> list[SniperResult]:
        """
    Dispara submissão simultânea de TODOS os usuários.

    Cada browser já tem credenciais preenchidas.
    Clica submit em todos ao mesmo tempo.
    """
        session = self._active_session
        if not session:
            return []

        fire_start = ntp_clock.now_us()
        logger.info(f"🔥 FIRING: {len(self._browser_pages)} usuários simultâneos")

        # Submit todos em paralelo absoluto
        tasks = []
        for user_id, data in self._browser_pages.items():
            if data.get("ready"):
                tasks.append(self._fire_user(user_id, data))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        session.status = "hunting"
        sniper_results = []
        for r in results:
            if isinstance(r, SniperResult):
                r.submit_time_ms = (ntp_clock.now_us() - fire_start) / 1000
                sniper_results.append(r)
                self._emit_event(r.user_id, "submit_result",
                    success=r.success, vacancy=r.vacancy_id, time_ms=r.submit_time_ms)

        session.results.extend(sniper_results)
        return sniper_results

    async def _fire_user(self, user_id: str, data: dict) -> SniperResult:
        """Submete formulário para um usuário."""
        user = data["user"]
        page = data["page"]

        try:
            # Clica no botão submit
            submitted = False
            for selector in [
                "button[type='submit']",
                "input[type='submit']",
                "button.btn-primary",
                "button:has-text('Entrar')",
                "button:has-text('Login')",
                "button:has-text('Acessar')",
            ]:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=500):
                        await el.click()
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                # Fallback: Enter no campo de senha
                await page.keyboard.press("Enter")
                submitted = True

            # Aguarda resposta (curto timeout — velocidade é tudo)
            await page.wait_for_load_state("networkidle", timeout=5000)

            return SniperResult(
                user_id=user_id,
                username=user.username,
                success=submitted,
                timestamp=ntp_clock.now().isoformat(),
            )

        except Exception as e:
            return SniperResult(
                user_id=user_id,
                username=user.username,
                success=False,
                error=str(e),
                timestamp=ntp_clock.now().isoformat(),
            )

    # -----------------------------------------------------------------------
    # Phase 4: HUNT — Loop de busca de vagas
    # -----------------------------------------------------------------------
    async def hunt(self, max_iterations: int = 50, interval_ms: int = 100) -> list[SniperResult]:
        """
        Após login, busca vagas disponíveis e tenta preencher em loop.

        Cada iteração:
        1. Busca vagas disponíveis na página
        2. Para cada vaga que corresponde ao target do usuário
        3. Clica, preenche formulário, submete
        4. Volta e repete

        Args:
            max_iterations: Máximo de tentativas por usuário
            interval_ms: Intervalo entre iterações (ms)
        """
        session = self._active_session
        if not session:
            return []

        logger.info(f"🎯 HUNT: Iniciando busca de vagas (max {max_iterations} iterações)")

        all_results = []

        for iteration in range(max_iterations):
            if not self._is_running:
                break

            tasks = []
            for user_id, data in self._browser_pages.items():
                if data.get("ready"):
                    tasks.append(self._hunt_iteration(user_id, data, iteration))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, SniperResult):
                    all_results.append(r)
                    if r.success:
                        self._emit_event(r.user_id, "vaga_captured",
                            vacancy=r.vacancy_id, title=r.vacancy_title, iteration=iteration)

            # Verifica se ainda há vagas
            any_vaga_found = any(isinstance(r, SniperResult) and r.success for r in results)
            if not any_vaga_found and iteration > 0:
                # Nenhuma vaga em 2+ iterações seguidas → provavelmente esgotou
                logger.info(f"🎯 HUNT: Nenhuma vaga encontrada na iteração {iteration}, parando")
                break

            await asyncio.sleep(interval_ms / 1000.0)

        session.status = "complete"
        session.completed_at = ntp_clock.now()
        self._emit_event("__all__", "hunt_complete",
            total_results=len(all_results), successes=sum(1 for r in all_results if r.success))

        return all_results

    async def _hunt_iteration(self, user_id: str, data: dict, iteration: int) -> SniperResult:
        """Uma iteração de busca de vaga para um usuário."""
        user = data["user"]
        page = data["page"]

        try:
            # TODO: Implementar seletores reais de busca de vagas
            # quando o site voltar e pudermos mapear o HTML

            # Placeholder — estrutura pronta para preencher
            # 1. Buscar lista de vagas disponíveis
            # 2. Filtrar por dias/horários do target do usuário
            # 3. Clicar na vaga
            # 4. Preencher formulário de candidatura
            # 5. Submeter

            return SniperResult(
                user_id=user_id,
                username=user.username,
                success=False,
                error="Hunt selectors not yet mapped",
                timestamp=ntp_clock.now().isoformat(),
            )

        except Exception as e:
            return SniperResult(
                user_id=user_id,
                username=user.username,
                success=False,
                error=str(e),
                timestamp=ntp_clock.now().isoformat(),
            )

    # -----------------------------------------------------------------------
    # Full pipeline
    # -----------------------------------------------------------------------
    async def execute_full_pipeline(self, users: list[SniperUser]) -> dict:
        """
        Executa pipeline completo: prewarm → arm → fire → hunt.
        """
        # Phase 1: Pre-warm
        prewarm_result = await self.prewarm(users)
        if prewarm_result["ready"] == 0:
            return {"error": "Nenhum usuário conseguiu preparar", "prewarm": prewarm_result}

        # Phase 2: Arm & Wait
        arm_result = await self.arm_and_wait()

        # Phase 3: Fire (submit login)
        login_results = await self.fire()

        # Phase 4: Hunt (buscar e preencher vagas)
        hunt_results = await self.hunt()

        # Report
        session = self._active_session
        all_results = login_results + hunt_results
        successes = sum(1 for r in all_results if r.success)

        return {
            "session_id": session.session_id if session else None,
            "fired_at": session.fired_at.isoformat() if session and session.fired_at else None,
            "fire_offset_ms": arm_result.get("offset_ms"),
            "total_attempts": len(all_results),
            "successes": successes,
            "ntp_offset_ms": ntp_clock.offset_ms,
            "login_results": [{"user_id": r.user_id, "success": r.success, "time_ms": r.submit_time_ms} for r in login_results],
            "hunt_results": [{"user_id": r.user_id, "success": r.success, "vacancy": r.vacancy_id} for r in hunt_results],
        }

    # -----------------------------------------------------------------------
    # Cancel / Cleanup
    # -----------------------------------------------------------------------
    async def cancel(self):
        """Cancela a sessão atual e fecha todos os browsers."""
        self._is_running = False
        for user_id, data in self._browser_pages.items():
            try:
                page = data.get("page")
                if page:
                    await page.close()
            except Exception:
                pass
        self._browser_pages.clear()
        if self._active_session:
            self._active_session.status = "cancelled"
        logger.info("Sniper cancelado — browsers fechados")

    def get_status(self) -> dict:
        """Retorna status atual do sniper."""
        session = self._active_session
        return {
            "running": self._is_running,
            "session_id": session.session_id if session else None,
            "status": session.status if session else "idle",
            "users_ready": len(self._browser_pages),
            "target_time": session.target_time.isoformat() if session else None,
            "ntp_offset_ms": ntp_clock.offset_ms,
            "next_thursday": get_thursday_6am_brt().isoformat(),
        }
