# Guia passo a passo: do zero ao app no ar

Este guia é para quem nunca usou GitHub. Vamos usar o **GitHub Desktop**, que é um programa visual: você clica em botões em vez de digitar comandos. Em cerca de 30 minutos o app estará na internet.

Dividido em 4 partes:

1. Preparar o GitHub
2. Subir a pasta do projeto
3. Publicar no Streamlit Cloud
4. Atualizar o app quando quiser mudar algo

---

## Parte 1: Preparar o GitHub (10 minutos)

### 1.1. Criar conta no GitHub (pule se já tiver)

1. Abra https://github.com/signup
2. Preencha email, senha e um nome de usuário (ex.: `dgomes-handit`)
3. Confirme o email que o GitHub envia

### 1.2. Instalar GitHub Desktop

1. Abra https://desktop.github.com
2. Clique em **Download for Windows**
3. Rode o instalador `.exe` (instalação automática, sem mexer em nada)
4. Quando abrir, clique em **Sign in to GitHub.com**
5. O navegador abre, você faz login e autoriza o GitHub Desktop
6. Volte pro programa e clique em **Finish**

### 1.3. Gerar sua Anthropic API Key

Enquanto estamos configurando, aproveite para gerar a chave da API que o app vai usar:

1. Abra https://console.anthropic.com
2. Se não tiver conta, crie uma
3. Vá em **Settings > API Keys > Create Key**
4. Dê um nome tipo `fpa-converter-handit` e copie a chave que aparece (começa com `sk-ant-...`)
5. **Guarde em um lugar seguro**. A chave só aparece uma vez
6. Vá em **Settings > Limits** e defina um **Monthly spend limit** de US$ 50 (ou o que quiser) para não levar susto na fatura

---

## Parte 2: Subir a pasta do projeto para o GitHub (10 minutos)

### 2.1. Abrir o GitHub Desktop

Com o programa aberto, você vê 3 opções na tela inicial:

- Create a tutorial repository
- Clone a repository
- **Add an existing repository from your hard drive** ← é essa

### 2.2. Apontar para a pasta do projeto

1. Clique em **Add an existing repository from your hard drive**
2. Na janela que abre, clique em **Choose...**
3. Navegue até a pasta `fpa-converter` (onde estão os arquivos `app.py`, `requirements.txt`, etc.)
4. Selecione a pasta e clique em **Select Folder**
5. O GitHub Desktop vai dizer: **"This directory does not appear to be a Git repository. Would you like to create a repository here instead?"**
6. Clique no link **create a repository here**

### 2.3. Criar o repositório

Na janela que aparece:

- **Name**: `fpa-converter` (ou o nome que preferir)
- **Description**: `Conversor de arquivos para carga no FP&A Base da Handit` (opcional)
- **Local path**: já está preenchido
- **Git Ignore**: deixe como `None` (já temos um .gitignore na pasta)
- **License**: deixe como `None`

Clique em **Create Repository**.

### 2.4. Primeiro commit (salvar os arquivos)

Depois de criar, você vê a tela principal do GitHub Desktop com a lista de arquivos à esquerda.

No canto inferior esquerdo tem dois campos:

- **Summary (required)**: escreva `Versão inicial`
- **Description**: pode deixar vazio

Clique no botão azul **Commit to main**.

Pronto, os arquivos estão salvos localmente. Agora falta enviar pro GitHub (na nuvem).

### 2.5. Publicar o repositório

No topo da tela, clique em **Publish repository**.

Na janela que aparece:

- **Name**: `fpa-converter` (já vem preenchido)
- **Description**: opcional
- **Marque a caixa "Keep this code private"** (privado é o recomendado para uso interno Handit)

Clique em **Publish repository**.

Em poucos segundos seus arquivos estão no GitHub. Você pode conferir entrando em `https://github.com/SEU-USUARIO/fpa-converter` no navegador.

---

## Parte 3: Publicar no Streamlit Cloud (10 minutos)

### 3.1. Entrar no Streamlit Cloud

1. Abra https://share.streamlit.io
2. Clique em **Sign up** ou **Continue with GitHub**
3. Autorize o Streamlit Cloud a ver seus repositórios (aceita tudo)

### 3.2. Criar o app

1. Clique no botão **Create app** (canto superior direito)
2. Escolha **Deploy a public app from GitHub** (mesmo que o repositório seja privado, essa a opção)
3. Preencha:
   - **Repository**: `SEU-USUARIO/fpa-converter`
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - **App URL**: escolha um slug fácil, tipo `handit-fpa-converter`. A URL final fica `handit-fpa-converter.streamlit.app`

