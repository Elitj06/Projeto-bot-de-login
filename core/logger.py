"""
Sistema de logging centralizado.

Cria logs estruturados com timestamp, nível e origem.
Salva em arquivo e exibe no console simultaneamente.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import path_config


class LoggerFactory:
    """Fábrica de loggers configurados (Singleton pattern)."""

    _is_configured: bool = False

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Retorna um logger configurado para o módulo.

        Args:
            name: Nome do módulo (geralmente __name__)

        Returns:
            Logger pronto para uso
        """
        if not cls._is_configured:
            cls._setup_root_logger()
            cls._is_configured = True

        return logging.getLogger(name)

    @classmethod
    def _setup_root_logger(cls) -> None:
        """Configura o logger raiz uma única vez."""
        path_config.ensure_dirs_exist()

        log_file = cls._get_log_filepath()

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Handler para arquivo (todos os níveis)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        # Handler para console (info para cima)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # Configurar logger raiz
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    @staticmethod
    def _get_log_filepath() -> Path:
        """Gera caminho do arquivo de log com timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return path_config.logs_dir / f"bot_seap_{timestamp}.log"
