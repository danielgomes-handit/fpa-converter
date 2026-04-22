"""Classe base para agentes especializados + Triager.

Pattern de cada agente:
    extract → validate → self_review (se houve issues) → validate novamente

O Triager identifica quais estruturas FP&A Base estão presentes num documento
para que o orchestrator só acione os agentes relevantes.
"""

from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

from anthropic import Anthropic

from ..router import FileKind
from ..schemas import ALL_STRUCTURES, get_structure


# =============================================================================
# Utilitários compartilhados
# =============================================================================

def _encode_pdf_base64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def _encode_image_base64(path: Path) -> Dict[str, str]:
    ext_to_media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return {
        "media_type": ext_to_media.get(path.suffix.lower(), "image/png"),
        "data": base64.standard_b64encode(path.read_bytes()).decode("utf-8"),
    }


def _document_blocks(path: Path, file_kind: FileKind) -> List[Dict[str, Any]]:
    """Monta blocks de conteúdo para enviar ao Claude conforme o tipo de arquivo."""
    blocks: List[Dict[str, Any]] = []

    if file_kind in {FileKind.PDF_WITH_TEXT, FileKind.PDF_SCANNED}:
        blocks.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": _encode_pdf_base64(path),
            },
        })
    elif file_kind == FileKind.IMAGE:
        img = _encode_image_base64(path)
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            },
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
# Classe base Agent
# =============================================================================

