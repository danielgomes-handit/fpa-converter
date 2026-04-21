"""Lê o arquivo do cliente e extrai metadados que serão enviados ao Claude.

O objetivo é dar ao Claude informação suficiente para propor o mapeamento
sem precisar enviar o arquivo inteiro (o que seria caro e lento).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    non_null_count: int
    sample_values: List[Any] = field(default_factory=list)
    unique_count: int = 0


@dataclass
class SheetProfile:
    name: str
    row_count: int
    columns: List[ColumnProfile]
    head_markdown: str = ""


@dataclass
class FileProfile:
    path: str
    sheets: List[SheetProfile]


def _profile_column(series: pd.Series, n_samples: int = 5) -> ColumnProfile:
    non_null = series.dropna()
    samples = non_null.head(n_samples).astype(str).tolist()
    return ColumnProfile(
        name=str(series.name),
        dtype=str(series.dtype),
        non_null_count=int(non_null.shape[0]),
        sample_values=samples,
        unique_count=int(non_null.nunique()),
    )


def _profile_sheet(df: pd.DataFrame, sheet_name: str, n_head: int = 5) -> SheetProfile:
    cols = [_profile_column(df[c]) for c in df.columns]
    head_md = df.head(n_head).to_markdown(index=False) if len(df) else ""
    return SheetProfile(
        name=sheet_name,
        row_count=int(df.shape[0]),
        columns=cols,
        head_markdown=head_md,
    )


def analyze_file(path: str | Path) -> FileProfile:
    """Lê xlsx ou csv e retorna um perfil com metadados de cada aba."""
    path = Path(path)
    sheets: List[SheetProfile] = []

    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        xls = pd.ExcelFile(path)
        for sheet_name in xls.sheet_names:
            try:
                df = xls.parse(sheet_name)
            except Exception:
                continue
            if df.shape[1] == 0:
                continue
            sheets.append(_profile_sheet(df, sheet_name))
    elif path.suffix.lower() in {".csv", ".tsv"}:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(path, sep=sep, dtype=str)
        sheets.append(_profile_sheet(df, path.stem))
    else:
        raise ValueError(f"Formato não suportado: {path.suffix}")

    return FileProfile(path=str(path), sheets=sheets)


def profile_to_prompt(profile: FileProfile, max_cols: int = 50) -> str:
    """Serializa o perfil em markdown para mandar ao Claude."""
    parts = [f"# Arquivo: `{Path(profile.path).name}`", ""]
    for sheet in profile.sheets:
        parts.append(f"## Aba: `{sheet.name}` ({sheet.row_count} linhas)")
        parts.append("")
        parts.append("### Colunas")
        for col in sheet.columns[:max_cols]:
            samples = ", ".join(f"`{v}`" for v in col.sample_values[:3])
            parts.append(
                f"- **{col.name}** ({col.dtype}, {col.non_null_count} preenchidos, "
                f"{col.unique_count} únicos): {samples}"
            )
        if len(sheet.columns) > max_cols:
            parts.append(f"- ... e mais {len(sheet.columns) - max_cols} colunas")
        parts.append("")
        if sheet.head_markdown:
            parts.append("### Amostra (5 primeiras linhas)")
            parts.append("")
            parts.append(sheet.head_markdown)
            parts.append("")
    return "\n".join(parts)


def read_sheet(path: str | Path, sheet_name: str) -> pd.DataFrame:
    """Lê uma aba específica para aplicar o mapeamento."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, sheet_name=sheet_name, dtype=str)
    if path.suffix.lower() in {".csv", ".tsv"}:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        return pd.read_csv(path, sep=sep, dtype=str)
    raise ValueError(f"Formato não suportado: {path.suffix}")
