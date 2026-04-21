"""Validações automáticas pós-transformação."""

import re
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from .schemas import get_structure


@dataclass
class ValidationResult:
    structure_id: str
    total_rows: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _validate_structure(df: pd.DataFrame, structure_id: str) -> ValidationResult:
    structure = get_structure(structure_id)
    result = ValidationResult(structure_id=structure_id, total_rows=len(df))

    # Obrigatórios em branco
    for f in structure.required_fields:
        if f not in df.columns:
            result.errors.append(f"Coluna obrigatória ausente: {f}")
            continue
        empty = df[f].astype(str).str.strip().eq("").sum() + df[f].isna().sum()
        if empty > 0:
            result.errors.append(f"{empty} linhas com {f} em branco (obrigatório)")

    # Duplicados em campos-chave
    key_candidates = {
        "centro_de_custo": "CC_COD",
        "plano_de_contas": "CONTA_CONTABIL_COD",
    }
    key = key_candidates.get(structure_id)
    if key and key in df.columns:
        dups = df[key].duplicated(keep=False).sum()
        if dups > 0:
            result.errors.append(f"{dups} linhas com {key} duplicado")

    return result


def _validate_razao(
    razao: pd.DataFrame,
    cc_codes: set[str],
    conta_codes: set[str],
) -> ValidationResult:
    result = _validate_structure(razao, "razao_contabil")

    # Datas
    if "DATA_LANCAMENTO" in razao.columns:
        bad_dates = (~razao["DATA_LANCAMENTO"].astype(str).str.match(DATE_RE)).sum()
        if bad_dates > 0:
            result.errors.append(
                f"{bad_dates} linhas com DATA_LANCAMENTO fora do padrão DD/MM/AAAA"
            )

    # CCs/Contas órfãos
    if "CC_COD" in razao.columns and cc_codes:
        orphan = (~razao["CC_COD"].astype(str).isin(cc_codes | {"0", ""})).sum()
        if orphan > 0:
            result.errors.append(f"{orphan} lançamentos com CC_COD órfão")
    if "CONTA_CONTABIL_COD" in razao.columns and conta_codes:
        orphan = (~razao["CONTA_CONTABIL_COD"].astype(str).isin(conta_codes | {""})).sum()
        if orphan > 0:
            result.errors.append(f"{orphan} lançamentos com CONTA_CONTABIL_COD órfão")

    # Totais por filial
    if {"FILIAL_COD", "VALOR_LANCAMENTO", "NATUREZA_LANCAMENTO"}.issubset(razao.columns):
        vals = pd.to_numeric(razao["VALOR_LANCAMENTO"], errors="coerce").fillna(0)
        by_filial = razao.groupby("FILIAL_COD").apply(
            lambda g: {
                "D": float(pd.to_numeric(g["VALOR_LANCAMENTO"], errors="coerce")
                           .where(g["NATUREZA_LANCAMENTO"] == "D", 0).sum()),
                "C": float(pd.to_numeric(g["VALOR_LANCAMENTO"], errors="coerce")
                           .where(g["NATUREZA_LANCAMENTO"] == "C", 0).sum()),
                "n": int(len(g)),
            }
        ).to_dict()
        result.metrics["por_filial"] = by_filial
        result.metrics["total_D"] = float(
            vals.where(razao["NATUREZA_LANCAMENTO"] == "D", 0).sum()
        )
        result.metrics["total_C"] = float(
            vals.where(razao["NATUREZA_LANCAMENTO"] == "C", 0).sum()
        )

    return result


def validate_all(
    dfs: Dict[str, pd.DataFrame],
) -> Dict[str, ValidationResult]:
    results: Dict[str, ValidationResult] = {}

    cc_codes = (
        set(dfs["centro_de_custo"]["CC_COD"].astype(str))
        if "centro_de_custo" in dfs
        else set()
    )
    conta_codes = (
        set(dfs["plano_de_contas"]["CONTA_CONTABIL_COD"].astype(str))
        if "plano_de_contas" in dfs
        else set()
    )

    for sid, df in dfs.items():
        if sid == "razao_contabil":
            results[sid] = _validate_razao(df, cc_codes, conta_codes)
        else:
            results[sid] = _validate_structure(df, sid)

    return results
