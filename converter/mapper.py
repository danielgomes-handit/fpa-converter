"""Chama a Claude API para propor o mapeamento coluna-a-coluna.

Usa tool use para forçar resposta estruturada em JSON, evitando parse
quebrado de texto livre.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from anthropic import Anthropic

from .schemas import ALL_STRUCTURES, StructureSpec


SYSTEM_PROMPT = """Você é um especialista em FP&A da Handit. Seu trabalho é analisar arquivos brutos de clientes (extrações de ERP, planilhas) e propor o mapeamento coluna-a-coluna para as 4 estruturas oficiais de carga do FP&A Base.

Regras de mapeamento:
1. Só mapeie colunas quando houver correspondência semântica clara. Não force mapeamentos duvidosos.
2. Para hierarquias (CC_N1..CC_N5, CONTA_N1..CONTA_N5), sugira derivação a partir de colunas com estrutura pontuada (ex.: 001.001.002).
3. Para NATUREZA do razão: se houver sinal do valor, use D para negativos e C para positivos. Se houver tipo de movimento (Entrada/Saída), use C/D.
4. Campos obrigatórios que não puderem ser mapeados devem ser marcados como gap, com justificativa.
5. Se o arquivo tem múltiplas abas, uma aba pode alimentar mais de uma estrutura (ex.: aba de departamentos alimenta Centro de Custo; aba de lançamentos alimenta Razão).
6. Para aplicações em dimensões replicadas por filial (ex.: Omie replica categorias entre SPEs), sinalize que deve haver deduplicação por código.

Retorne sempre via tool use, nunca em texto livre."""


def _build_mapping_tool() -> Dict[str, Any]:
    """Tool Anthropic para forçar retorno estruturado do mapeamento."""
    structure_ids = [s.id for s in ALL_STRUCTURES]
    return {
        "name": "propose_mapping",
        "description": (
            "Retorna o mapeamento proposto entre as colunas do arquivo do cliente "
            "e os campos das 4 estruturas do FP&A Base."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "structures": {
                    "type": "array",
                    "description": "Uma entrada por estrutura alimentada pelo arquivo",
                    "items": {
                        "type": "object",
                        "properties": {
                            "structure_id": {
                                "type": "string",
                                "enum": structure_ids,
                            },
                            "source_sheet": {
                                "type": "string",
                                "description": "Nome da aba do arquivo do cliente que alimenta esta estrutura",
                            },
                            "deduplicate_by": {
                                "type": "string",
                                "description": "Nome do campo FP&A pelo qual deduplicar antes de salvar (opcional)",
                            },
                            "field_mappings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "fpa_field": {"type": "string"},
                                        "source_column": {
                                            "type": "string",
                                            "description": "Nome EXATO da coluna no arquivo do cliente, ou vazio se for gap/derivado",
                                        },
                                        "strategy": {
                                            "type": "string",
                                            "enum": [
                                                "direct",
                                                "derived_from_dotted_code",
                                                "lookup_from_description",
                                                "constant",
                                                "abs_value",
                                                "natureza_from_sign",
                                                "natureza_from_movement_type",
                                                "gap",
                                            ],
                                            "description": (
                                                "Como preencher o campo. "
                                                "direct = copiar da coluna. "
                                                "derived_from_dotted_code = quebrar código pontuado em níveis. "
                                                "lookup_from_description = buscar código via descrição em outra aba. "
                                                "constant = valor fixo (ver 'constant_value'). "
                                                "abs_value = valor absoluto. "
                                                "natureza_from_sign = D se negativo, C se positivo. "
                                                "natureza_from_movement_type = C para Entrada, D para Saída. "
                                                "gap = deixar em branco."
                                            ),
                                        },
                                        "constant_value": {
                                            "type": "string",
                                            "description": "Valor fixo quando strategy=constant",
                                        },
                                        "notes": {
                                            "type": "string",
                                            "description": "Observações úteis (ex.: composite key, limitações, decisões)",
                                        },
                                    },
                                    "required": ["fpa_field", "strategy"],
                                },
                            },
                        },
                        "required": ["structure_id", "source_sheet", "field_mappings"],
                    },
                },
                "global_notes": {
                    "type": "string",
                    "description": "Observações gerais sobre o arquivo, decisões estruturais e alertas",
                },
            },
            "required": ["structures"],
        },
    }


def _structures_prompt() -> str:
    """Descreve as 4 estruturas FP&A em formato legível para o Claude."""
    parts = ["# Estruturas alvo do FP&A Base", ""]
    for s in ALL_STRUCTURES:
        parts.append(f"## {s.label} (id=`{s.id}`)")
        parts.append("")
        for f in s.fields:
            req = "obrigatório" if f.required else "opcional"
            fmt = f" | formato: {f.format_hint}" if f.format_hint else ""
            parts.append(f"- **{f.name}** ({req}){fmt}: {f.description}")
        parts.append("")
    return "\n".join(parts)


def propose_mapping(
    source_profile_markdown: str,
    client_context: str = "",
    api_key: str | None = None,
    model: str | None = None,
) -> Dict[str, Any]:
    """Chama Claude API e retorna o mapeamento em dict."""
    api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
    model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "4096"))

    client = Anthropic(api_key=api_key)
    tool = _build_mapping_tool()

    user_message = f"""{_structures_prompt()}

---

# Arquivo do cliente

{source_profile_markdown}

---

# Contexto adicional

{client_context or '(nenhum)'}

---

Analise o arquivo acima e proponha o mapeamento para as estruturas aplicáveis. Use a ferramenta `propose_mapping` para retornar o resultado."""

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": "propose_mapping"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "propose_mapping":
            return block.input

    raise RuntimeError(
        "Claude não retornou tool_use. Resposta bruta: " + str(response.content)
    )
