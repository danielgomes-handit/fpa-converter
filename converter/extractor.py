"""Extração direta de registros via Claude multimodal.

Usado para arquivos não estruturados (PDF, imagem, xlsx bagunçado, texto livre).
Diferente do mapper.py (que só propõe o mapeamento de colunas), aqui o Claude
recebe o documento inteiro e retorna as linhas já no formato FP&A Base.
"""

import base64
import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from anthropic import Anthropic

from .router import FileKind
from .schemas import ALL_STRUCTURES, get_structure


SYSTEM_PROMPT_EXTRACTION = """Você é um especialista em FP&A da Handit. Seu trabalho é extrair dados financeiros de documentos não estruturados (PDFs, imagens, planilhas bagunçadas) e retorná-los no formato oficial das 4 estruturas de carga do FP&A Base.

Regras de extração:
1. Só extraia dados que estejam explicitamente no documento. Não invente valores.
2. Para valores monetários, retorne sempre positivo e use campo NATUREZA_LANCAMENTO para indicar D (Devedora) ou C (Credora).
3. Datas devem estar no formato DD/MM/AAAA.
4. Para campos obrigatórios que não aparecem no documento, deixe em branco e registre no campo global_notes.
5. Se o documento contém dados de múltiplas estruturas (ex.: um PDF com balanço e razão), extraia cada uma separadamente.
6. Preserve o texto original de descrições e históricos, sem reformular.
7. Para documentos longos com centenas de lançamentos, extraia todos mesmo assim.

Retorne sempre via tool use."""


def _build_extraction_tool() -> Dict[str, Any]:
    structure_ids = [s.id for s in ALL_STRUCTURES]

    record_items_schema = {}
    for s in ALL_STRUCTURES:
        record_items_schema[s.id] = {
            "type": "array",
            "description": f"Registros da estrutura {s.label}",
            "items": {
                "type": "object",
                "properties": {f.name: {"type": "string"} for f in s.fields},
            },
        }

    return {
        "name": "extract_records",
        "description": (
            "Extrai registros do documento e retorna organizados por estrutura FP&A Base."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "records_by_structure": {
                    "type": "object",
                    "properties": record_items_schema,
                    "description": (
                        "Chaves: " + ", ".join(structure_ids) + ". "
                        "Inclua só as estruturas presentes no documento."
                    ),
                },
                "global_notes": {
                    "type": "string",
                    "description": "Observações, gaps de campos obrigatórios e alertas",
                },
                "detected_period": {
                    "type": "string",
                    "description": "Período dos dados quando identificável (ex.: '11/2025 a 12/2025')",
                },
            },
            "required": ["records_by_structure"],
        },
    }


def _structures_prompt_compact() -> str:
    parts = ["# Estruturas alvo", ""]
    for s in ALL_STRUCTURES:
        fields_summary = []
        for f in s.fields:
            tag = "*" if f.required else ""
            fmt = f" ({f.format_hint})" if f.format_hint else ""
            fields_summary.append(f"{f.name}{tag}{fmt}")
        parts.append(f"**{s.label}** (`{s.id}`): {', '.join(fields_summary)}")
        parts.append("")
    parts.append("*Campos marcados com asterisco são obrigatórios.*")
    return "\n".join(parts)


def _encode_pdf_base64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def _encode_image_base64(path: Path) -> Dict[str, str]:
    """Retorna dict com media_type e data base64 para envio como image block."""
    ext_to_media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = ext_to_media.get(path.suffix.lower(), "image/png")
    return {
        "media_type": media_type,
        "data": base64.standard_b64encode(path.read_bytes()).decode("utf-8"),
    }


def extract_records(
    source_path: str | Path,
    file_kind: FileKind,
    client_context: str = "",
    api_key: str | None = None,
    model: str | None = None,
) -> Dict[str, Any]:
    """Extrai registros de um arquivo não estruturado e retorna dict pronto para conversão em DataFrame."""
    api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "8192"))

    client = Anthropic(api_key=api_key)
    tool = _build_extraction_tool()
    path = Path(source_path)

    # Monta o content do user message conforme o tipo de arquivo
    content_blocks: List[Dict[str, Any]] = []
    preamble = f"""{_structures_prompt_compact()}

---

# Contexto adicional do cliente

{client_context or '(nenhum)'}

---

# Instruções

Analise o documento abaixo e extraia todos os registros financeiros para as estruturas aplicáveis. Use a ferramenta `extract_records`."""

    content_blocks.append({"type": "text", "text": preamble})

    if file_kind in {FileKind.PDF_WITH_TEXT, FileKind.PDF_SCANNED}:
        content_blocks.append(
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": _encode_pdf_base64(path),
                },
            }
        )
    elif file_kind == FileKind.IMAGE:
        img = _encode_image_base64(path)
        content_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"],
                },
            }
        )
    elif file_kind == FileKind.TEXT_FREEFORM:
        text = path.read_text(encoding="utf-8", errors="replace")
        content_blocks.append({"type": "text", "text": f"```\n{text}\n```"})
    elif file_kind == FileKind.TABULAR_MESSY:
        # Envia todas as abas como texto markdown
        from .analyzer import analyze_file, profile_to_prompt

        profile = analyze_file(path)
        content_blocks.append({"type": "text", "text": profile_to_prompt(profile, max_cols=100)})
    else:
        raise ValueError(f"Tipo de arquivo não suportado para extração direta: {file_kind}")

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT_EXTRACTION,
        tools=[tool],
        tool_choice={"type": "tool", "name": "extract_records"},
        messages=[{"role": "user", "content": content_blocks}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_records":
            return block.input

    raise RuntimeError("Claude não retornou tool_use para extração.")


def extraction_to_dataframes(extraction: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """Converte o resultado da extração em DataFrames alinhados com os schemas."""
    results: Dict[str, pd.DataFrame] = {}
    records_by_structure = extraction.get("records_by_structure", {})

    for structure_id, records in records_by_structure.items():
        if not records:
            continue
        structure = get_structure(structure_id)
        df = pd.DataFrame(records)
        # Garantir ordem e presença de todos os campos
        for field_name in structure.all_fields:
            if field_name not in df.columns:
                df[field_name] = ""
        df = df[structure.all_fields]
        results[structure_id] = df

    return results
