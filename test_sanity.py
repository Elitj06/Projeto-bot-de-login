"""
Teste de sanidade — verifica Playwright e Camoufox.

Roda em 3 etapas:
1. Playwright Firefox nativo
2. Camoufox (se disponível)
3. Acesso ao SEAP-RJ (verifica bloqueio de IP)

Uso: python test_sanity.py
"""
import sys
import time


def test_playwright():
    """Etapa 1: Playwright Firefox nativo."""
    print("=" * 60)
    print("ETAPA 1: Playwright Firefox nativo")
    print("=" * 60)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            start = time.time()
            browser = p.firefox.launch(headless=True, timeout=60000)
            page = browser.new_page()
            page.goto("https://www.google.com", timeout=30000)
            elapsed = time.time() - start
            print(f"✅ Firefox OK — Title: {page.title()} ({elapsed:.1f}s)")
            browser.close()
        return True
    except Exception as e:
        print(f"❌ Playwright falhou: {type(e).__name__}: {e}")
        print("   → Rodar: playwright install firefox")
        return False


def test_camoufox():
    """Etapa 2: Camoufox."""
    print()
    print("=" * 60)
    print("ETAPA 2: Camoufox (Firefox stealth)")
    print("=" * 60)
    try:
        from camoufox.sync_api import Camoufox

        start = time.time()
        with Camoufox(headless=True) as browser:
            page = browser.new_page()
            page.goto("https://www.google.com", timeout=30000)
            elapsed = time.time() - start
            print(f"✅ Camoufox OK — Title: {page.title()} ({elapsed:.1f}s)")
        return True
    except ImportError:
        print("⚠️  Camoufox não instalado — pip install camoufox")
        return False
    except Exception as e:
        print(f"⚠️  Camoufox falhou: {type(e).__name__}: {e}")
        print("   → Fallback para Playwright Firefox será usado")
        return False


def test_seap():
    """Etapa 3: Acesso ao SEAP-RJ."""
    print()
    print("=" * 60)
    print("ETAPA 3: Acesso ao SEAP-RJ")
    print("=" * 60)
    try:
        from camoufox.sync_api import Camoufox

        browser_cls = Camoufox
        use_camoufox = True
    except Exception:
        from playwright.sync_api import sync_playwright

        browser_cls = None
        use_camoufox = False

    try:
        if use_camoufox:
            with browser_cls(headless=True, locale="pt-BR") as browser:
                page = browser.new_page()
                page.goto(
                    "https://seapsistema.rj.gov.br/login",
                    timeout=30000,
                    wait_until="networkidle",
                )
                _check_seap(page)
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.firefox.launch(headless=True, timeout=60000)
                page = browser.new_page()
                page.goto(
                    "https://seapsistema.rj.gov.br/login",
                    timeout=30000,
                    wait_until="networkidle",
                )
                _check_seap(page)
                browser.close()
    except Exception as e:
        print(f"❌ Erro ao acessar SEAP: {type(e).__name__}: {e}")


def _check_seap(page):
    """Verifica se a página do SEAP carregou corretamente."""
    title = page.title()
    url = page.url
    print(f"Title: {title}")
    print(f"URL: {url}")

    if "unavailable" in title.lower() or "server unavailable" in page.locator("body").inner_html().lower():
        print("❌ SEAP bloqueou o acesso (Server Unavailable)")
        print("   → IP provavelmente fora do Brasil")
        print("   → Necessário proxy brasileiro residencial")
    else:
        inputs = page.locator("input").count()
        print(f"✅ SEAP carregou — {inputs} inputs encontrados")


def main():
    print("SEAP-RJ Bot — Teste de Sanidade")
    print()

    pw_ok = test_playwright()
    cam_ok = test_camoufox()

    if not pw_ok:
        print("\n❌ Playwright base não funciona. Resolver isso primeiro.")
        sys.exit(1)

    test_seap()

    print()
    print("=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Playwright Firefox: {'✅' if pw_ok else '❌'}")
    print(f"  Camoufox:           {'✅' if cam_ok else '⚠️ fallback'}")
    print()
    if pw_ok:
        print("  → browser_manager.py funcionará (com ou sem Camoufox)")
    print()


if __name__ == "__main__":
    main()
