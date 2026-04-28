"""Cliente LLM unificado para o projeto.

Usa o OpenAI SDK apontando para o OpenRouter (`https://openrouter.ai/api/v1`).
Vantagens:
- Modelo default: anthropic/claude-opus-4.7 (rate limits altos baseados no
  saldo da conta, sem o teto Tier 1 da Anthropic).
- Suporte a PDF, imagens e tool calling no formato OpenAI.
- SDK único para todas as chamadas (Triager + agentes especializados).

Formatos de bloco esperados em `user_content` (lista de blocos OpenAI):
- Texto:  {"type": "text", "text": "..."}
- Imagem: {"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}
- PDF:    {"type": "file", "file": {"filename": "...pdf",
           "file_data": "data:application/pdf;base64,..."}}
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI


DEFAULT_MODEL = "anthropic/claude-opus-4.7"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurada. Adicione em st.secrets ou .env."
        )
    return key


def _build_client() -> OpenAI:
    return OpenAI(
        api_key=_get_api_key(),
        base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL),
        timeout=float(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "300")),
        # OpenRouter recomenda passar HTTP-Referer e X-Title, mas são opcionais.
        default_headers={
            "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://handit.com.br"),
            "X-Title": os.environ.get("OPENROUTER_TITLE", "Handit FP&A Converter"),
        },
    )


def get_model() -> str:
    """Retorna o modelo configurado (env OPENROUTER_MODEL ou CLAUDE_MODEL)."""
    return (
        os.environ.get("OPENROUTER_MODEL")
        or os.environ.get("CLAUDE_MODEL")
        or DEFAULT_MODEL
    )


def _to_openai_tool(anth_tool: Dict[str, Any]) -> Dict[str, Any]:
    """Converte schema de tool no formato Anthropic para o formato OpenAI."""
    return {
        "type": "function",
        "function": {
            "name": anth_tool["name"],
            "description": anth_tool.get("description", ""),
            "parameters": anth_tool["input_schema"],
        },
    }


def call_with_tool(
    system: str,
    user_content: List[Dict[str, Any]],
    tool_schema: Dict[str, Any],
    model: Optional[str] = None,
    max_tokens: int = 32000,
    stream: bool = True,
) -> Dict[str, Any]:
    """Chama o LLM forçando uso de uma tool específica e retorna o input parseado.

    Retorna dict com:
    - tool_input: dict com os argumentos parseados (JSON do tool call)
    - meta: {model, finish_reason, prompt_tokens, completion_tokens}
    """
    client = _build_client()
    chosen_model = model or get_model()
    openai_tool = _to_openai_tool(tool_schema)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    common = dict(
        model=chosen_model,
        messages=messages,
        max_tokens=max_tokens,
        tools=[openai_tool],
        tool_choice={
            "type": "function",
            "function": {"name": tool_schema["name"]},
        },
    )

    if stream:
        # Streaming: acumula tool_calls.arguments delta a delta
        accumulated_args = ""
        finish_reason = None
        usage = {}
        tool_call_id = None
        tool_call_name = None

        with client.chat.completions.create(**common, stream=True,
                                            stream_options={"include_usage": True}) as resp:
            for chunk in resp:
                if not chunk.choices:
                    if chunk.usage:
                        usage = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                        }
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if not delta or not getattr(delta, "tool_calls", None):
                    continue
                for tc in delta.tool_calls:
                    if tc.id and not tool_call_id:
                        tool_call_id = tc.id
                    if tc.function:
                        if tc.function.name and not tool_call_name:
                            tool_call_name = tc.function.name
                        if tc.function.arguments:
                            accumulated_args += tc.function.arguments
        raw_args = accumulated_args
    else:
        resp = client.chat.completions.create(**common)
        choice = resp.choices[0]
        finish_reason = choice.finish_reason
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
        } if resp.usage else {}
        tool_calls = choice.message.tool_calls or []
        raw_args = tool_calls[0].function.arguments if tool_calls else ""

    try:
        tool_input = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        tool_input = {}

    return {
        "tool_input": tool_input,
        "raw_args": raw_args,
        "meta": {
            "model": chosen_model,
            "finish_reason": finish_reason,
            **usage,
        },
    }
