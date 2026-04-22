"""UI Streamlit do FP&A Base Converter - arquitetura multi-agente.

Fluxo:
    upload → Triager identifica estruturas → agentes especializados processam
    em sequência, cada um fazendo extract + validate + self_review.
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from converter import (
    FileKind,
    classify_file,
    generate_outputs,
    run_orchestration,
    validate_all,
)
from converter.schemas import get_structure


load_dotenv()


def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)


ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get_secret("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MAX_TOKENS = _get_secret("CLAUDE_MAX_TOKENS", "16384")
APP_PASSWORD = _get_secret("APP_PASSWORD", "")
MAX_UPLOAD_MB = int(_get_secret("MAX_UPLOAD_MB", "30"))

if ANTHROPIC_API_KEY:
    os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
if CLAUDE_MODEL:
    os.environ["CLAUDE_MODEL"] = CLAUDE_MODEL
if CLAUDE_MAX_TOKENS:
    os.environ["CLAUDE_MAX_TOKENS"] = CLAUDE_MAX_TOKENS


st.set_page_config(
    page_title="FP&A Base Converter · Handit",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)


st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    html, body, [class*="css"], .stApp, .stMarkdown, .stButton, input, textarea {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    .stApp { background: #FAFBFC; }
    section[data-testid="stSidebar"] { display: none; }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    .stDeployButton { display: none; }
    header[data-testid="stHeader"] { background: transparent !important; }
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 4rem;
        max-width: 820px;
    }
    h1 {
        color: #1B355B !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
        font-size: 2.25rem !important;
        margin-bottom: 0.5rem !important;
    }
    h2, h3 {
        color: #1B355B !important;
        font-weight: 700 !important;
        letter-spacing: -0.01em;
    }
    .stCaption, [data-testid="stCaptionContainer"] {
        color: #5A6475 !important;
        font-size: 0.95rem !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #00C389 0%, #00A670 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        padding: 0.85rem 1.5rem !important;
        box-shadow: 0 2px 8px rgba(0, 195, 137, 0.25);
        transition: all 0.2s ease;
        font-size: 0.95rem !important;
    }
    .stButton > button[kind="primary"]:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(0, 195, 137, 0.35);
        background: linear-gradient(135deg, #00A670 0%, #008858 100%) !important;
    }
    div[data-testid="stFileUploaderDropzone"] {
        border: 2px dashed #CBD5E1 !important;
        background: white !important;
        border-radius: 14px !important;
        padding: 2.5rem 1.5rem !important;
        transition: all 0.2s ease;
    }
    div[data-testid="stFileUploaderDropzone"]:hover {
        border-color: #00C389 !important;
        background: #F6FCF9 !important;
    }
    div[data-testid="stAlert"] {
        border-radius: 12px !important;
        padding: 1rem 1.25rem !important;
        border-width: 1px !important;
    }
    hr { border-color: #EAECF0 !important; margin: 2rem 0 !important; }
    div[data-testid="stMetric"] {
        background: white;
        border: 1px solid #EAECF0;
        border-radius: 12px;
        padding: 1rem 1.25rem;
        box-shadow: 0 1px 3px rgba(16, 24, 40, 0.04);
    }
    div[data-testid="stMetric"] label {
        color: #5A6475 !important;
        font-weight: 500 !important;
        font-size: 0.82rem !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #1B355B !important;
        font-weight: 700 !important;
    }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #1B355B 0%, #0F2542 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        padding: 0.85rem 1.5rem !important;
        box-shadow: 0 2px 8px rgba(27, 53, 91, 0.25);
        transition: all 0.2s ease;
    }
    .stDownloadButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(27, 53, 91, 0.4);
    }
    div[data-testid="stExpander"] {
        border: 1px solid #EAECF0 !important;
        border-radius: 10px !important;
        background: white !important;
    }
    .stTextInput > div > div > input {
        border-radius: 10px !important;
        border-color: #CBD5E1 !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #00C389 !important;
        box-shadow: 0 0 0 3px rgba(0, 195, 137, 0.12) !important;
    }
    .handit-brand-text {
        font-size: 1.5rem;
        font-weight: 800;
        color: #111;
        letter-spacing: -0.02em;
    }
    .handit-brand-accent { color: #00C389; }
    .handit-badge {
        display: inline-block;
        background: #F0FDF4;
        color: #00A670;
        font-size: 0.7rem;
        font-weight: 700;
        padding: 0.25rem 0.625rem;
        border-radius: 20px;
        margin-left: 0.75rem;
        border: 1px solid #BBF7D0;
        letter-spacing: 0.04em;
        vertical-align: middle;
    }
    .handit-footer {
        text-align: center;
        color: #94A3B8;
        font-size: 0.8rem;
        margin-top: 3rem;
        padding-top: 1.5rem;
        border-top: 1px solid #EAECF0;
    }
    .handit-footer strong { color: #1B355B; font-weight: 600; }
    .agent-step {
        padding: 0.75rem 1rem;
        background: white;
        border-left: 3px solid #00C389;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }
</style>
""", unsafe_allow_html=True)


