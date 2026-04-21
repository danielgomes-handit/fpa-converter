"""Classifica o arquivo recebido e decide qual adapter usar."""

from enum import Enum
from pathlib import Path
from typing import Tuple

import pandas as pd


class FileKind(str, Enum):
    TABULAR_STRUCTURED = "tabular_structured"
    TABULAR_MESSY = "tabular_messy"
    PDF_WITH_TEXT = "pdf_with_text"
    PDF_SCANNED = "pdf_scanned"
    IMAGE = "image"
    TEXT_FREEFORM = "text_freeform"
    UNKNOWN = "unknown"


TABULAR_EXTS = {".xlsx", ".xlsm", ".csv", ".tsv"}
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
TEXT_EXTS = {".txt", ".md"}


def _looks_like_structured_table(path: Path) -> bool:
    """Checa se o xlsx/csv tem um cabeçalho reconhecível e dados tabulares consistentes."""
    try:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            df = pd.read_excel(path, sheet_name=0, nrows=20)
        else:
            df = pd.read_csv(path, nrows=20, dtype=str)
    except Exception:
        return False

    if df.empty or df.shape[1] < 2:
        return False

    # Cabeçalho: colunas não são todas "Unnamed" e não têm espaços excessivos
    unnamed = sum(1 for c in df.columns if str(c).startswith("Unnamed"))
    if unnamed > df.shape[1] * 0.5:
        return False

    # Linhas têm pelo menos 50% das células preenchidas
    non_null_ratio = df.notna().sum().sum() / (df.shape[0] * df.shape[1])
    return non_null_ratio >= 0.4


def _pdf_has_extractable_text(path: Path, min_chars: int = 200) -> bool:
    """Tenta extrair texto da primeira página via pypdf. Se falhar ou vier pouco texto, é escaneado."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if not reader.pages:
            return False
        text = reader.pages[0].extract_text() or ""
        return len(text.strip()) >= min_chars
    except Exception:
        return False


def classify_file(path: str | Path) -> Tuple[FileKind, str]:
    """Retorna o tipo do arquivo e uma breve justificativa."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext in TABULAR_EXTS:
        if _looks_like_structured_table(p):
            return FileKind.TABULAR_STRUCTURED, (
                "Planilha com cabeçalho identificável e dados tabulares consistentes"
            )
        return FileKind.TABULAR_MESSY, (
            "Planilha sem cabeçalho claro ou com múltiplas tabelas espalhadas"
        )

    if ext in PDF_EXTS:
        if _pdf_has_extractable_text(p):
            return FileKind.PDF_WITH_TEXT, "PDF com camada de texto extraível"
        return FileKind.PDF_SCANNED, "PDF escaneado (sem texto extraível)"

    if ext in IMAGE_EXTS:
        return FileKind.IMAGE, "Arquivo de imagem"

    if ext in TEXT_EXTS:
        return FileKind.TEXT_FREEFORM, "Texto livre"

    return FileKind.UNKNOWN, f"Extensão desconhecida: {ext}"
