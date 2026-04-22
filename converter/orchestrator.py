"""Orchestrator: coordena Triager + agentes especializados.

Fluxo:
    1. Triager identifica quais estruturas estão no documento.
    2. Para cada estrutura presente, instancia e roda o agente correspondente.
    3. Consolida resultados em dict {structure_id: DataFrame}.

Cada agente já faz extract → validate → self_review internamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from .agents import Triager, get_agent_class
from .router import FileKind
from .schemas import get_structure


@dataclass
class OrchestrationResult:
    triage: Dict[str, Any]
    agent_outputs: Dict[str, Dict[str, Any]]  # structure_id -> {records, issues, log}
    dfs: Dict[str, pd.DataFrame]

    def to_debug_dict(self) -> Dict[str, Any]:
        """Representação serializável para o expander de debug na UI."""
        return {
            "triage": self.triage,
            "agents": {
                sid: {
                    "records_count": len(out.get("records", [])),
                    "remaining_issues": out.get("remaining_issues", []),
                    "log": out.get("log", []),
                }
                for sid, out in self.agent_outputs.items()
            },
        }


def run_orchestration(
    source_path: str | Path,
    file_kind: FileKind,
    client_context: str = "",
    progress_callback=None,
) -> OrchestrationResult:
    """Executa o fluxo completo de conversão com agentes.

    Args:
        source_path: caminho para o arquivo do cliente.
        file_kind: tipo de arquivo (saída do router.classify_file).
        client_context: contexto livre sobre o cliente.
        progress_callback: função opcional `(label: str) -> None` chamada
            a cada passo, útil para atualizar spinners na UI.
    """

    def _notify(label: str):
        if progress_callback:
            progress_callback(label)

    source_path = Path(source_path)

    # 1. Triagem: identifica estruturas presentes
    _notify("Identificando estruturas presentes no documento...")
    triager = Triager()
    triage = triager.classify(source_path, file_kind, client_context)
    structures_present: List[str] = triage.get("structures_present", []) or []

    # Se triager não identificou nada, roda todos como fallback
    if not structures_present:
        structures_present = [
            "estrutura_empresarial",
            "centro_de_custo",
            "plano_de_contas",
            "razao_contabil",
        ]
        triage["fallback_all"] = True

    # 2. Executa agentes relevantes
    agent_outputs: Dict[str, Dict[str, Any]] = {}
    dfs: Dict[str, pd.DataFrame] = {}

    for sid in structures_present:
        try:
            agent_cls = get_agent_class(sid)
        except ValueError:
            continue

        structure = get_structure(sid)
        _notify(f"Iniciando agente de {structure.label}...")

        agent = agent_cls(
            source_path=source_path,
            file_kind=file_kind,
            client_context=client_context,
            progress_callback=progress_callback,
        )
        try:
            output = agent.run()
        except Exception as e:
            output = {
                "structure_id": sid,
                "records": [],
                "remaining_issues": [f"Falha no agente: {e}"],
                "log": [{"step": "error", "message": str(e)}],
            }

        agent_outputs[sid] = output

        records = output.get("records", [])
        if records:
            df = pd.DataFrame(records)
            # Garantir ordem e presença de todos os campos
            for field_name in structure.all_fields:
                if field_name not in df.columns:
                    df[field_name] = ""
            df = df[structure.all_fields]
            dfs[sid] = df

    return OrchestrationResult(
        triage=triage,
        agent_outputs=agent_outputs,
        dfs=dfs,
    )
