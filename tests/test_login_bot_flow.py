import sys
import types
import unittest

playwright_module = types.ModuleType("playwright")
async_api_module = types.ModuleType("playwright.async_api")
async_api_module.Page = object
async_api_module.ElementHandle = object
playwright_module.async_api = async_api_module
sys.modules.setdefault("playwright", playwright_module)
sys.modules.setdefault("playwright.async_api", async_api_module)

from automation.login_bot import SeapLoginBot


class LoginAttemptClassificationTests(unittest.TestCase):
    def test_detects_success_via_logged_user_label(self):
        status, message = SeapLoginBot._classify_attempt_feedback(
            current_url="https://www.seapsistema.rj.gov.br/home.aspx",
            form_visible=False,
            login_message="",
            general_message="",
            user_label="Servidor Teste",
        )

        self.assertEqual(status, "success")
        self.assertIn("Servidor Teste", message)

    def test_detects_fatal_credentials_error(self):
        status, message = SeapLoginBot._classify_attempt_feedback(
            current_url="https://www.seapsistema.rj.gov.br/",
            form_visible=True,
            login_message="Usuário ou senha inválidos",
            general_message="",
            user_label="",
        )

        self.assertEqual(status, "fatal_credentials")
        self.assertIn("senha", message.lower())

    def test_detects_captcha_retry_from_feedback_text(self):
        status, message = SeapLoginBot._classify_attempt_feedback(
            current_url="https://www.seapsistema.rj.gov.br/",
            form_visible=True,
            login_message="Código da imagem incorreto",
            general_message="",
            user_label="",
        )

        self.assertEqual(status, "retry_captcha")
        self.assertIn("incorreto", message.lower())

    def test_prioritizes_captcha_retry_for_ambiguous_message(self):
        status, message = SeapLoginBot._classify_attempt_feedback(
            current_url="https://www.seapsistema.rj.gov.br/",
            form_visible=True,
            login_message="Usuário correto, mas código da imagem inválido",
            general_message="",
            user_label="",
        )

        self.assertEqual(status, "retry_captcha")
        self.assertIn("imagem", message.lower())

    def test_does_not_mark_root_url_without_form_as_success(self):
        status, _ = SeapLoginBot._classify_attempt_feedback(
            current_url="https://www.seapsistema.rj.gov.br/",
            form_visible=False,
            login_message="",
            general_message="",
            user_label="",
        )

        self.assertEqual(status, "retry_captcha")

    def test_defaults_to_retry_when_form_remains_visible(self):
        status, message = SeapLoginBot._classify_attempt_feedback(
            current_url="https://www.seapsistema.rj.gov.br/",
            form_visible=True,
            login_message="",
            general_message="",
            user_label="",
        )

        self.assertEqual(status, "retry_captcha")
        self.assertIn("tela de login", message.lower())


if __name__ == "__main__":
    unittest.main()
