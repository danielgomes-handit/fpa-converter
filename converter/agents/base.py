"""Classe base para agentes especializados + Triager.

Pattern de cada agente:
    extract → post_process → validate → self_review (se houve issues) → validate

Comunicação com o LLM via `converter.llm_client` (OpenAI SDK apontando para
OpenRouter). Modelo default: anthropic/claude-opus-4.7.

Tamanhos de chunk foram aumentados dramaticamente porque o limite de output
do OpenRouter é muito maior que o Tier 1 da Anthropic. Para a grande maioria
dos arquivos, o documento inteiro vai numa só chamada (sem chunking real).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import time
from abc import ABC, abstractmethod
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List

from ..llm_client import call_with_tool, get_model
from ..router import FileKind
from ..schemas import ALL_STRUCTURES, StructureSpec, get_structure


# =============================================================================
# Utilitários compartilhados — blocos de conteúdo no formato OpenAI/OpenRouter
# =============================================================================

def _pdf_data_url(pdf_bytes: bytes) -> str:
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    return f"data:application/pdf;base64,{b64}"


def _image_data_url(path: Path) -> str:
    ext_to_media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media = ext_to_media.get(path.suffix.lower(), "image/png")
    b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{media};base64,{b64}"


def _pdf_block(filename: str, pdf_bytes: bytes) -> Dict[str, Any]:
    """Bloco de PDF no formato OpenRouter (file) compatível com Claude."""
    return {
        "type": "file",
        "file": {
            "filename": filename,
            "file_data": _pdf_data_url(pdf_bytes),
        },
    }


def _document_blocks(path: Path, file_kind: FileKind) -> List[Dict[str, Any]]:
    """Monta blocos de conteúdo para enviar ao LLM conforme o tipo de arquivo."""
    blocks: List[Dict[str, Any]] = []

    if file_kind in {FileKind.PDF_WITH_TEXT, FileKind.PDF_SCANNED}:
        blocks.append(_pdf_block(path.name, path.read_bytes()))
    elif file_kind == FileKind.IMAGE:
        blocks.append({
            "type": "image_url",
            "image_url": {"url": _image_data_url(path)},
        })
    elif file_kind == FileKind.TEXT_FREEFORM:
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks.append({"type": "text", "text": f"```\n{text}\n```"})
    elif file_kind in {FileKind.TABULAR_STRUCTURED, FileKind.TABULAR_MESSY}:
        from ..analyzer import analyze_file, profile_to_prompt
        profile = analyze_file(path)
        blocks.append({
            "type": "text",
            "text": profile_to_prompt(profile, max_cols=100),
        })
    else:
        raise ValueError(f"Tipo de arquivo não suportado: {file_kind}")

    return blocks


# =============================================================================
# Chunking: chunks GRANDES por padrão. Só divide se o documento for enorme.
# =============================================================================

# Defaults pensados para Opus 4.7 via OpenRouter (output ~32k tokens, contexto 200k).
# Para a maioria dos arquivos do dia a dia, NÃO há chunking — vai tudo de uma vez.
DEFAULT_PDF_PAGES_PER_CHUNK = int(os.environ.get("CHUNK_PDF_PAGES", "30"))
DEFAULT_TABULAR_ROWS_PER_CHUNK = int(os.environ.get("CHUNK_TABULAR_ROWS", "600"))
DEFAULT_TEXT_CHARS_PER_CHUNK = int(os.environ.get("CHUNK_TEXT_CHARS", "100000"))


def _pdf_chunks(path: Path, pages_per_chunk: int = DEFAULT_PDF_PAGES_PER_CHUNK
                ) -> List[List[Dict[str, Any]]]:
    """Divide PDF em chunks de N páginas. Só fragmenta se PDF tiver >pages_per_chunk."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return [_document_blocks(path, FileKind.PDF_WITH_TEXT)]

    reader = PdfReader(str(path))
    total_pages = len(reader.pages)

    if total_pages <= pages_per_chunk:
        return [_document_blocks(path, FileKind.PDF_WITH_TEXT)]

    chunks: List[List[Dict[str, Any]]] = []
    for start in range(0, total_pages, pages_per_chunk):
        end = min(start + pages_per_chunk, total_pages)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])

        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()

        chunks.append([
            {
                "type": "text",
                "text": (
                    f"Esta é a parte {len(chunks) + 1} do documento "
                    f"(páginas {start + 1} a {end} de {total_pages})."
                ),
            },
            _pdf_block(f"{path.stem}_p{start+1}-{end}.pdf", pdf_bytes),
        ])
    return chunks


