# FP&A Base Converter (MVP)

Ferramenta visual para converter arquivos brutos de clientes no layout oficial de carga do FP&A Base da Handit. Suporta arquivos estruturados (xlsx, csv), não estruturados (PDF, imagens, texto livre) e planilhas bagunçadas com múltiplas tabelas. Usa Claude API no backend.

## Tipos de arquivo suportados

| Tipo | Como é processado | Precisa OCR? |
|---|---|---|
| xlsx/csv com cabeçalho claro | pandas extrai perfil, Claude propõe mapeamento, pandas aplica | Não |
| xlsx bagunçado, múltiplas tabelas | Claude recebe perfil completo das abas e extrai registros diretamente | Não |
| PDF com texto | Claude lê o PDF via API multimodal, extrai registros | Não |
| PDF escaneado | Claude processa via API multimodal (OCR nativo do modelo) | Não (Claude faz) |
| Imagem (png, jpg, webp) | Claude processa como imagem | Não (Claude faz) |
| Texto livre (txt, md) | Claude lê o texto e extrai | Não |

A detecção do tipo é automática via `router.py`. O usuário só faz upload.

## Custo estimado por conversão

| Tipo | Input tokens | Output tokens | Custo com Sonnet 4.6 |
|---|---:|---:|---:|
| xlsx tabular estruturado | ~8k | ~2k | ~US$ 0,05 |
| PDF 5 páginas com texto | ~15k | ~4k | ~US$ 0,10 |
| PDF 20 páginas escaneado | ~50k | ~8k | ~US$ 0,25 |
| Imagem única | ~5k | ~2k | ~US$ 0,04 |

Para 100 conversões/mês de volume típico: aproximadamente US$ 10-15.

## Setup local

Pré-requisitos: Python 3.10+ e uma chave da Claude API.

```bash
cd fpa-converter
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edite .env e cole sua ANTHROPIC_API_KEY
streamlit run app.py
```

A aplicação abre em `http://localhost:8501`.

## Fluxo de uso

1. Usuário abre a ferramenta
2. Faz upload do arquivo bruto (qualquer formato suportado)
3. Informa nome do cliente e contexto (ex.: "ERP Omie, período 11-12/2025")
4. A ferramenta detecta automaticamente o tipo do arquivo e mostra a justificativa
5. Clica em "Analisar e propor mapeamento" (estruturado) ou "Extrair registros via Claude" (não estruturado)
6. Revisa o JSON retornado pelo Claude (debug opcional)
7. Clica em "Aplicar e gerar arquivos"
8. Vê preview dos 4 DataFrames com alertas de validação
9. Baixa o zip com xlsx + relatório MD

## Deploy

- **Streamlit Cloud** (grátis, ideal para MVP interno): conecta no GitHub, aponta para `app.py`, configura `ANTHROPIC_API_KEY` em Secrets
- **Railway / Render**: mesmo requirements.txt, comando de start `streamlit run app.py --server.port $PORT`
- **Docker interno Handit**: `FROM python:3.11-slim` + requirements + streamlit run

## Decisões de arquitetura

**Por que 2 caminhos e não um só?**
Mandar um xlsx de 10.000 linhas inteiro para o Claude seria caro e lento. Para arquivos estruturados, pandas resolve a leitura em milissegundos e o Claude só precisa raciocinar sobre o mapeamento (que é a parte difícil). Já para PDFs e arquivos bagunçados, não há como escapar de deixar o Claude ler o documento inteiro.

**Por que tool use em vez de resposta em texto?**
Tool use força o Claude a retornar JSON estruturado respeitando o schema. Isso elimina parsing frágil de texto livre e bugs de formatação. A tool `propose_mapping` e a tool `extract_records` têm schemas que garantem campos obrigatórios e enums.

**Por que pandas aplica o mapeamento e não o Claude?**
Aplicar o mapeamento é determinístico, tem custo zero e roda em milissegundos. Se o Claude errar na aplicação, ninguém sabe onde. Se o pandas errar, o stack trace aponta a linha exata. Separar "raciocínio" de "execução" é o padrão de sistemas de IA confiáveis.

**Por que permitir troca entre Sonnet/Opus/Haiku?**
Cada cliente/arquivo tem uma complexidade. Arquivos simples e repetitivos (planilhas Omie padronizadas) funcionam bem com Haiku e custam menos. Documentos complexos (PDF escaneado de balancete manuscrito) exigem Opus.

## Roadmap para white-label no FP&A Base

Quando for embarcar como feature nativa:

- Trocar Streamlit por componente React/Vue no frontend do FP&A
- Converter este serviço em REST (FastAPI) com endpoints `/classify`, `/analyze`, `/extract`, `/transform`, `/validate`, `/generate`
- Persistir histórico de conversões por cliente no banco do FP&A
- Reaproveitar SSO do FP&A Base
- Integrar com a API de carga do FP&A para pular o upload manual do xlsx
- Adicionar edição visual do mapeamento proposto antes de aplicar

A lógica de `converter/` � portável: funciona tanto dentro do Streamlit quanto chamada por endpoints FastAPI. Só muda a camada de apresentação.

## Limitações conhecidas (MVP)

- Sem histórico: cada conversão é independente
- Sem login: assume uso individual
- PDFs grandes (acima de 100 páginas ou 32MB) precisam ser divididos manualmente
- Edição visual do mapeamento fica como V2
- Sem integração com API do FP&A Base ainda

## Próximas iterações

- V2: histórico por cliente + edição visual do mapeamento + login
- V3: fila de processamento para arquivos grandes + multi-usuário
- V4: embed no FP&A Base com carga direta via API
