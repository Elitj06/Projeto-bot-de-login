# Checklist — Bot SEAP-RJ: Pendências para Configuração

## Contexto
O bot já está funcional com fluxo de 2 páginas (login + filtro de vagas), CAPTCHA retry,
dashboard Flask e integração CapSolver. Roda localmente em WSL2 com IP brasileiro.
Repositório: `Elitj06/Projeto-bot-de-login` (clone local: `/tmp/bot-login-seap`)

---

## 1. CONFIGURAÇÃO DO AMBIENTE

### 1.1 Arquivo .env
- **Arquivo:** `/tmp/bot-login-seap/.env`
- **Ação:** Preencher com as credenciais reais:
  - `CAPSOLVER_API_KEY` — chave da API do CapSolver (dashboard.capsolver.com)
  - `SEAP_USERNAME` — ID Funcional (ex: 19953933)
  - `SEAP_PASSWORD` — senha do SEAP
  - `SEAP_FILTER_UNIT` — nome da unidade para filtro (opcional)
  - `SEAP_FILTER_DATE` — data para filtro (opcional, formato que o site aceita)

### 1.2 Dependências Python
- **Status:** INSTALADO ✅
- Virtualenv em `/tmp/bot-login-seap/.venv`
- Para ativar: `source /tmp/bot-login-seap/.venv/bin/activate`
- Camoufox (Firefox stealth) já baixado

---

## 2. SELETORES DO SEAP — VALIDAR NO SITE REAL

### 2.1 Página de Login (confirmados pelo relatório anterior)
- Dropdown tipo login: `select[name='tipoLogin']` ou similar
- Campo usuário: `input[id='idFuncional']` ou `input[type='text']`
- Campo senha: `input[type='password']`
- CAPTCHA imagem: `div#captcha > div`
- CAPTCHA input: `input#TextCaptcha`
- CAPTCHA refresh: `a#lnkNewCaptcha`
- Botão submit: testar todos em `SUBMIT_SELECTORS`

**AÇÃO:** Abrir `https://seapsistema.rj.gov.br/login` no navegador, inspecionar elementos
e confirmar se os seletores acima estão corretos. Se não, atualizar em:
- `automation/login_bot.py` — listas `LOGIN_TYPE_DROPDOWN_SELECTORS`, `USERNAME_SELECTORS`, etc.
- `captcha/captcha_handler.py` — listas `CAPTCHA_IMAGE_SELECTORS`, `CAPTCHA_INPUT_SELECTORS`

### 2.2 Verificação de Login (novo — nunca testado)
- **Método:** `_verify_login_success()` em `login_bot.py`
- Verificar se após login bem-sucedido a URL muda ou se fica na mesma com indicador
- Confirmar seletor `span#lblUsuario` aparece após login OK
- Se o SEAP usa ASP.NET postback, a URL pode NÃO mudar — ajustar lógica de verificação

### 2.3 Página de Filtro (FrmEventoAssociar.aspx) — NUNCA TESTADA
- **Métodos:** `_navigate_to_filter_page()`, `_fill_filter_fields()` em `login_bot.py`
- **Config:** `filter_config` em `config.py`
- **Seletores a validar no site real:**
  - Link no menu: `a[href*='FrmEventoAssociar']`
  - Dropdown unidade: `select#ddlUnidade`
  - Campo data: `input#txtData`
  - Botão pesquisar: `button#btnPesquisar`
  - CAPTCHA: deve ser o mesmo `div#captcha > div`
- **AÇÃO:** Fazer login manual, navegar para FrmEventoAssociar.aspx, inspecionar cada campo
e atualizar `FilterConfig` em `config.py` com os seletores reais

---

## 3. CAPTCHA — PROBLEMA PRINCIPAL

### 3.1 Diagnóstico atual
- CapSolver retorna texto (ex: `fc2=`, `n355`) mas SEAP rejeita com "Erro ao confirmar Imagem"
- A causa provável era extração via regex do CSS base64 → corrigido para screenshot do elemento
- Adicionado `websiteURL` no payload do CapSolver para melhor acurácia
- Adicionado retry (3 tentativas) com refresh entre elas

