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


# =============================================================================
# Leitura robusta de xlsx-like: detecta tipo real e trata xlsx, xls, HTML
# disfarçado e CSV renomeado
# =============================================================================

def _detect_real_file_type(path: Path) -> str:
    """Detecta o tipo REAL do arquivo via magic bytes (não confia na extensão).

    Retorna um de: 'xlsx', 'xls', 'html', 'csv', 'unknown'.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except Exception:
        return "unknown"

    if not head:
        return "unknown"

    # xlsx, xlsm, docx, etc são ZIP files
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06") \
            or head.startswith(b"PK\x07\x08"):
        return "xlsx"

    # xls antigo (OLE2 Compound Document)
    if head.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
        return "xls"

    # Tenta detectar texto/HTML/CSV: lê os primeiros 4 KB como texto
    try:
        sample = head.decode("utf-8", errors="ignore") + (
            open(path, "r", encoding="utf-8", errors="ignore").read(4096)
        )
    except Exception:
        sample = ""

    sample_low = sample.lstrip().lower()
    # HTML: começa com <html, <!doctype, <?xml + html, ou <table
    if any(sample_low.startswith(prefix) for prefix in (
            "<html", "<!doctype html", "<?xml", "<table", "<meta", "<head",
            "﻿<html", "﻿<!doctype")):
        return "html"
    # Detecta HTML mesmo sem prefixo no início (XML/markup misturado)
    if "<html" in sample_low[:1000] or "<table" in sample_low[:1000]:
        return "html"

    # Se chegou aqui e tem conteúdo legível, considera CSV
    if sample.strip():
        return "csv"

    return "unknown"


# Stylesheet OOXML mínimo válido — usado como substituto para styles
# malformados em xlsx gerados por ERPs antigos.
_MINIMAL_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    '</styleSheet>'
).encode("utf-8")


def _repair_xlsx(path: Path) -> Path | None:
    """Tenta consertar xlsx malformados gerados por ERPs (Datasul, Protheus, etc).

    Cobre os dois bugs mais comuns:
    1. Paths internos com `\\` em vez de `/` (viola padrão OOXML/ZIP)
    2. `xl/styles.xml` malformado (Border.left como string em vez de objeto Side)

    Retorna o path de um arquivo temporário "consertado", ou None se o arquivo
    estiver OK ou não puder ser consertado.
    """
    import zipfile
    import tempfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return None

    # Sempre regrava normalizando paths E substituindo styles (operação barata
    # e idempotente). Se o arquivo estava OK, ainda assim funciona.
    has_problem = (
        any("\\" in n for n in names)
        or any(n.replace("\\", "/").endswith("xl/styles.xml") for n in names)
    )
    if not has_problem:
        return None

    fixed = Path(tempfile.mktemp(suffix=".xlsx"))
    try:
        with zipfile.ZipFile(path) as zin, \
                zipfile.ZipFile(fixed, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                fixed_name = info.filename.replace("\\", "/")
                # Substitui styles.xml por versão mínima válida
                if fixed_name == "xl/styles.xml":
                    data = _MINIMAL_STYLES_XML
                else:
                    data = zin.read(info.filename)
                new_info = zipfile.ZipInfo(
                    filename=fixed_name,
                    date_time=info.date_time,
                )
                new_info.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(new_info, data)
        return fixed
    except Exception:
        try:
            fixed.unlink()
        except Exception:
            pass
        return None


def _read_zip_fallback(path: Path) -> Dict[str, pd.DataFrame]:
    """Tenta extrair tabelas de um zip-like que NÃO é xlsx OOXML padrão.

    Casos cobertos:
    - xlsx mal formado com `\\` em vez de `/` nos paths (Datasul/Protheus etc.)
    - Zips com CSV/TSV dentro (ERPs que exportam dados em zip)
    - Zips com HTML dentro
    - Zips com XML do tipo SpreadsheetML 2003 (Microsoft Office XML antigo)
    """
    import zipfile

    # 0. Tenta consertar bugs comuns do xlsx (Datasul/Protheus/ERPs antigos):
    #    paths com backslash, styles.xml malformado, etc.
    fixed_path = _repair_xlsx(path)
    if fixed_path:
        try:
            xls = pd.ExcelFile(fixed_path, engine="openpyxl")
            sheets = {}
            for sn in xls.sheet_names:
                try:
                    df = xls.parse(sn)
                    if not df.empty and df.shape[1] > 0:
                        sheets[sn] = df
                except Exception:
                    continue
            if sheets:
                return sheets
        except Exception:
            pass
        finally:
            try:
                fixed_path.unlink()
            except Exception:
                pass

    sheets: Dict[str, pd.DataFrame] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            for name in names:
                lower = name.lower()
                if lower.endswith("/") or lower.startswith("__macosx/"):
                    continue
                try:
                    with zf.open(name) as inner:
                        data = inner.read()
                except Exception:
                    continue

                # Tenta CSV
                if lower.endswith((".csv", ".tsv", ".txt")):
                    try:
                        from io import BytesIO
                        sep = "\t" if lower.endswith(".tsv") else ","
                        df = pd.read_csv(BytesIO(data), sep=sep, dtype=str,
                                          encoding_errors="replace")
                        if not df.empty and df.shape[1] > 0:
                            sheets[Path(name).stem] = df
                    except Exception:
                        pass

                # Tenta HTML (típico de exports SAP)
                elif lower.endswith((".html", ".htm", ".xhtml")):
                    try:
                        from io import BytesIO
                        tabs = pd.read_html(BytesIO(data))
                        for i, df in enumerate(tabs, 1):
                            if not df.empty and df.shape[1] > 0:
                                key = f"{Path(name).stem}_t{i}" if len(tabs) > 1 else Path(name).stem
                                sheets[key] = df
                    except Exception:
                        pass

                # Tenta SpreadsheetML 2003 (Microsoft Office XML antigo)
                elif lower.endswith(".xml") and "workbook" not in lower:
                    text = data.decode("utf-8", errors="ignore")
                    if "<Worksheet" in text or "<Table" in text:
                        try:
                            from io import StringIO
                            tabs = pd.read_html(StringIO(text))
                            for i, df in enumerate(tabs, 1):
                                if not df.empty and df.shape[1] > 0:
                                    sheets[f"{Path(name).stem}_t{i}"] = df
                        except Exception:
                            pass
    except zipfile.BadZipFile:
        pass

    return sheets


def _read_xlsx_like_smart(path: Path) -> Dict[str, pd.DataFrame]:
    """Lê arquivo xlsx-like detectando o tipo real e usando o parser correto.

    Retorna dict {sheet_name: DataFrame}. Sempre devolve pelo menos 1 sheet
    (mesmo que o arquivo seja CSV/HTML, será envolvido em uma "aba" sintética).
    """
    real_type = _detect_real_file_type(path)

    # 1. xlsx real → openpyxl normal
    if real_type == "xlsx":
        try:
            xls = pd.ExcelFile(path, engine="openpyxl")
            sheets = {}
            for sn in xls.sheet_names:
                try:
                    df = xls.parse(sn)
                    if not df.empty and df.shape[1] > 0:
                        sheets[sn] = df
                except Exception:
                    continue
            if sheets:
                return sheets
        except Exception:
            pass  # Cai pra outras estratégias

        # 1b. É um zip mas openpyxl falhou (xlsx não-padrão / corrompido) →
        # tenta extrair conteúdo do zip diretamente
        sheets = _read_zip_fallback(path)
        if sheets:
            return sheets

    # 2. xls antigo (binário OLE2) → xlrd
    if real_type == "xls":
        try:
            xls = pd.ExcelFile(path, engine="xlrd")
            sheets = {}
            for sn in xls.sheet_names:
                try:
                    df = xls.parse(sn)
                    if not df.empty and df.shape[1] > 0:
                        sheets[sn] = df
                except Exception:
                    continue
            if sheets:
                return sheets
        except Exception:
            pass

    # 3. HTML disfarçado (típico SAP/S4HANA, Mercado Pago, etc.)
    if real_type == "html":
        try:
            tables = pd.read_html(path, encoding="utf-8", flavor="lxml")
        except Exception:
            try:
                tables = pd.read_html(path, encoding="latin-1", flavor="lxml")
            except Exception:
                try:
                    tables = pd.read_html(path)  # fallback default
                except Exception:
                    tables = []
        if tables:
            sheets = {}
            for i, df in enumerate(tables, 1):
                if df.empty or df.shape[1] == 0:
                    continue
                name = f"Tabela_{i}" if len(tables) > 1 else path.stem
                sheets[name] = df
            if sheets:
                return sheets

    # 4. CSV renomeado para xlsx
    if real_type == "csv":
        try:
            df = _read_csv_smart(path)
            if not df.empty and df.shape[1] > 0:
                return {path.stem: df}
        except Exception:
            pass

    # 5. Último fallback: tenta openpyxl mesmo se não detectou (alguns xlsx
    # corrompidos podem não bater os magic bytes esperados)
    try:
        xls = pd.ExcelFile(path)
        sheets = {}
        for sn in xls.sheet_names:
            try:
                df = xls.parse(sn)
                if not df.empty and df.shape[1] > 0:
                    sheets[sn] = df
            except Exception:
                continue
        if sheets:
            return sheets
    except Exception:
        pass

    # Diagnóstico final: se for um zip, lista o conteúdo pra ajudar a entender
    extra_info = ""
    if real_type == "xlsx":
        try:
            import zipfile
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()[:15]
            extra_info = (
                f" Conteúdo do zip (primeiros 15 itens): {names}. "
                f"Esperava 'xl/workbook.xml' (formato OOXML/Excel padrão)."
            )
        except Exception:
            extra_info = " O arquivo aparenta ser um ZIP, mas não pôde ser aberto."

    raise ValueError(
        f"Não foi possível abrir '{path.name}' como planilha. "
        f"Tipo detectado: '{real_type}'.{extra_info} "
        f"Tente abrir o arquivo no Excel e salvar como xlsx (Salvar como → "
        f"Pasta de Trabalho do Excel .xlsx) ou exportar como CSV."
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


def _profile_sheet(df: pd.DataFrame, sheet_name: str, n_head: int = 10) -> SheetProfile:
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
    """Lê xlsx, xls, csv (ou xlsx falso: HTML, xls antigo, csv renomeado).

    A detecção do tipo real é feita via magic bytes pelo
    `_read_xlsx_like_smart`, que resolve a maioria dos casos de arquivo com
    extensão errada (.xlsx que na verdade é xls/HTML/csv).
    """
    path = Path(path)
    sheets: List[SheetProfile] = []

    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        sheets_data = _read_xlsx_like_smart(path)
        for sheet_name, df in sheets_data.items():
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
    sheet_names = [s.name for s in profile.sheets]
    parts = [
        f"# Arquivo: `{Path(profile.path).name}`",
        "",
        f"**Total de abas:** {len(profile.sheets)} → {sheet_names}",
        "",
    ]
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
            parts.append("### Amostra (primeiras linhas)")
            parts.append("")
            parts.append(sheet.head_markdown)
            parts.append("")
    return "\n".join(parts)


def read_sheet(path: str | Path, sheet_name: str) -> pd.DataFrame:
    """Lê uma aba específica para aplicar o mapeamento."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        sheets = _read_xlsx_like_smart(path)
        if sheet_name in sheets:
            return sheets[sheet_name]
        # Sheet não encontrada: devolve a primeira disponível
        if sheets:
            return next(iter(sheets.values()))
        raise ValueError(f"Aba '{sheet_name}' não encontrada em {path.name}")
    if path.suffix.lower() in {".csv", ".tsv"}:
        return _read_csv_smart(path)
    raise ValueError(f"Formato não suportado: {path.suffix}")