def _tabular_chunks(path: Path, rows_per_chunk: int = DEFAULT_TABULAR_ROWS_PER_CHUNK
                    ) -> List[List[Dict[str, Any]]]:
    """Divide xlsx/csv em chunks de N linhas. Só fragmenta se planilha for muito grande."""
    import pandas as pd
    from ..analyzer import _read_csv_smart

    try:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            xls = pd.ExcelFile(path)
            sheets_data = {}
            for sheet_name in xls.sheet_names:
                try:
                    df = xls.parse(sheet_name)
                    if not df.empty and df.shape[1] > 0:
                        sheets_data[sheet_name] = df
                except Exception:
                    continue
        else:
            df = _read_csv_smart(path)
            sheets_data = {path.stem: df}
    except Exception:
        return [_document_blocks(path, FileKind.TABULAR_STRUCTURED)]

    if not sheets_data:
        return [_document_blocks(path, FileKind.TABULAR_STRUCTURED)]

    total_rows_across = sum(len(df) for df in sheets_data.values())

    # Se cabe num chunk único, usa o caminho normal (analyzer + profile_to_prompt)
    if total_rows_across <= rows_per_chunk:
        return [_document_blocks(path, FileKind.TABULAR_STRUCTURED)]

    chunks: List[List[Dict[str, Any]]] = []
    for sheet_name, df in sheets_data.items():
        sheet_total = len(df)
        cols = list(df.columns)

        for start in range(0, sheet_total, rows_per_chunk):
            end = min(start + rows_per_chunk, sheet_total)
            chunk_df = df.iloc[start:end]
            try:
                md_table = chunk_df.to_markdown(index=False)
            except (ImportError, ModuleNotFoundError):
                md_table = chunk_df.to_csv(index=False)
            except Exception:
                md_table = chunk_df.to_string(index=False)

            preamble_txt = (
                f"# Arquivo: `{path.name}`\n"
                f"## Aba: `{sheet_name}` — linhas {start + 1} a {end} de {sheet_total}\n"
                f"### Colunas: {cols}\n\n"
            )
            chunks.append([{
                "type": "text",
                "text": preamble_txt + md_table,
            }])

    return chunks if chunks else [_document_blocks(path, FileKind.TABULAR_STRUCTURED)]