def _render_brand():
    logo_path = Path("assets/handit-logo.png")
    if logo_path.exists():
        st.image(str(logo_path), width=140)
    else:
        st.markdown(
            '<span class="handit-brand-text">Hand<span class="handit-brand-accent">i</span>t</span>',
            unsafe_allow_html=True,
        )


def _check_password() -> bool:
    if not APP_PASSWORD:
        return True
    if st.session_state.get("_auth_ok"):
        return True

    _render_brand()
    st.title("Acesso restrito")
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


_render_brand()
st.markdown(
    '<h1>FP&A Base Converter <span class="handit-badge">MULTI-AGENTE</span></h1>',
    unsafe_allow_html=True,
)
st.caption(
    "Anexe o arquivo do cliente. Agentes especializados por estrutura analisam, "
    "extraem e revisam o próprio trabalho antes de entregar."
)
st.divider()


for k in ["zip_bytes", "orchestration", "client_name", "file_kind",
          "file_path", "validations"]:
    st.session_state.setdefault(k, None)


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

    if st.session_state.file_path != uploaded.name:
        tmp_dir = Path(tempfile.mkdtemp(prefix="fpa_"))
        tmp_path = tmp_dir / uploaded.name
        tmp_path.write_bytes(uploaded.getvalue())
        st.session_state.file_path = str(tmp_path)
        st.session_state.zip_bytes = None
        st.session_state.orchestration = None
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
        f"**{uploaded.name}** · {size_mb:.1f} MB · Tipo detectado: {kind_labels.get(kind, '?')}"
    )

    if kind == FileKind.UNKNOWN:
        st.error("Formato não suportado.")
        st.stop()

    if st.button("Converter para formato Handit", type="primary", use_container_width=True):
        try:
            client_name = Path(uploaded.name).stem
            status_placeholder = st.empty()

            def _progress(label: str):
                status_placeholder.markdown(
                    f'<div class="agent-step">⚡ {label}</div>',
                    unsafe_allow_html=True,
                )

            orchestration = run_orchestration(
                source_path=str(tmp_path),
                file_kind=kind,
                client_context="",
                progress_callback=_progress,
            )
            st.session_state.orchestration = orchestration

            status_placeholder.empty()

            with st.spinner("Validando cruzamentos entre estruturas..."):
                validations = validate_all(orchestration.dfs)
                st.session_state.validations = validations

            with st.spinner("Gerando arquivos de carga..."):
                zip_bytes = generate_outputs(
                    client_name=client_name,
                    source_filename=uploaded.name,
                    file_kind=kind.value,
                    mapping_or_extraction=orchestration.to_debug_dict(),
                    dfs=orchestration.dfs,
                    validations=validations,
                )
                st.session_state.zip_bytes = zip_bytes
                st.session_state.client_name = client_name

            if orchestration.dfs:
                st.success(
                    f"Conversão concluída. "
                    f"{len(orchestration.dfs)} estrutura(s) processada(s)."
                )
            else:
                st.warning(
                    "Os agentes não encontraram registros válidos. "
                    "Veja detalhes no expander abaixo."
                )
        except Exception as e:
            st.error(f"Não consegui processar o arquivo: {e}")


if st.session_state.orchestration and st.session_state.zip_bytes:
    orchestration = st.session_state.orchestration
    st.divider()

    triage = orchestration.triage
    structures_present = triage.get("structures_present", [])
    if structures_present:
        structure_names = [get_structure(s).label for s in structures_present if s]
        st.markdown(
            f"**Estruturas identificadas:** {', '.join(structure_names)}"
        )
        if triage.get("reasoning"):
            st.caption(f"_{triage['reasoning']}_")

    if orchestration.dfs:
        cols = st.columns(len(orchestration.dfs))
        for col, (sid, df) in zip(cols, orchestration.dfs.items()):
            s = get_structure(sid)
            agent_out = orchestration.agent_outputs.get(sid, {})
            issues = agent_out.get("remaining_issues", [])
            with col:
                st.metric(
                    label=s.label,
                    value=len(df),
                    delta=("OK" if not issues else f"{len(issues)} alertas"),
                    delta_color=("normal" if not issues else "inverse"),
                )

    all_alerts = []
    for sid, out in orchestration.agent_outputs.items():
        label = get_structure(sid).label
        for issue in out.get("remaining_issues", []):
            all_alerts.append(f"**{label}**: {issue}")

    if st.session_state.validations:
        for sid, v in st.session_state.validations.items():
            label = get_structure(sid).label
            for err in v.errors:
                all_alerts.append(f"**{label}** (cruzamento): {err}")

    if all_alerts:
        with st.expander(f"{len(all_alerts)} alertas para revisar antes do upload"):
            for a in all_alerts:
                st.markdown(f"- {a}")

    with st.expander("Ver passos executados por cada agente (debug)"):
        st.json(orchestration.to_debug_dict())

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


st.markdown(
    '<div class="handit-footer">'
    'FP&A Base Converter · Arquitetura Multi-Agente · '
    'Powered by <strong>Claude AI</strong> · <strong>Handit</strong> © 2026'
    '</div>',
    unsafe_allow_html=True,
)