### 3.3. Configurar os Secrets (muito importante)

**Antes de clicar em Deploy**, clique em **Advanced settings** no final do formulário.

Em **Secrets**, cole exatamente isto (trocando os valores):

```toml
ANTHROPIC_API_KEY = "sk-ant-COLE_AQUI_A_CHAVE_QUE_VOCE_GEROU"
CLAUDE_MODEL = "claude-sonnet-4-6"
APP_PASSWORD = ""
MAX_UPLOAD_MB = 30
```

Notas:

- A `ANTHROPIC_API_KEY` é **obrigatória** (sem ela o app não funciona)
- `APP_PASSWORD` fica vazia se você não quiser senha. Se quiser limitar acesso, preencha com uma senha (ex.: `handit2026`) e distribua só para quem precisa
- `MAX_UPLOAD_MB` é o limite de tamanho de arquivo que o usuário pode anexar

### 3.4. Deploy

Clique em **Deploy!**.

Você vê uma tela de "Your app is in the oven" por 2-3 minutos. Quando terminar, o app abre sozinho.

**A URL pública** é `https://handit-fpa-converter.streamlit.app` (ou o slug que você escolheu). Essa é a URL que você compartilha com os colegas.

### 3.5. Testar

1. Abra a URL do app
2. Se configurou `APP_PASSWORD`, o app pede senha
3. Anexe um arquivo de teste (pode ser o próprio `Bases_Omie (v3).xlsx` que usamos)
4. Clique em **Converter para formato Handit**
5. Depois de 20-60 segundos, aparece o resumo e o botão de download
6. Baixe o zip e confira os arquivos

---

## Parte 4: Atualizar o app quando quiser mudar algo (5 minutos por atualização)

Depois de publicado, toda mudança que você fizer na pasta local é enviada pro GitHub via GitHub Desktop, e o Streamlit Cloud atualiza o app sozinho.

Fluxo completo de uma atualização:

1. Abra um arquivo da pasta (ex.: `app.py`) no editor que preferir (VS Code, Notepad++, até o bloco de notas serve)
2. Faça a mudança e salve
3. Abra o GitHub Desktop. Ele detecta automaticamente o que mudou e mostra em cinza/verde
4. No canto inferior esquerdo, escreva um **Summary** tipo `Ajustar limite de upload para 50MB`
5. Clique em **Commit to main**
6. No topo, clique em **Push origin** (envia pro GitHub)
7. O Streamlit Cloud detecta a mudança e reinicia o app em 1-2 minutos

Pronto, atualização no ar.

---

## Problemas comuns

### "Authentication failed" no Publish repository

Aconteceu o token de autenticação expirar. Vá em **GitHub Desktop > Preferences > Accounts > Sign out** e **Sign in** novamente.

### "Your app is in the oven" passou de 5 minutos

Algum erro no build. No Streamlit Cloud, clique em **Manage app > Logs**. O erro aparece em vermelho. Quase sempre é dependência faltando em `requirements.txt` ou erro de sintaxe em Python.

### "ANTHROPIC_API_KEY não encontrada" depois de deploy

Os secrets não foram salvos corretamente. No painel do Streamlit Cloud, vá em **Manage app > Settings > Secrets** e cole novamente os 4 valores. O app reinicia sozinho.

### Quero adicionar uma senha depois

No painel do Streamlit Cloud, vá em **Manage app > Settings > Secrets** e mude `APP_PASSWORD = ""` para `APP_PASSWORD = "minhasenha"`. Salve. O app reinicia automaticamente pedindo a senha.

### Perdi a URL do app

Entre em https://share.streamlit.io e a lista dos seus apps aparece. Clique no app para abrir.

### Quero desligar o app

No painel do Streamlit Cloud, **Manage app > Delete app**. Sem custo envolvido, é só tirar do ar.

---

## Checklist final

- [ ] Conta no GitHub criada
- [ ] GitHub Desktop instalado e logado
- [ ] Anthropic API Key gerada e guardada em local seguro
- [ ] Limite mensal da API definido em US$ 50 (ou outro valor)
- [ ] Pasta `fpa-converter` publicada no GitHub (repositório privado)
- [ ] App publicado no Streamlit Cloud
- [ ] Secrets configurados (ANTHROPIC_API_KEY, CLAUDE_MODEL, APP_PASSWORD, MAX_UPLOAD_MB)
- [ ] Testei com pelo menos 1 arquivo real
- [ ] URL pública compartilhada com o time (+ senha se configurou)
