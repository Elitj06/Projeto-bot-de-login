"""
Configurações centralizadas do Bot SEAP v2.

Todas as constantes e configurações ficam aqui.
Para alterar URL, timeout ou qualquer parâmetro, modifique apenas este arquivo.

Princípio aplicado: Single Source of Truth (SSOT)
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()


@dataclass(frozen=True)
class CapSolverConfig:
    """Configurações do serviço CapSolver para resolução de captcha."""
    api_key: str = os.getenv("CAPSOLVER_API_KEY", "")
    base_url: str = "https://api.capsolver.com"
    create_task_endpoint: str = "/createTask"
    get_result_endpoint: str = "/getTaskResult"
    polling_interval_seconds: float = 1.5
    max_polling_attempts: int = 40  # 40 x 1.5s = 60s no máximo
    seap_website_url: str = "https://www.seapsistema.rj.gov.br/"  # Ajuda o solver a calibrar
    expected_min_chars: int = 4
    expected_max_chars: int = 6
    manual_fallback: bool = os.getenv("CAPTCHA_MANUAL_FALLBACK", "true").lower() in ("true", "1", "yes")

    def validate(self) -> None:
        """Garante que a chave de API foi configurada."""
        if not self.api_key:
            raise ValueError(
                "CAPSOLVER_API_KEY não configurada. "
                "Crie um arquivo .env com sua chave (veja .env.example)."
            )


@dataclass(frozen=True)
class SeapConfig:
    """Configurações do site SEAP-RJ (ASP.NET WebForms)."""
    base_url: str = "https://www.seapsistema.rj.gov.br"
    login_path: str = "/"  # WebForms: login é a página default
    menu_path: str = "/FrmMenuVoluntario.aspx"
    filter_path: str = "/FrmEventoAssociar.aspx"
    page_load_timeout_ms: int = 30000  # 30 segundos
    element_wait_timeout_ms: int = 10000  # 10 segundos


@dataclass(frozen=True)
class FilterConfig:
    """Seletores da página de filtro de vagas (FrmEventoAssociar.aspx)."""
    unit_selectors: tuple = (
        "select#ddlUnidade",
        "select[name*='Unidade']",
        "select[name*='unidade']",
    )
    date_selectors: tuple = (
        "input#txtData",
        "input[type='date']",
        "input[name*='data']",
        "input[name*='Data']",
    )
    submit_selectors: tuple = (
        "button#btnPesquisar",
        "button:has-text('Pesquisar')",
        "button:has-text('Buscar')",
        "button:has-text('Filtrar')",
        "input[type='submit']",
        "button[type='submit']",
    )
    menu_link_selectors: tuple = (
        "a[href*='FrmEventoAssociar']",
        "a:has-text('Evento')",
        "a:has-text('Associar')",
        "a[href*='Evento']",
    )


@dataclass(frozen=True)
class CaptchaProviderConfig:
    """Configuração da cadeia de providers de captcha."""
    providers: Tuple[str, ...] = field(
        default_factory=lambda: tuple(
            provider.strip().lower()
            for provider in os.getenv(
                "CAPTCHA_PROVIDERS",
                "capsolver,openai_vision",
            ).split(",")
            if provider.strip()
        )
    )
    expected_min_chars: int = int(os.getenv("CAPTCHA_EXPECTED_MIN_CHARS", "4"))
    expected_max_chars: int = int(os.getenv("CAPTCHA_EXPECTED_MAX_CHARS", "6"))


@dataclass(frozen=True)
class CaptchaFlowConfig:
    """Parâmetros operacionais do fluxo de captcha do SEAP."""
    variant_order: Tuple[str, ...] = field(
        default_factory=lambda: tuple(
            variant.strip().lower()
            for variant in os.getenv(
                "CAPTCHA_VARIANT_ORDER",
                "original,gray3x,bw3x",
            ).split(",")
            if variant.strip()
        )
    )
    refresh_timeout_seconds: float = float(
        os.getenv("CAPTCHA_REFRESH_TIMEOUT_SECONDS", "8")
    )
    refresh_poll_interval_seconds: float = float(
        os.getenv("CAPTCHA_REFRESH_POLL_INTERVAL_SECONDS", "0.5")
    )
    retry_result_wait_seconds: float = float(
        os.getenv("CAPTCHA_RETRY_RESULT_WAIT_SECONDS", "3")
    )


@dataclass(frozen=True)
class OpenAIVisionConfig:
    """Configuração opcional para leitura multimodal de captcha."""
    api_key: str = os.getenv("CAPTCHA_VISION_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    base_url: str = os.getenv(
        "CAPTCHA_VISION_BASE_URL",
        "https://api.openai.com/v1/chat/completions",
    )
    model: str = os.getenv("CAPTCHA_VISION_MODEL", "gpt-4.1-mini")
    timeout_seconds: float = float(os.getenv("CAPTCHA_VISION_TIMEOUT_SECONDS", "30"))
    max_tokens: int = int(os.getenv("CAPTCHA_VISION_MAX_TOKENS", "24"))

    def enabled(self) -> bool:
        """Indica se o fallback multimodal está configurado."""
        return bool(self.api_key and self.model)


@dataclass(frozen=True)
class CamoufoxConfig:
    """
    Configurações do navegador Camoufox (Firefox stealth).

    Camoufox é mais difícil de detectar que Selenium/Playwright comum
    porque modifica fingerprints no nível C++ do Firefox.
    """
    headless: bool = os.getenv("BROWSER_HEADLESS", "false").lower() in ("true", "1", "yes")
    humanize: bool = True  # Movimentos de mouse humanizados (built-in)
    humanize_max_seconds: float = 1.5  # Tempo máximo de movimento

    # Sistema operacional simulado para fingerprint
    os_simulation: str = "windows"  # windows, macos ou linux

    # Bloquear imagens? (False = mais realista, True = mais rápido)
    block_images: bool = os.getenv("BLOCK_IMAGES", "false").lower() in ("true", "1", "yes")

    # Locale e timezone (importante para parecer brasileiro)
    locale: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"
    preferred_engines: Tuple[str, ...] = field(
        default_factory=lambda: tuple(
            engine.strip().lower()
            for engine in os.getenv(
                "BROWSER_ENGINES",
                "camoufox,firefox,chromium",
            ).split(",")
            if engine.strip()
        )
    )


@dataclass(frozen=True)
class HumanBehaviorConfig:
    """
    Configurações de comportamento humano simulado.

    Estes valores foram calibrados a partir de estudos de UX
    sobre tempos de reação humana real.
    """
    # Tempo de "pensar" antes de digitar (simula leitura)
    think_min_seconds: float = 0.8
    think_max_seconds: float = 2.5

    # Velocidade de digitação (caracteres por segundo)
    typing_min_delay_ms: int = 80   # Digitação rápida
    typing_max_delay_ms: int = 220  # Digitação devagar

    # Pausa após digitar uma palavra/campo
    field_complete_min_seconds: float = 0.4
    field_complete_max_seconds: float = 1.2

    # Tempo de movimentação do mouse antes de clicar
    mouse_move_min_seconds: float = 0.3
    mouse_move_max_seconds: float = 1.0

    # Probabilidade de fazer "erro" e corrigir (humanização extra)
    typo_probability: float = 0.05  # 5% de chance


@dataclass(frozen=True)
class ProxyConfig:
    """
    Configuração de proxy residencial brasileiro.

    Necessário porque o SEAP-RJ bloqueia IPs fora do Brasil.
    O servidor está na Alemanha (Hetzner), então todo tráfego
    precisa passar por proxy BR.

    Provedor: Decodo (residential proxies)
    Tipo: Sticky (10 min)
    """
    enabled: bool = os.getenv("PROXY_ENABLED", "false").lower() in ("true", "1", "yes")
    host: str = os.getenv("PROXY_HOST", "br.decodo.com")
    port: str = os.getenv("PROXY_PORT", "10001")
    username: str = os.getenv("PROXY_USER", "")
    password: str = os.getenv("PROXY_PASSWORD", "")
    # Portas alternativas (pool rotativo)
    ports_pool: Tuple[str, ...] = (
        "10001", "10002", "10003", "10004", "10005",
        "10006", "10007", "10008", "10009", "10010",
    )

    @property
    def server_url(self) -> str:
        """URL do servidor proxy (ex: http://br.decodo.com:10001)."""
        return f"http://{self.host}:{self.port}"

    def validate(self) -> None:
        """Garante que as credenciais de proxy estão configuradas."""
        if self.enabled and (not self.username or not self.password):
            raise ValueError(
                "Proxy habilitado mas credenciais não configuradas. "
                "Defina PROXY_USER e PROXY_PASSWORD no .env."
            )


@dataclass(frozen=True)
class PathConfig:
    """Caminhos importantes do projeto."""
    project_root: Path = Path(__file__).parent
    logs_dir: Path = field(default_factory=lambda: Path(__file__).parent / "logs")
    captchas_dir: Path = field(default_factory=lambda: Path(__file__).parent / "captchas_capturados")

    def ensure_dirs_exist(self) -> None:
        """Cria diretórios se não existirem."""
        self.logs_dir.mkdir(exist_ok=True)
        self.captchas_dir.mkdir(exist_ok=True)


# Instâncias singleton para uso em todo o projeto
capsolver_config = CapSolverConfig()
seap_config = SeapConfig()
filter_config = FilterConfig()
captcha_provider_config = CaptchaProviderConfig()
captcha_flow_config = CaptchaFlowConfig()
openai_vision_config = OpenAIVisionConfig()
camoufox_config = CamoufoxConfig()
human_behavior_config = HumanBehaviorConfig()
proxy_config = ProxyConfig()
path_config = PathConfig()