def _text_chunks(path: Path, chars_per_chunk: int = DEFAULT_TEXT_CHARS_PER_CHUNK
                 ) -> List[List[Dict[str, Any]]]:
    """Divide texto em chunks de N chars. Só fragmenta se texto for muito grande."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= chars_per_chunk:
        return [[{"type": "text", "text": f"```\n{text}\n```"}]]

    chunks: List[List[Dict[str, Any]]] = []
    total = len(text)
    for start in range(0, total, chars_per_chunk):
        end = min(start + chars_per_chunk, total)
        chunks.append([{
            "type": "text",
            "text": (
                f"Parte {len(chunks) + 1} (chars {start + 1}-{end} de {total}):\n\n"
                f"```\n{text[start:end]}\n```"
            ),
        }])
    return chunks


def _document_chunks(
    path: Path,
    file_kind: FileKind,
    pdf_pages_per_chunk: int = DEFAULT_PDF_PAGES_PER_CHUNK,
    tabular_rows_per_chunk: int = DEFAULT_TABULAR_ROWS_PER_CHUNK,
    text_chars_per_chunk: int = DEFAULT_TEXT_CHARS_PER_CHUNK,
) -> List[List[Dict[str, Any]]]:
    """Retorna lista de chunks (cada chunk é uma lista de blocos para o LLM)."""
    if file_kind in {FileKind.PDF_WITH_TEXT, FileKind.PDF_SCANNED}:
        return _pdf_chunks(path, pdf_pages_per_chunk)
    if file_kind in {FileKind.TABULAR_STRUCTURED, FileKind.TABULAR_MESSY}:
        return _tabular_chunks(path, tabular_rows_per_chunk)
    if file_kind == FileKind.TEXT_FREEFORM:
        return _text_chunks(path, text_chars_per_chunk)
    return [_document_blocks(path, file_kind)]


# =============================================================================
# Parser CSV (LLM retorna CSV em string para economizar tokens)
# =============================================================================

def _parse_csv_records(csv_text: str, structure: StructureSpec) -> List[Dict[str, str]]:
    """Parseia string CSV em lista de dicts.

    Tolera diferenças de case nos nomes de coluna e ignora colunas
    que não pertencem ao schema da estrutura.
    """
    if not csv_text or not csv_text.strip():
        return []

    all_fields = {f.upper(): f for f in structure.all_fields}
    records: List[Dict[str, str]] = []

    try:
        reader = csv.DictReader(StringIO(csv_text.strip()))
        for row in reader:
            if not row:
                continue
            rec: Dict[str, str] = {}
            for k, v in row.items():
                if k is None:
                    continue
                k_norm = str(k).strip().upper()
                if k_norm in all_fields:
                    original_name = all_fields[k_norm]
                    rec[original_name] = str(v or "").strip()
            if rec:
                records.append(rec)
    except Exception:
        return []

    return records


# =============================================================================
# Classe base Agent
# =============================================================================

class Agent(ABC):
    """Agente especializado em uma estrutura do FP&A Base."""

    structure_id: str = ""

    def __init__(
        self,
        source_path: str | Path,
        file_kind: FileKind,
        client_context: str = "",
        api_key: str | None = None,
        model: str | None = None,
        progress_callback=None,
    ):
        self.source_path = Path(source_path)
        self.file_kind = file_kind
        self.client_context = client_context
        # Compatibilidade com chamadas antigas que passam api_key explicitamente
        if api_key:
            os.environ.setdefault("OPENROUTER_API_KEY", api_key)
        self.model = model or get_model()
        self.max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "32000"))
        self.log: List[Dict[str, Any]] = []
        self.progress_callback = progress_callback

    def _notify(self, label: str):
        if self.progress_callback:
            self.progress_callback(label)

    # ---------------------------------------------------------------------
    # A implementar por cada subclasse
    # ---------------------------------------------------------------------

    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt focado nesta estrutura específica."""

    @abstractmethod
    def extract_instructions(self) -> str:
        """Instruções adicionais para a extração (além do system)."""

    def custom_validations(self, records: List[Dict[str, Any]]) -> List[str]:
        return []

    def key_field(self) -> str:
        return ""

    def post_process(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return records

    def extra_chunk_instruction(self) -> str:
        return ""

    def schema_fields(self) -> List[str]:
        return list(self.structure.all_fields)

    # ---------------------------------------------------------------------
    # Pipeline
    # ---------------------------------------------------------------------

    @property
    def structure(self):
        return get_structure(self.structure_id)

    def tool_schema(self) -> Dict[str, Any]:
        s = self.structure
        fields_for_schema = self.schema_fields()
        required_fields = [f for f in s.required_fields if f in fields_for_schema]
        return {
            "name": f"submit_{self.structure_id}",
            "description": f"Submete registros de {s.label} em formato CSV.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "records_csv": {
                        "type": "string",
                        "description": (
                            f"String CSV com header na primeira linha e um registro "
                            f"por linha. Separador: vírgula. "
                            f"Colunas disponíveis (na ordem): {','.join(fields_for_schema)}. "
                            f"Colunas obrigatórias que devem sempre ter valor: "
                            f"{','.join(required_fields)}. "
                            f"Use aspas duplas em valores que contenham vírgula, quebra de "
                            f"linha ou aspas. Deixe células vazias quando o documento não "
                            f"fornecer o dado (não invente). Exemplo de formato:\\n"
                            f"COL1,COL2,COL3\\nvalor1,\\\"valor com, vírgula\\\",valor3"
                        ),
                    },
                    "notes": {"type": "string"},
                },
                "required": ["records_csv"],
            },
        }

    def _call_llm(self, user_content: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Chama o LLM (Opus via OpenRouter) e parseia a resposta CSV."""
        tool = self.tool_schema()
        result = call_with_tool(
            system=self.system_prompt(),
            user_content=user_content,
            tool_schema=tool,
            model=self.model,
            max_tokens=self.max_tokens,
            stream=True,
        )

        tool_input = result.get("tool_input", {}) or {}
        csv_text = str(tool_input.get("records_csv", "") or "")
        records = _parse_csv_records(csv_text, self.structure)

        return {
            "records": records,
            "notes": tool_input.get("notes", ""),
            "_csv_preview": csv_text[:500],
            "_csv_length": len(csv_text),
            "_meta": result.get("meta", {}),
        }

    def extract(self) -> List[Dict[str, Any]]:
        """Extração via chunks (na maioria dos casos, só 1 chunk = arquivo inteiro)."""
        chunks = _document_chunks(self.source_path, self.file_kind)
        total_chunks = len(chunks)

        all_records: List[Dict[str, Any]] = []
        seen_keys: set = set()
        kf = self.key_field()
        rate_wait = int(os.environ.get("CLAUDE_RATE_LIMIT_WAIT_SECONDS", "0"))

        required_fields = self.structure.required_fields

        for i, chunk_blocks in enumerate(chunks, 1):
            if total_chunks > 1:
                self._notify(
                    f"Extraindo {self.structure.label} — parte {i}/{total_chunks}..."
                )
            else:
                self._notify(
                    f"Extraindo {self.structure.label}... (pode levar 1-3 min)"
                )

            preamble = (
                f"Você vai extrair APENAS registros da estrutura "
                f"**{self.structure.label}** "
                + (f"da parte {i}/{total_chunks} do documento" if total_chunks > 1
                   else "deste documento")
                + ". Outras estruturas serão processadas por outros agentes.\n\n"
                + (
                    f"**Parte {i} de {total_chunks}**: extraia o que estiver visível "
                    f"nesta parte. Registros duplicados serão deduplicados depois.\n\n"
                    if total_chunks > 1 else ""
                )
                + "**FORMATO DE RESPOSTA (CRÍTICO):**\n"
                "Retorne os registros em CSV (Comma-Separated Values) dentro do "
                "campo `records_csv`. NÃO use JSON/objeto. O CSV é eficiente em "
                "tokens, permitindo extrair centenas de registros de uma vez.\n\n"
                f"- Primeira linha: header com os nomes das colunas separados por vírgula.\n"
                f"- Uma linha por registro.\n"
                f"- Deixe células VAZIAS quando o documento não fornecer o valor. "
                f"Ex.: `1.1.1.01,,Caixa,D`\n"
                f"- Use aspas duplas em valores com vírgula ou quebra de linha. "
                f"Ex.: `1010,,\"Caixa, Agência Centro\",D`\n"
                f"- Campos obrigatórios que DEVEM sempre ter valor: "
                f"{', '.join(required_fields)}\n\n"
                f"{self.extract_instructions()}\n\n"
                + (f"{self.extra_chunk_instruction()}\n\n"
                   if self.extra_chunk_instruction() else "")
                + f"Contexto do cliente: {self.client_context or '(nenhum)'}\n\n"
                + f"Use a ferramenta `submit_{self.structure_id}` com `records_csv` preenchido."
            )

            content = [{"type": "text", "text": preamble}] + chunk_blocks

            try:
                result = self._call_llm(content)
            except Exception as e:
                self.log.append({
                    "step": f"extract_chunk_{i}",
                    "error": str(e),
                    "chunk_index": i,
                    "total_chunks": total_chunks,
                })
                if i < total_chunks and rate_wait > 0:
                    self._notify(
                        f"Erro no chunk {i}. Aguardando {rate_wait}s e tentando chunk {i+1}..."
                    )
                    time.sleep(rate_wait)
                continue

            records = result.get("records", [])

            new_records: List[Dict[str, Any]] = []
            for rec in records:
                if kf:
                    key_val = str(rec.get(kf, "")).strip()
                    if key_val:
                        if key_val in seen_keys:
                            continue
                        seen_keys.add(key_val)
                new_records.append(rec)

            all_records.extend(new_records)

            self.log.append({
                "step": f"extract_chunk_{i}" if total_chunks > 1 else "extract",
                "chunk_index": i,
                "total_chunks": total_chunks,
                "records_from_chunk": len(records),
                "records_after_dedup": len(new_records),
                "cumulative_records": len(all_records),
                "meta": result.get("_meta", {}),
                "notes": result.get("notes", ""),
            })

            if i < total_chunks and rate_wait > 0:
                self._notify(
                    f"Chunk {i}/{total_chunks} OK ({len(all_records)} registros). "
                    f"Aguardando {rate_wait}s..."
                )
                time.sleep(rate_wait)

        return all_records

    def validate(self, records: List[Dict[str, Any]]) -> List[str]:
        issues: List[str] = []

        if not records:
            issues.append("Nenhum registro foi extraído.")
            return issues

        for i, rec in enumerate(records, 1):
            for field in self.structure.required_fields:
                val = str(rec.get(field, "")).strip()
                if not val:
                    issues.append(f"Registro #{i}: campo obrigatório `{field}` está vazio.")

        kf = self.key_field()
        if kf:
            seen: Dict[str, int] = {}
            for i, rec in enumerate(records, 1):
                val = str(rec.get(kf, "")).strip()
                if not val:
                    continue
                if val in seen:
                    issues.append(
                        f"Registros #{seen[val]} e #{i}: `{kf}` duplicado (valor `{val}`)."
                    )
                else:
                    seen[val] = i

        issues.extend(self.custom_validations(records))
        return issues

    def self_review(
        self,
        records: List[Dict[str, Any]],
        issues: List[str],
    ) -> List[Dict[str, Any]]:
        if not issues:
            return records

        MAX_RECORDS_FOR_REVIEW = int(
            os.environ.get("CLAUDE_SELF_REVIEW_MAX_RECORDS", "200")
        )
        if len(records) > MAX_RECORDS_FOR_REVIEW:
            self.log.append({
                "step": "self_review_skipped",
                "reason": f"{len(records)} registros > limite {MAX_RECORDS_FOR_REVIEW}",
                "issues_count": len(issues),
            })
            return records

        self._notify(f"Revisando {self.structure.label} ({len(issues)} alertas)...")
        records_json = json.dumps(records, indent=2, ensure_ascii=False)
        issues_text = "\n".join(f"- {i}" for i in issues[:25])

        review_prompt = (
            f"Você extraiu estes registros de {self.structure.label}:\n\n"
            f"```json\n{records_json[:30000]}\n```\n\n"
            f"A validação automática detectou problemas:\n\n{issues_text}\n\n"
            f"Revise os registros e corrija o que for possível. Se algum problema "
            f"for limitação real do documento original, mantenha como está e "
            f"registre em `notes`. NÃO invente dados.\n\n"
            f"**FORMATO DE RESPOSTA**: retorne em CSV via `records_csv`. "
            f"Header na 1ª linha + uma linha por registro. Células vazias quando "
            f"não houver dado.\n\n"
            f"Retorne a versão revisada usando `submit_{self.structure_id}`."
        )

        content = [{"type": "text", "text": review_prompt}]

        try:
            result = self._call_llm(content)
        except Exception as e:
            self.log.append({
                "step": "self_review_error",
                "error": str(e),
                "issues_count": len(issues),
            })
            return records

        refined = result.get("records", records)

        self.log.append({
            "step": "self_review",
            "records_before": len(records),
            "records_after": len(refined),
            "issues_found": len(issues),
            "meta": result.get("_meta", {}),
            "notes": result.get("notes", ""),
        })

        return refined

    def run(self) -> Dict[str, Any]:
        records = self.extract()

        records_before_post = len(records)
        records = self.post_process(records)
        if len(records) != records_before_post:
            self.log.append({
                "step": "post_process",
                "records_before": records_before_post,
                "records_after": len(records),
            })

        issues = self.validate(records)

        if issues:
            records = self.self_review(records, issues)
            records = self.post_process(records)
            issues = self.validate(records)

        all_fields = self.structure.all_fields
        normalized = [
            {f: str(rec.get(f, "")).strip() for f in all_fields}
            for rec in records
        ]

        return {
            "structure_id": self.structure_id,
            "records": normalized,
            "remaining_issues": issues,
            "log": self.log,
        }


# =============================================================================
# Triager: identifica quais estruturas estão presentes no documento
# =============================================================================

TRIAGER_SYSTEM = """Você é um triador de documentos financeiros da Handit. Dado um \
documento, sua missão é identificar quais das 4 estruturas do FP&A Base estão \
presentes nele.

As 4 estruturas possíveis são:

- **estrutura_empresarial**: lista de empresas/filiais. Campos típicos: filial, empresa, CNPJ.
- **centro_de_custo**: lista de centros de custo. Campos típicos: código CC, descrição, hierarquia (departamento, gerência, diretoria).
- **plano_de_contas**: lista de contas contábeis. Campos típicos: código contábil, descrição da conta, natureza (D/C), hierarquia DRE.
- **razao_contabil**: lançamentos contábeis ou movimentos. Campos típicos: data, valor, débito/crédito, histórico.

Um mesmo documento pode ter várias estruturas (ex.: extração Omie com CCs + contas + lançamentos).
Outros podem ter apenas uma (ex.: PDF só de Plano de Contas).

Seja conservador: só inclua uma estrutura se houver evidência clara no documento."""


class Triager:
    """Identifica quais estruturas FP&A estão presentes num documento."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        if api_key:
            os.environ.setdefault("OPENROUTER_API_KEY", api_key)
        self.model = model or get_model()

    def _tool_schema(self) -> Dict[str, Any]:
        structure_ids = [s.id for s in ALL_STRUCTURES]
        return {
            "name": "submit_triage",
            "description": (
                "Retorna a lista de estruturas FP&A Base identificadas no documento."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "structures_present": {
                        "type": "array",
                        "description": "Lista de IDs das estruturas presentes no documento.",
                        "items": {"type": "string", "enum": structure_ids},
                    },
                    "primary_structure": {
                        "type": "string",
                        "enum": structure_ids,
                        "description": "Estrutura principal/dominante do documento.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explicação curta de como identificou as estruturas.",
                    },
                },
                "required": ["structures_present", "reasoning"],
            },
        }

    def classify(
        self,
        source_path: str | Path,
        file_kind: FileKind,
        client_context: str = "",
    ) -> Dict[str, Any]:
        source_path = Path(source_path)
        doc_blocks = _document_blocks(source_path, file_kind)
        preamble = (
            "Analise o documento abaixo e identifique quais das 4 estruturas do "
            "FP&A Base estão presentes. Use a ferramenta `submit_triage` para retornar.\n\n"
            f"Contexto adicional: {client_context or '(nenhum)'}"
        )

        content = [{"type": "text", "text": preamble}] + doc_blocks
        tool = self._tool_schema()

        try:
            result = call_with_tool(
                system=TRIAGER_SYSTEM,
                user_content=content,
                tool_schema=tool,
                model=self.model,
                max_tokens=2048,
                stream=False,
            )
        except Exception:
            return {"structures_present": [], "primary_structure": "", "reasoning": ""}

        tool_input = result.get("tool_input", {}) or {}
        return {
            "structures_present": tool_input.get("structures_present", []),
            "primary_structure": tool_input.get("primary_structure", ""),
            "reasoning": tool_input.get("reasoning", ""),
        }
