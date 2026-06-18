import unittest

from captcha.exceptions import CaptchaProviderError
from captcha.provider_chain import (
    CaptchaProviderChain,
    is_plausible_captcha_text,
    normalize_captcha_text,
)


class FakeProvider:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self._result = result
        self._error = error

    async def solve_image_captcha(self, image_path):
        if self._error:
            raise self._error
        return self._result


class CaptchaProviderChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_second_provider_when_first_returns_improbable_text(self):
        chain = CaptchaProviderChain(
            providers=[
                FakeProvider("first", result="8-7=?"),
                FakeProvider("second", result="AB12C"),
            ]
        )

        result = await chain.solve_image_captcha("unused.png")

        self.assertEqual(result, "AB12C")

    async def test_raises_when_all_providers_return_improbable_text(self):
        chain = CaptchaProviderChain(
            providers=[
                FakeProvider("first", result="226"),
                FakeProvider("second", result="??"),
            ]
        )

        with self.assertRaises(CaptchaProviderError):
            await chain.solve_image_captcha("unused.png")


class CaptchaTextHelpersTests(unittest.TestCase):
    def test_normalize_removes_whitespace_and_quotes(self):
        self.assertEqual(normalize_captcha_text(' " AB 12 " '), "AB12")

    def test_plausibility_accepts_only_alnum_between_4_and_6_chars(self):
        self.assertTrue(is_plausible_captcha_text("AB12"))
        self.assertTrue(is_plausible_captcha_text("ABC123"))
        self.assertFalse(is_plausible_captcha_text("8-7=?"))
        self.assertFalse(is_plausible_captcha_text("226"))


if __name__ == "__main__":
    unittest.main()
