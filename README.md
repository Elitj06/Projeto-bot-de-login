# 🤖 Bot de Login SEAP-RJ v2.0

Bot automatizado para login no sistema SEAP-RJ com **stealth máximo** e **resolução rápida de captcha**.

## ✨ Tecnologias usadas

- **Camoufox**: Firefox modificado, anti-detecção no nível C++
- **CapSolver**: Resolução de captcha em 2-5 segundos via IA
- **Comportamento humano**: Digitação variável, mouse humanizado, pausas naturais
- **Python assíncrono**: Performance máxima

## 🛡️ Por que este bot é difícil de detectar?

| Característica | Bot comum | Este bot |
|---|---|---|
| navigator.webdriver | true ❌ | undefined ✅ |
| Canvas fingerprint | Padrão ❌ | Randomizado ✅ |
| WebGL fingerprint | Default ❌ | Spoofado ✅ |
| Movimento de mouse | Linear ❌ | Curvas humanas ✅ |
| Velocidade de digitação | Constante ❌ | Variável (80-220ms) ✅ |
| Pausas entre ações | Inexistentes ❌ | Naturais (0.5-2.5s) ✅ |
| Erros de digitação | Não ❌ | 5% chance + correção ✅ |
| CDP detection | Detectável ❌ | Sandboxed ✅ |

## 📋 Pré-requisitos

- Python 3.10 ou superior
- Conexão de internet
- Conta no CapSolver com saldo
- Credenciais válidas SEAP-RJ

## 🚀 Instalação

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Baixar o Firefox stealth (Camoufox)

```bash
python -m camoufox fetch
```

⚠️ **Atenção**: Esta etapa baixa ~150MB. Acontece **apenas uma vez**.

### 3. Configurar credenciais

```bash
# Renomeie .env.example para .env
cp .env.example .env

# Edite .env com seu editor favorito
notepad .env  # Windows
nano .env     # Linux/Mac
```

Preencha 3 valores:
```
CAPSOLVER_API_KEY=CAP-xxxxxxxxxxxxx
SEAP_USERNAME=seu_usuario
SEAP_PASSWORD=sua_senha
```

### 4. Executar

```bash
python main.py
```

## 📁 Estrutura do projeto

```
bot_seap_v2/
├── main.py                       # Ponto de entrada
├── config.py                     # Configurações centralizadas
├── requirements.txt              # Dependências
├── .env                          # Credenciais (você cria)
├── .env.example                  # Template
│
├── core/                         # Núcleo
│   ├── browser_manager.py        # Gerencia Camoufox
│   └── logger.py                 # Sistema de logs
│
├── captcha/                      # Captcha
│   ├── capsolver_client.py       # API CapSolver
│   ├── captcha_handler.py        # Captura e preenche
│   └── exceptions.py             # Erros customizados
│
├── automation/                   # Lógica do bot
│   └── login_bot.py              # Fluxo de login
│
├── human/                        # Simulação humana
│   └── human_actions.py          # Mouse, digitação, pausas
│
├── logs/                         # Arquivos de log (criados automaticamente)
└── captchas_capturados/          # Imagens dos captchas (debug)
```

## 🏗️ Arquitetura

O código segue princípios **SOLID**:

- **S**ingle Responsibility: Cada classe tem UMA responsabilidade
- **O**pen/Closed: Extensível sem modificar código existente
- **L**iskov Substitution: Interfaces consistentes
- **I**nterface Segregation: Métodos específicos
- **D**ependency Injection: Componentes desacoplados (testável)

## ⏱️ Tempos esperados

| Etapa | Tempo |
|---|---|
| Iniciar Camoufox | 4-6s |
| Navegar para SEAP | 2-3s |
| Preencher usuário (humano) | 3-5s |
| Pausa "pensando" | 1-2s |
| Preencher senha (humano) | 3-5s |
| Resolver captcha (CapSolver) | 2-5s |
| Preencher captcha + clicar | 2-3s |
| **TOTAL** | **17-29s** |

## 🐛 Troubleshooting

### "CAPSOLVER_API_KEY não configurada"
- Verifique se o arquivo se chama `.env` (não `.env.txt`)
- Confirme que a chave está sem espaços/aspas

### "Imagem do captcha não encontrada"
- O site pode ter mudado a estrutura
- Atualize seletores em `captcha/captcha_handler.py`

### "CapSolver API error"
- Verifique seu saldo em https://dashboard.capsolver.com
- Confirme que sua chave está correta

### Camoufox não inicia
```bash
python -m camoufox fetch  # Re-baixar o navegador
```

## 🔒 Segurança

- ⚠️ **NUNCA** envie `.env` para o GitHub (já está no .gitignore)
- ⚠️ **NUNCA** compartilhe sua chave de API
- Se a chave vazar, regenere em dashboard.capsolver.com

## 📊 Logs

Cada execução gera um log em `logs/bot_seap_TIMESTAMP.log` com:
- Timestamps de cada ação
- Decisões tomadas
- Erros detalhados (se houver)

Útil para debug e auditoria.

## 💰 Custos

- **Camoufox**: Grátis e open source
- **CapSolver**: ~USD 0.005 por captcha (~R$ 0,025)
- **1.000 captchas/mês**: ~USD 5 (~R$ 25)

## 📜 Licença

Projeto privado de Eliandro.
