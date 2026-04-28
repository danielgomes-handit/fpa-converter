"""Lê o arquivo do cliente e extrai metadados que serão enviados ao Claude.

O objetivo é dar ao Claude informação suficiente para propor o mapeamento
sem precisar enviar o arquivo inteiro (o que seria caro e lento).
"""

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


# =============================================================================
# Leitura robusta de CSV (detecta separador automaticamente)
# =============================================================================

def _read_text_with_fallback(path: Path, sample_size: int | None = None) -> str:
    """Lê arquivo texto com fallback de encoding (utf-8 → latin-1 → cp1252)."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read() if sample_size is None else f.read(sample_size)
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    # Último recurso: replace
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read() if sample_size is None else f.read(sample_size)


def _detect_csv_layout(path: Path, sample_size: int = 16384) -> Dict[str, Any]:
    """Detecta separador, encoding e linha onde começa a tabela real.

    Retorna dict com:
    - separator: ',' | ';' | '\\t' | '|'
    - skiprows: número de linhas a ignorar antes do header
    - encoding: encoding usado
    """
    sample = _read_text_with_fallback(path, sample_size)

    candidates = [";", ",", "\t", "|"]
    lines = sample.splitlines()

    # Para cada separador candidato, encontra a linha onde começam várias linhas
    # consecutivas com o mesmo número de campos (heurística de "tabela real").
    best = {"separator": ",", "skiprows": 0, "score": -1}

    for sep in candidates:
        # Conta separadores em cada linha não-vazia
        counts = [ln.count(sep) for ln in lines]

        # Procura janela de pelo menos 3 linhas consecutivas com mesmo count > 0
        for start in range(len(counts)):
            c = counts[start]
            if c == 0:
                continue
            # Quantas linhas consecutivas a partir daqui têm o MESMO count?
            run = 1
            for j in range(start + 1, min(start + 50, len(counts))):
                if counts[j] == c:
                    run += 1
                else:
                    # tolera 1 linha quebrada no meio
                    if j + 1 < len(counts) and counts[j + 1] == c:
                        run += 1
                        continue
                    break
            # Score: alto número de campos consistentes × tamanho do run
            score = c * run
            if run >= 3 and score > best["score"]:
                best = {"separator": sep, "skiprows": start, "score": score}

    return {
        "separator": best["separator"],
        "skiprows": best["skiprows"],
    }


def _detect_csv_separator(path: Path, sample_size: int = 8192) -> str:
    """Compatibilidade: retorna apenas o separador detectado."""
    return _detect_csv_layout(path, sample_size)["separator"]


def _read_csv_smart(path: Path, dtype=str) -> pd.DataFrame:
    """Lê CSV detectando separador, encoding e linhas de cabeçalho-livre."""
    suffix = path.suffix.lower()
    if suffix == ".tsv":
        layout = {"separator": "\t", "skiprows": 0}
    else:
        layout = _detect_csv_layout(path)

    sep = layout["separator"]
    skiprows = layout["skiprows"]

    # Tentativa 1: engine C (rápido) com skiprows detectado
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(
                path, sep=sep, dtype=dtype, encoding=enc, skiprows=skiprows
            )
        except UnicodeDecodeError:
            continue
        except Exception:
            break

    # Tentativa 2: engine Python tolerando linhas malformadas
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(
                path,
                sep=sep,
                dtype=dtype,
                encoding=enc,
                skiprows=skiprows,
                engine="python",
                on_bad_lines="skip",
            )
        except Exception:
            continue

    # Tentativa 3: auto-detect total (sep=None, skiprows=0)
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return pd.read_csv(
                path,
                sep=None,
                dtype=dtype,
                encoding=enc,
                engine="python",
                on_bad_lines="skip",
            )
        except Exception:
            continue

    raise ValueError(
        f"Não foi possível ler o CSV '{path.name}'. "
        f"Verifique o separador e a codificação do arquivo."
    )


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
    head_md = ""
    if len(df):
        try:
            head_md = df.head(n_head).to_markdown(index=False)
        except (ImportError, ModuleNotFoundError):
            head_md = df.head(n_head).to_csv(index=False)
        except Exception:
            head_md = df.head(n_head).to_string(index=False)
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
        df = _read_csv_smart(path)
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
        return _read_csv_smart(path)
    raise ValueError(f"Formato não suportado: {path.suffix}")