### 3.2 O que testar
1. Rodar o bot e verificar se `div#captcha > div` é encontrado
2. Verificar se o screenshot está capturando a imagem corretamente (salva em `captchas_capturados/`)
3. Verificar se o CapSolver está recebendo a imagem completa (não truncada)
4. Se ainda falhar, testar:
   - Trocar `module` de `"common"` para outro (ver docs CapSolver)
   - Aumentar qualidade do screenshot
   - Tentar extração direta do base64 do CSS como fallback

### 3.3 Fallback: extração do base64 inline
- **Se o screenshot não funcionar**, implementar extração do `background: url(data:image/png;base64,...)`
- **Local:** `captcha_handler.py`, método `_save_captcha_image`
- Lógica: usar `element.evaluate()` para ler o CSS `background` e extrair o base64

---

## 4. IP / INFRAESTRUTURA

### 4.1 Status
- IP alemão (Hetzner) está bloqueado pelo SEAP → `The URL you requested has been blocked`
- IP brasileiro (esta máquina WSL2) deve funcionar
- Proxy Decodo foi testado mas bloqueia `.gov.br`

### 4.2 Decisão pendente
- **Opção A:** Rodar na máquina local (esta) — funciona mas depende do PC ligado
- **Opção B:** VPS brasileira (ex: HostGator, Locaweb, Hetzner BR)
- **Opção C:** Proxy residencial brasileiro (precisa contratar)

---

## 5. PÁGINA PÓS-FILTRO — NÃO MAPEADA

### 5.1 Situação
- Após submeter filtro (unidade + data + CAPTCHA #2), não sabemos como é a tela de resultados
- A tela de resultados pode ter: lista de vagas, botão de candidatar, etc.

### 5.2 Ação necessária
1. Login manual no SEAP
2. Navegar até FrmEventoAssociar.aspx
3. Preencher filtro e submeter
4. Screenshot da tela de resultados
5. Mapear seletores: lista de vagas, botão reservar, etc.
6. Implementar em `automation/login_bot.py` ou novo módulo `automation/vaga_bot.py`

---

## 6. DASHBOARD — FUNCIONALIDADES PENDENTES

### 6.1 O que funciona
- Login de página única via dashboard (`POST /api/users/<id>/login`)
- Login de múltiplos usuários em paralelo
- Gerenciamento de usuários, proxies, logs
- Sniper engine (estrutura pronta, seletores TODO)

### 6.2 O que precisa conectar
- Botão "Fluxo Completo" no frontend chamando `POST /api/users/<id>/full-flow`
  - Endpoint já existe no backend (`dashboard/api/login.py`)
  - Falta adicionar botão/no frontend (`dashboard/templates/index.html` ou `dashboard/static/app.js`)
- Exibir resultado do segundo CAPTCHA no dashboard
- Exibir status do filtro (submetido / não submetido)

---

## 7. ARQUIVOS-CHAVE PARA O AGENTE

```
| Arquivo                              | O que fazer                          |
| ------------------------------------ | ------------------------------------ |
| .env                                 | Preencher credenciais reais          |
| automation/login_bot.py              | Validar seletores com site real      |
| captcha/captcha_handler.py           | Testar screenshot vs base64          |
| captcha/capsolver_client.py          | Ajustar module se acurácia baixa     |
| config.py                            | Atualizar FilterConfig se necessário |
| dashboard/templates/index.html       | Adicionar botão "Fluxo Completo"     |
| dashboard/static/app.js              | Conectar botão ao endpoint /full-flow|
```

---

## 8. ORDEM SUGERIDA DE EXECUÇÃO

1. Preencher `.env` com credenciais reais
2. Rodar `python main.py` e verificar se CAPTCHA #1 é resolvido corretamente
3. Se CAPTCHA falhar, diagnosticar: screenshot ok? base64 completo? acurácia do CapSolver?
4. Validar seletores da página de login no site real
5. Validar seletores da página de filtro no site real
6. Testar fluxo completo: login → filtro → CAPTCHA #2 → submit
7. Mapear tela de resultados pós-filtro
8. Implementar reserva de vaga
9. Conectar dashboard frontend ao endpoint /full-flow
