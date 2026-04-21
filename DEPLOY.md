# Guia de Deploy: FP&A Base Converter na Web

Este guia mostra como publicar o MVP Streamlit na internet, com URL pública, sem precisar de servidor próprio. Tempo total: aproximadamente 30 minutos.

## Opção recomendada: Streamlit Community Cloud

**Vantagens:**
- Grátis para apps públicos
- Deploy automático quando você faz push no GitHub
- SSL automático (HTTPS)
- Gerenciamento seguro de secrets (API keys não ficam no código)
- Logs acessíveis no painel

**Limitações:**
- 1 GB de RAM por app (suficiente para o nosso caso)
- App dorme após 7 dias sem acesso (acorda em 30s)
- Domínio padrão é `app-name.streamlit.app` (para domínio próprio, veja alternativas adiante)

---

## Passo a passo

### 1. Criar repositório no GitHub

```bash
cd fpa-converter
git init
git add .
git commit -m "FP&A Base Converter MVP"
git branch -M main
```

Crie um repositório novo no GitHub (pode ser privado) e:

```bash
git remote add origin https://github.com/SEU-USUARIO/fpa-converter.git
git push -u origin main
```

### 2. Gerar uma Anthropic API Key

Entre em https://console.anthropic.com, crie uma workspace "Handit - FP&A Converter" e gere uma API Key. **Defina um limite de gasto mensal** (por exemplo US$ 50) na aba Settings > Limits para evitar surpresas.

### 3. Deploy no Streamlit Community Cloud

1. Acesse https://share.streamlit.io e entre com sua conta GitHub
2. Clique em **New app**
3. Preencha:
   - Repository: `SEU-USUARIO/fpa-converter`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: escolha um slug (ex.: `handit-fpa-converter`)
4. Antes de clicar em **Deploy**, abra **Advanced settings** e cole em **Secrets**:

```toml
# Anthropic API Key do passo 2
ANTHROPIC_API_KEY = "sk-ant-..."

# Modelo padrão
CLAUDE_MODEL = "claude-sonnet-4-6"

# Senha de acesso simples (opcional, deixe vazio para desabilitar)
APP_PASSWORD = "handit2026"

# Limite de tamanho de upload em MB
MAX_UPLOAD_MB = 30
```

5. Clique em **Deploy**. O build leva 2-3 minutos.

Pronto. A URL pública estará em `https://handit-fpa-converter.streamlit.app`.

### 4. Testar

- Abra a URL pública
- Se configurou `APP_PASSWORD`, o app pede a senha antes de permitir uso
- Faça upload de um arquivo de teste e execute a conversão
- Confira no dashboard da Anthropic que os tokens foram consumidos

---

## Hardening para uso público

Mesmo sendo "web pública", algumas proteções mínimas evitam dor de cabeça:

### Senha de acesso (já incluída)

O `app.py` tem um gate de senha simples via `APP_PASSWORD`. Mude a senha trimestralmente e distribua só para quem precisa.

### Limite de tamanho de upload

Configurado via `MAX_UPLOAD_MB` em secrets. Padrão: 30MB. Streamlit também tem limite interno de 200MB que pode ser ajustado em `.streamlit/config.toml`.

### Limite de gasto da API

Configure na Anthropic:
- **Settings > Limits > Monthly spend limit**: defina um teto mensal (ex.: US$ 50)
- **Settings > Alerts**: email quando gastar 80% do limite

### Monitoramento

Streamlit Cloud mostra logs em tempo real. Para cada conversão, o app loga tipo de arquivo, tempo de processamento e sucesso/erro. Use isso para ajustar custos.

---

## Alternativas (se Streamlit Cloud não atender)

### Railway

Melhor se você quer domínio próprio (ex.: `fpa-converter.handit.com.br\) e precisa de mais RAM/CPU.

**Setup:**
1. Crie conta em https://railway.app
2. New Project > Deploy from GitHub repo
3. Adicione variáveis de ambiente (mesmas do secrets.toml acima)
4. Em Settings, ajuste o start command:
   ```
   streamlit run app.py --server.port $PORT --server.address 0.0.0.0
   ```
5. Em Networking, gere um domínio público e (opcional) aponte CNAME do seu domínio

**Custo:** US$ 5-10/mês dependendo do uso.

### Render

Similar ao Railway, com plano gratuito com limitações.

### VPS próprio (DigitalOcean, Hetzner, AWS Lightsail)

Para controle total ou se a Handit tiver infra própria. Setup envolve Docker, nginx e certificado SSL. Mais trabalho, menos indicado para MVP.

---

## Domínio customizado (opcional)

Com Railway ou VPS, você aponta um CNAME do domínio da Handit para o app:

```
fpa-converter.handit.com.br  CNAME  seu-app.up.railway.app
```

Streamlit Cloud **não** suporta domínio customizado no plano gratuito.

---

## Atualizações futuras

Com Streamlit Cloud, basta fazer `git push` que o deploy é automático:

```bash
# No seu projeto local, após uma mudança
git add .
git commit -m "feat: suporte a XLS antigo"
git push
```

O app reinicia sozinho em 1-2 minutos. Logs aparecem no painel do Streamlit Cloud.

---

## Checklist antes de divulgar o link

- [ ] API key da Anthropic tem limite mensal definido
- [ ] APP_PASSWORD configurada e compartilhada só com quem precisa
- [ ] Testei ao menos 1 xlsx estruturado (caminho tabular)
- [ ] Testei ao menos 1 PDF (caminho multimodal)
- [ ] Logs do Streamlit Cloud não estão mostrando erros
- [ ] Dashboard da Anthropic confirma consumo dentro do esperado
- [ ] Documentei a URL + senha num lugar acessível para o time

---

## Troubleshooting

**"App is in the oven" por mais de 5 minutos:**
Problema no build. Abra **Manage app > Logs** e veja o erro. Geralmente é dependência faltando no `requirements.txt`.

**"ModuleNotFoundError":**
Alguma dependência não está no `requirements.txt`. Adicione e faça push.

**App dorme muito rápido:**
Streamlit Cloud coloca apps em sleep após 7 dias sem acesso. Se for crítico, considere Railway.

**"Error 413: Request Entity Too Large":**
Upload maior que o limite. Ajuste `MAX_UPLOAD_MB` nos secrets e em `.streamlit/config.toml`.

**Custos da API crescendo muito:**
Vá em https://console.anthropic.com/dashboard, veja quais requisições estão consumindo mais. Provavelmente PDFs muito longos. Considere limitar o tamanho máximo ou avisar o usuário do custo estimado antes de processar.
