"""Aplica o mapeamento proposto pelo Claude e gera os DataFrames finais.

Toda a lógica de transformação roda em pandas puro (sem IA), para ser
determinística, rápida e barata.
"""

from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from .analyzer import read_sheet
from .schemas import ALL_STRUCTURES, get_structure


def _apply_strategy(
    source_df: pd.DataFrame,
    fpa_field: str,
    source_column: str | None,
    strategy: str,
    constant_value: str | None = None,
    struct_to_desc: Dict[str, str] | None = None,
) -> pd.Series:
    """Aplica uma strategy de mapeamento e retorna a série para o campo FP&A."""
    n = len(source_df)

    if strategy == "direct":
        if not source_column or source_column not in source_df.columns:
            return pd.Series([""] * n)
        return source_df[source_column].fillna("").astype(str)

    if strategy == "constant":
        return pd.Series([constant_value or ""] * n)

    if strategy == "abs_value":
        if not source_column or source_column not in source_df.columns:
            return pd.Series([""] * n)
        return pd.to_numeric(source_df[source_column], errors="coerce").abs().fillna(0)

    if strategy == "natureza_from_sign":
        if not source_column or source_column not in source_df.columns:
            return pd.Series([""] * n)
        vals = pd.to_numeric(source_df[source_column], errors="coerce")
        return vals.apply(lambda v: "D" if pd.notna(v) and v < 0 else ("C" if pd.notna(v) else ""))

    if strategy == "natureza_from_movement_type":
        if not source_column or source_column not in source_df.columns:
            return pd.Series([""] * n)

        def _map(v: Any) -> str:
            s = str(v).strip().lower()
            if s in {"entrada", "recebimento", "credito", "crédito"}:
                return "C"
            if s in {"saida", "saída", "pagamento", "debito", "débito"}:
                return "D"
            return ""

        return source_df[source_column].apply(_map)

    if strategy == "derived_from_dotted_code":
        # Extrai o nível correspondente do campo fpa_field (ex.: CC_N2_COD)
        # Convenção: CC_N{i}_COD extrai primeiros i tokens separados por ponto
        if not source_column or source_column not in source_df.columns:
            return pd.Series([""] * n)

        level = _extract_level_from_name(fpa_field)
        if level is None:
            return pd.Series([""] * n)

        def _derive(code: Any) -> str:
            if pd.isna(code):
                return ""
            parts = str(code).split(".")
            if len(parts) < level:
                return ""
            key = ".".join(parts[:level])
            if fpa_field.endswith("_DESC") and struct_to_desc:
                return struct_to_desc.get(key, "")
            return key

        return source_df[source_column].apply(_derive)

    if strategy == "lookup_from_description":
        # Implementação simples: só retorna a própria descrição como placeholder.
        # Em produção, este método receberia o dicionário de lookup pré-construído.
        if not source_column or source_column not in source_df.columns:
            return pd.Series([""] * n)
        return source_df[source_column].fillna("").astype(str)

    # gap ou desconhecido
    return pd.Series([""] * n)


def _extract_level_from_name(fpa_field: str) -> int | None:
    """CC_N2_COD -> 2, CONTA_N3_DESC -> 3."""
    import re

    m = re.search(r"_N(\d+)_", fpa_field)
    if m:
        return int(m.group(1))
    return None


def _build_struct_to_desc(df: pd.DataFrame, code_col: str, desc_col: str) -> Dict[str, str]:
    mapping = {}
    if code_col not in df.columns or desc_col not in df.columns:
        return mapping
    for _, row in df[[code_col, desc_col]].dropna().iterrows():
        mapping[str(row[code_col])] = str(row[desc_col])
    return mapping


def apply_mapping(
    source_path: str | Path,
    mapping: Dict[str, Any],
) -> Dict[str, pd.DataFrame]:
    """Dado o caminho do arquivo e o mapeamento, retorna dict {structure_id: DataFrame}."""
    results: Dict[str, pd.DataFrame] = {}

    for struct_map in mapping.get("structures", []):
        structure = get_structure(struct_map["structure_id"])
        source_sheet = struct_map["source_sheet"]
        source_df = read_sheet(source_path, source_sheet)

        # Detecta colunas típicas para lookup de descrições hierárquicas
        struct_to_desc = {}
        for fm in struct_map.get("field_mappings", []):
            if fm["strategy"] == "derived_from_dotted_code":
                code_col = fm.get("source_column")
                # Tenta achar uma coluna de descrição correspondente no source
                for cand in source_df.columns:
                    if "desc" in str(cand).lower() and code_col and cand != code_col:
                        struct_to_desc = _build_struct_to_desc(source_df, code_col, cand)
                        break
                break

        out_cols = {}
        for fm in struct_map.get("field_mappings", []):
            series = _apply_strategy(
                source_df=source_df,
                fpa_field=fm["fpa_field"],
                source_column=fm.get("source_column"),
                strategy=fm["strategy"],
                constant_value=fm.get("constant_value"),
                struct_to_desc=struct_to_desc,
            )
            out_cols[fm["fpa_field"]] = series

        out_df = pd.DataFrame(out_cols)

        # Garantir que todos os campos da estrutura existam (mesmo vazios)
        for field_name in structure.all_fields:
            if field_name not in out_df.columns:
                out_df[field_name] = ""
        out_df = out_df[structure.all_fields]

        # Deduplicação se solicitada
        dedup_col = struct_map.get("deduplicate_by")
        if dedup_col and dedup_col in out_df.columns:
            out_df = out_df.drop_duplicates(subset=[dedup_col], keep="first").reset_index(drop=True)

        results[struct_map["structure_id"]] = out_df

    return results