class Agent(ABC):
    """Agente especializado em uma estrutura do FP&A Base.

    Cada agente executa o pipeline:
        1. extract: extração focada na sua estrutura
        2. validate: validações específicas (retorna lista de issues)
        3. self_review: se há issues, pede ao Claude para refinar
        4. validate novamente: confere se as correções funcionaram
    """

    structure_id: str = ""  # sobrescrito pela subclasse

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
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "16384"))
        self.timeout = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "180"))
        # timeout=180 = 3 minutos por chamada. Se passar, lança exceção.
        self.client = Anthropic(api_key=self.api_key, timeout=self.timeout)
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
        """Validações adicionais além das básicas. Override opcional."""
        return []

    def key_field(self) -> str:
        """Campo chave para detectar duplicatas."""
        return ""

    # ---------------------------------------------------------------------
    # Pipeline
    # ---------------------------------------------------------------------

    @property
    def structure(self):
        return get_structure(self.structure_id)

    def tool_schema(self) -> Dict[str, Any]:
        """Schema enxuto: só os nomes dos campos, sem descrições (economiza tokens)."""
        s = self.structure
        return {
            "name": f"submit_{self.structure_id}",
            "description": f"Submete registros de {s.label}.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                f.name: {"type": "string"}
                                for f in s.fields
                            },
                        },
                    },
                    "notes": {"type": "string"},
                },
                "required": ["records"],
            },
        }

    def _call_claude(self, user_content: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Chama Claude com streaming e retorna o tool_use input."""
        tool = self.tool_schema()
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt(),
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            final = stream.get_final_message()

        for block in final.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                result = dict(block.input)
                result["_meta"] = {
                    "stop_reason": final.stop_reason,
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                }
                return result
        return {"records": [], "_meta": {"stop_reason": "no_tool_use"}}

    def extract(self) -> List[Dict[str, Any]]:
        """Primeira extração focada na estrutura."""
        self._notify(f"Extraindo {self.structure.label}... (pode levar 1-3 min)")
        doc_blocks = _document_blocks(self.source_path, self.file_kind)

        required_fields = self.structure.required_fields
        preamble = (
            f"Você vai extrair APENAS registros da estrutura **{self.structure.label}** "
            f"deste documento. Outras estruturas serão processadas por outros agentes, "
            f"não se preocupe com elas.\n\n"
            f"**ECONOMIA DE TOKENS (IMPORTANTE):**\n"
            f"- OMITA campos sem valor no JSON. Só inclua as chaves que têm dado real.\n"
            f"- Campos obrigatórios que DEVEM sempre aparecer: {', '.join(required_fields)}\n"
            f"- Campos opcionais: só os que o documento preencher explicitamente.\n\n"
            f"{self.extract_instructions()}\n\n"
            f"Contexto do cliente: {self.client_context or '(nenhum)'}\n\n"
            f"Use a ferramenta `submit_{self.structure_id}` para retornar os registros."
        )

        content = [{"type": "text", "text": preamble}] + doc_blocks
        result = self._call_claude(content)
        records = result.get("records", [])

        self.log.append({
            "step": "extract",
            "records_count": len(records),
            "meta": result.get("_meta", {}),
            "notes": result.get("notes", ""),
        })
        return records

    def validate(self, records: List[Dict[str, Any]]) -> List[str]:
        """Validações básicas + customizadas. Retorna lista de issues."""
        issues: List[str] = []

        if not records:
            issues.append("Nenhum registro foi extraído.")
            return issues

        # 1) Campos obrigatórios em branco
        for i, rec in enumerate(records, 1):
            for field in self.structure.required_fields:
                val = str(rec.get(field, "")).strip()
                if not val:
                    issues.append(f"Registro #{i}: campo obrigatório `{field}` está vazio.")

        # 2) Duplicatas no campo chave
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

        # 3) Validações específicas da subclasse
        issues.extend(self.custom_validations(records))

        return issues

    def self_review(
        self,
        records: List[Dict[str, Any]],
        issues: List[str],
    ) -> List[Dict[str, Any]]:
        """Pede ao Claude para revisar e refinar os registros."""
        if not issues:
            return records

        self._notify(
            f"Revisando {self.structure.label} ({len(issues)} alertas)... (pode levar mais 1-3 min)"
        )
        records_json = json.dumps(records, indent=2, ensure_ascii=False)
        issues_text = "\n".join(f"- {i}" for i in issues[:25])

        review_prompt = (
            f"Você extraiu estes registros de {self.structure.label}:\n\n"
            f"```json\n{records_json[:20000]}\n```\n\n"
            f"A validação automática detectou problemas:\n\n{issues_text}\n\n"
            f"Revise os registros e corrija o que for possível SEM inventar dados "
            f"que não existam no documento original. Se algum problema for uma "
            f"limitação real do documento, mantenha como está e registre em `notes`.\n\n"
            f"Retorne a versão revisada usando `submit_{self.structure_id}`."
        )

        # O documento original precisa ir junto para o Claude re-consultar se quiser
        doc_blocks = _document_blocks(self.source_path, self.file_kind)
        content = [{"type": "text", "text": review_prompt}] + doc_blocks

        result = self._call_claude(content)
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
        """Pipeline completo: extract → validate → self_review → validate."""
        records = self.extract()
        issues = self.validate(records)

        if issues:
            records = self.self_review(records, issues)
            issues = self.validate(records)  # re-valida após refino

        # Garantir que todos os campos do schema existam em cada registro
        all_fields = self.structure.all_fields
        normalized = []
        for rec in records:
            normalized.append({f: str(rec.get(f, "")).strip() for f in all_fields})

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
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.client = Anthropic(api_key=self.api_key)

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
        """Retorna dict com structures_present, primary_structure, reasoning."""
        source_path = Path(source_path)
        doc_blocks = _document_blocks(source_path, file_kind)
        preamble = (
            "Analise o documento abaixo e identifique quais das 4 estruturas do FP&A Base "
            "estão presentes. Use a ferramenta `submit_triage` para retornar.\n\n"
            f"Contexto adicional: {client_context or '(nenhum)'}"
        )

        content = [{"type": "text", "text": preamble}] + doc_blocks
        tool = self._tool_schema()

        with self.client.messages.stream(
            model=self.model,
            max_tokens=1024,
            system=TRIAGER_SYSTEM,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": content}],
        ) as stream:
            final = stream.get_final_message()

        for block in final.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return dict(block.input)

        return {"structures_present": [], "primary_structure": "", "reasoning": ""}
