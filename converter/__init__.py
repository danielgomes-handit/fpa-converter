"""FP&A Base Converter - arquitetura multi-agente."""

from .analyzer import analyze_file, profile_to_prompt
from .mapper import propose_mapping
from .transformer import apply_mapping
from .extractor import extract_records, extraction_to_dataframes
from .validator import validate_all
from .reporter import generate_outputs
from .router import classify_file, FileKind
from .orchestrator import run_orchestration, OrchestrationResult

__all__ = [
    "analyze_file",
    "profile_to_prompt",
    "propose_mapping",
    "apply_mapping",
    "extract_records",
    "extraction_to_dataframes",
    "validate_all",
    "generate_outputs",
    "classify_file",
    "FileKind",
    "run_orchestration",
    "OrchestrationResult",
]
