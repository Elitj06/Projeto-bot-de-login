"""
Exceções customizadas do módulo de captcha.

Cada tipo de erro tem sua própria classe, permitindo tratamento
granular e mensagens específicas para cada situação.
"""


class CaptchaError(Exception):
    """Exceção base para todos os erros relacionados a captcha."""
    pass


class CapSolverConnectionError(CaptchaError):
    """Erro de conexão com a API do CapSolver."""
    pass


class CapSolverApiError(CaptchaError):
    """Erro retornado pela API do CapSolver."""

    def __init__(self, error_id: int, error_code: str, error_description: str):
        self.error_id = error_id
        self.error_code = error_code
        self.error_description = error_description
        super().__init__(
            f"CapSolver API erro [{error_code}]: {error_description}"
        )


class CaptchaTimeoutError(CaptchaError):
    """Captcha não foi resolvido dentro do tempo limite."""
    pass


class CaptchaImageNotFoundError(CaptchaError):
    """Imagem do captcha não foi encontrada na página."""
    pass


class CaptchaFieldNotFoundError(CaptchaError):
    """Campo de input do captcha não foi encontrado na página."""
    pass


class InvalidApiKeyError(CaptchaError):
    """Chave de API do CapSolver inválida ou ausente."""
    pass
