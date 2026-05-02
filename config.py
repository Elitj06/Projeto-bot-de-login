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

    def validate(self) -> None:
        """Garante que a chave de API foi configurada."""
        if not self.api_key:
            raise ValueError(
                "CAPSOLVER_API_KEY não configurada. "
                "Crie um arquivo .env com sua chave (veja .env.example)."
            )


@dataclass(frozen=True)
class SeapConfig:
    """Configurações do site SEAP-RJ."""
    base_url: str = "https://seapsistema.rj.gov.br"
    login_path: str = "/login"
    page_load_timeout_ms: int = 30000  # 30 segundos
    element_wait_timeout_ms: int = 10000  # 10 segundos


@dataclass(frozen=True)
class CamoufoxConfig:
    """
    Configurações do navegador Camoufox (Firefox stealth).

    Camoufox é mais difícil de detectar que Selenium/Playwright comum
    porque modifica fingerprints no nível C++ do Firefox.
    """
    headless: bool = False  # False = mostra navegador (mais seguro)
    humanize: bool = True  # Movimentos de mouse humanizados (built-in)
    humanize_max_seconds: float = 1.5  # Tempo máximo de movimento

    # Sistema operacional simulado para fingerprint
    os_simulation: str = "windows"  # windows, macos ou linux

    # Bloquear images? (False = mais realista, True = mais rápido)
    block_images: bool = False

    # Locale e timezone (importante para parecer brasileiro)
    locale: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"


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
camoufox_config = CamoufoxConfig()
human_behavior_config = HumanBehaviorConfig()
path_config = PathConfig()
