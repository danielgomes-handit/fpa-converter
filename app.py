"""UI Streamlit do FP&A Base Converter - modo simples.

Fluxo: usuário anexa arquivo → clica em Converter → baixa o zip no formato Handit.
Nenhuma configuração pelo usuário: a API Key do Anthropic fica no servidor.

Rodar local: streamlit run app.py
Deploy: ver DEPLOY.md
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from converter import (
    FileKind,
    analyze_file,
    apply_mapping,
    classify_file,
    extract_records,
    extraction_to_dataframes,
    generate_outputs,
    profile_to_prompt,
    propose_mapping,
    validate_all,
)
from converter.schemas import get_structure


load_dotenv()

# --- Config (vem dos Secrets do Streamlit Cloud ou do .env local) ---
def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)


ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get_secret("CLAUDE_MODEL", "claude-sonnet-4-6")
APP_PASSWORD = _get_secret("APP_PASSWORD", "")
MAX_UPLOAD_MB = int(_get_secret("MAX_UPLOAD_MB", "30"))

if ANTHROPIC_API_KEY:
    os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
if CLAUDE_MODEL:
    os.environ["CLAUDE_MODEL"] = CLAUDE_MODEL


# --- Page config ---
st.set_page_config(
    page_title="FP&A Base Converter - Handit",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .stApp h1 { color: #1B355B; }
    .stButton>button[kind="primary"] {
        background-color: #00C389; color: white; border: 0; font-weight: 600;
    }
    .stButton>button[kind="primary"]:hover {
        background-color: #1B355B; color: white;
    }
    div[data-testid="stFileUploaderDropzone"] {
        border: 2px dashed #00C389; background-color: #F6FCF9;
    }
    section[data-testid="stSidebar"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Gate de senha (opcional) ---
def _check_password() -> bool:
    if not APP_PASSWORD:
        return True
    if st.session_state.get("_auth_ok"):
        return True

    st.title("FP&A Base Converter")
    st.caption("Acesso restrito")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
        if pwd == APP_PASSWORD:
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    return False


if not _check_password():
    st.stop()

if not ANTHROPIC_API_KEY:
    st.error("Configuração do servidor ausente. Contate o administrador.")
    st.stop()


# --- Header ---
st.title("FP&A Base Converter")
st.caption(
    "Anexe o arquivo do cliente. A ferramenta retorna os arquivos no formato de carga da Handit."
)
st.divider()


# --- Session state ---
for k in ["zip_bytes", "dfs", "validations", "client_name", "file_kind", "file_path"]:
    st.session_state.setdefault(k, None)


# --- Upload ---
uploaded = st.file_uploader(
    f"Anexe o arquivo (xlsx, csv, pdf, imagem ou texto · máx. {MAX_UPLOAD_MB}MB)",
    type=["xlsx", "xlsm", "csv", "tsv", "pdf", "png", "jpg", "jpeg", "webp", "txt", "md"],
    label_visibility="visible",
)

if uploaded is not None:
    size_mb = len(uploaded.getvalue()) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_MB:
        st.error(f"Arquivo com {size_mb:.1f}MB excede o limite de {MAX_UPLOAD_MB}MB.")
        st.stop()

    # Salva numa pasta temporária única por upload
    if st.session_state.file_path != uploaded.name:
        tmp_dir = Path(tempfile.mkdtemp(prefix="fpa_"))
        tmp_path = tmp_dir / uploaded.name
        tmp_path.write_bytes(uploaded.getvalue())
        st.session_state.file_path = str(tmp_path)
        st.session_state.zip_bytes = None
        st.session_state.dfs = None
        st.session_state.validations = None

    tmp_path = Path(st.session_state.file_path)
    kind, reason = classify_file(tmp_path)
    st.session_state.file_kind = kind

    kind_labels = {
        FileKind.TABULAR_STRUCTURED: "Planilha estruturada",
        FileKind.TABULAR_MESSY: "Planilha não estruturada",
        FileKind.PDF_WITH_TEXT: "PDF com texto",
        FileKind.PDF_SCANNED: "PDF escaneado",
        FileKind.IMAGE: "Imagem",
        FileKind.TEXT_FREEFORM: "Texto livre",
        FileKind.UNKNOWN: "Formato desconhecido",
    }
    st.caption(
        f"**{uploaded.name}** ({size_mb:.1f} MB) · Tipo detectado: {kind_labels.get(kind, '?')}"
    )

    if kind == FileKind.UNKNOWN:
        st.error("Formato não suportado.")
        st.stop()

    # Botão único de conversão
    if st.button("Converter para formato Handit", type="primary", use_container_width=True):
        try:
            client_name = Path(uploaded.name).stem

            with st.spinner("Analisando o arquivo..."):
                if kind == FileKind.TABULAR_STRUCTURED:
                    profile = analyze_file(str(tmp_path))
                    profile_md = profile_to_prompt(profile)
                    mapping = propose_mapping(source_profile_markdown=profile_md)
                    dfs = apply_mapping(str(tmp_path), mapping)
                else:
                    mapping = extract_records(
                        source_path=str(tmp_path),
                        file_kind=kind,
                    )
                    dfs = extraction_to_dataframes(mapping)

            with st.spinner("Validando..."):
                validations = validate_all(dfs)

            with st.spinner("Gerando arquivos de carga..."):
                zip_bytes = generate_outputs(
                    client_name=client_name,
                    source_filename=uploaded.name,
                    file_kind=kind.value,
                    mapping_or_extraction=mapping,
                    dfs=dfs,
                    validations=validations,
                )

            st.session_state.zip_bytes = zip_bytes
            st.session_state.dfs = dfs
            st.session_state.validations = validations
            st.session_state.client_name = client_name
            st.success("Conversão concluída.")
        except Exception as e:
            st.error(f"Não consegui processar o arquivo: {e}")


# --- Resumo pós-conversão ---
if st.session_state.zip_bytes and st.session_state.dfs:
    st.divider()

    cols = st.columns(len(st.session_state.dfs))
    for col, (sid, df) in zip(cols, st.session_state.dfs.items()):
        s = get_structure(sid)
        v = st.session_state.validations.get(sid) if st.session_state.validations else None
        err = len(v.errors) if v else 0
        with col:
            st.metric(
                label=s.label,
                value=len(df),
                delta=("OK" if err == 0 else f"{err} alertas"),
                delta_color=("normal" if err == 0 else "inverse"),
            )

    # Alertas consolidados
    all_errors = []
    for sid, v in (st.session_state.validations or {}).items():
        for e in v.errors:
            all_errors.append(f"**{get_structure(sid).label}**: {e}")
    if all_errors:
        with st.expander(f"{len(all_errors)} alertas para revisar antes do upload"):
            for a in all_errors:
                st.markdown(f"- {a}")

    # Download
    now = datetime.now().strftime("%Y%m%d_%H%M")
    safe_client = (st.session_state.client_name or "cliente").replace(" ", "_")
    st.download_button(
        label="Baixar pacote Handit (zip)",
        data=st.session_state.zip_bytes,
        file_name=f"CargaFPABase_{safe_client}_{now}.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True,
    )

st.divider()
st.caption("FP&A Base Converter · Handit")
