"""Agentes especializados: Estrutura Empresarial, Centro de Custo, Plano de
Contas e Razão Contábil.

Cada agente tem:
- System prompt focado na sua estrutura
- Instruções de extração detalhadas (com regras específicas)
- Validações customizadas além das básicas (duplicatas, obrigatórios)
- key_field para deduplicação
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Type

from .base import Agent


# =============================================================================
# Utilitário compartilhado: detecção de separador hierárquico
# =============================================================================

def _detect_separator(codes: List[str]) -> str:
    """Detecta o separador hierárquico majoritário ('.', '-', '/').

    Retorna '' se nenhum candidato aparecer em pelo menos 30% dos códigos
    (caso de códigos planos como '3010', '4020').
    """
    candidates = [".", "-", "/"]
    scores: Dict[str, int] = {c: 0 for c in candidates}
    valid_codes = [c for c in codes if c]
    if not valid_codes:
        return "."
    for cod in valid_codes:
        for sep in candidates:
            if sep in cod:
                scores[sep] += 1
    best_sep = max(candidates, key=lambda s: (scores[s], -candidates.index(s)))
    if scores[best_sep] >= max(1, len(valid_codes) * 0.3):
        return best_sep
    return ""


def _rebuild_hierarchy(
    records: List[Dict[str, Any]],
    code_field: str,
    desc_field: str,
    n_field_prefix: str,
    levels: int = 5,
) -> List[Dict[str, Any]]:
    """Filtra sintéticos + reconstrói N1..N{levels} usando o código hierárquico.

    Args:
        records: lista de registros (sintéticos + analíticos)
        code_field: nome do campo com código hierárquico (ex: 'CONTA_CONTABIL_COD',
            'CC_CLASS', 'CC_COD')
        desc_field: nome do campo de descrição (ex: 'CONTA_CONTABIL_DESC', 'CC_DESC')
        n_field_prefix: prefixo dos campos N (ex: 'CONTA_N' ou 'CC_N')
        levels: profundidade da hierarquia (default 5)

    Retorna lista filtrada com hierarquia reconstruída.
    """
    code_pattern = re.compile(r"^[\w.\-/]+$")
    sep = _detect_separator([
        str(r.get(code_field, "")).strip() for r in records
    ])

    code_to_desc: Dict[str, str] = {}
    all_codes: set = set()
    for rec in records:
        cod = str(rec.get(code_field, "")).strip()
        desc = str(rec.get(desc_field, "")).strip()
        if not cod:
            continue
        all_codes.add(cod)
        if desc and desc != cod:
            code_to_desc[cod] = desc

    def _is_synthetic(code: str) -> bool:
        if not code or not sep:
            return False
        prefix = code + sep
        return any(other.startswith(prefix) for other in all_codes if other != code)

    processed: List[Dict[str, Any]] = []
    for rec in records:
        cod = str(rec.get(code_field, "")).strip()
        if not cod or _is_synthetic(cod):
            continue

        for level in range(1, levels + 1):
            rec[f"{n_field_prefix}{level}_COD"] = ""
            rec[f"{n_field_prefix}{level}_DESC"] = ""

        if sep and code_pattern.match(cod) and sep in cod:
            parts = cod.split(sep)
            for level in range(1, levels + 1):
                if level <= len(parts):
                    prefix = sep.join(parts[:level])
                    rec[f"{n_field_prefix}{level}_COD"] = prefix
                    if prefix in code_to_desc:
                        rec[f"{n_field_prefix}{level}_DESC"] = code_to_desc[prefix]

        for level in range(1, levels + 1):
            c = str(rec.get(f"{n_field_prefix}{level}_COD", "")).strip()
            d = str(rec.get(f"{n_field_prefix}{level}_DESC", "")).strip()
            if c and d == c:
                rec[f"{n_field_prefix}{level}_DESC"] = ""

        processed.append(rec)

    return processed


# =============================================================================
# Estrutura Empresarial
# =============================================================================

class EmpresaAgent(Agent):
    structure_id = "estrutura_empresarial"

    def key_field(self) -> str:
        return "FILIAL_COD"

    def system_prompt(self) -> str:
        return (
            "Você é um especialista em cadastros societários e estrutura organizacional "
            "de empresas brasileiras. Sua tarefa é extrair a estrutura empresarial "
            "(empresas + filiais) de documentos financeiros.\n\n"
            "Regras de ouro:\n"
            "1. Cada linha representa UMA filial vinculada a UMA empresa.\n"
            "2. Se o documento traz apenas empresas (ex.: holding com SPEs), trate cada "
            "SPE como FILIAL e pergunte o EMPRESA_COD/DESC no campo notes (não invente).\n"
            "3. FILIAL_COD e EMPRESA_COD devem ser texto curto (sigla ou número). "
            "FILIAL_DESC e EMPRESA_DESC devem ser nome completo/razão social.\n"
            "4. Evite duplicar. Se a mesma filial aparece múltiplas vezes, consolide em uma linha.\n"
            "5. Os 4 campos são OBRIGATÓRIOS. Se algum não estiver no documento, "
            "deixe em branco e registre em notes para o usuário preencher manualmente."
        )

    def extract_instructions(self) -> str:
        return (
            "Procure no documento referências a:\n"
            "- Razão social, CNPJ, nome fantasia de empresas\n"
            "- Siglas de filiais, SPEs, unidades de negócio, estabelecimentos\n"
            "- Relação hierárquica entre holding/matriz e filiais/SPEs\n\n"
            "Se o documento só lista siglas (ex.: 'DV, AS, BRASILIN'), entenda "
            "cada uma como uma filial e retorne com EMPRESA_COD/DESC vazios."
        )

    def custom_validations(self, records: List[Dict[str, Any]]) -> List[str]:
        issues: List[str] = []
        for i, rec in enumerate(records, 1):
            filial_cod = str(rec.get("FILIAL_COD", "")).strip()
            empresa_cod = str(rec.get("EMPRESA_COD", "")).strip()
            if len(filial_cod) > 20:
                issues.append(
                    f"Registro #{i}: FILIAL_COD parece ser um nome completo "
                    f"({len(filial_cod)} chars). Deveria ser um código curto."
                )
            if len(empresa_cod) > 20:
                issues.append(
                    f"Registro #{i}: EMPRESA_COD parece ser um nome completo "
                    f"({len(empresa_cod)} chars). Deveria ser um código curto."
                )
        return issues


# =============================================================================
# Centro de Custo
# =============================================================================

class CentroDeCustoAgent(Agent):
    structure_id = "centro_de_custo"

    def key_field(self) -> str:
        return "CC_COD"

    def system_prompt(self) -> str:
        return (
            "Você é um especialista em controladoria e estruturação de centros de "
            "custo para empresas brasileiras. Sua tarefa é extrair o cadastro "
            "completo de CCs (tanto agrupadores/sintéticos quanto analíticos).\n\n"
            "IMPORTANTE — extraia TODOS os CCs (agrupadores + analíticos):\n"
            "- CCs AGRUPADORES (sintéticos, totalizadores como 'DIRETORIAS', "
            "'COMERCIAL', 'OPERAÇÕES') → EXTRAIA como linhas normais.\n"
            "- CCs ANALÍTICOS (folha da hierarquia, recebem lançamento) → EXTRAIA "
            "como linhas normais.\n"
            "- Um pós-processamento automático vai remover os agrupadores do arquivo "
            "final e usar suas descrições para preencher CC_N1..CC_N5 dos analíticos. "
            "Por isso precisamos de TODOS no retorno.\n\n"
            "Regras por campo:\n"
            "1. CC_COD: código do CC (obrigatório). Se houver código reduzido único, "
            "use ele. Se o cliente só usa código hierárquico (001.001.002), use esse.\n"
            "2. CC_DESC: NOME do CC (obrigatório). NUNCA coloque o código aqui.\n"
            "3. CC_CLASS: código hierárquico/de classificação (ex.: '01.01.001'). "
            "Pode ser igual ao CC_COD se o cliente não tiver código separado. "
            "Preserve o formato original (ponto, hífen ou barra).\n"
            "4. TIPO, GERENCIA, DIRETORIA: preencha se houver informação explícita. "
            "NUNCA invente. Se não houver, deixe vazio.\n"
            "5. CC_N1..N5 (COD e DESC): você NÃO precisa preencher. O "
            "pós-processamento reconstrói a hierarquia automaticamente. Deixe vazios.\n"
            "6. Deduplicar por CC_COD."
        )

    def extract_instructions(self) -> str:
        return (
            "Procure no documento TODAS as linhas de centros de custo:\n"
            "- Colunas como 'Centro de Custo', 'CC', 'Department', 'Departamento', "
            "'Cost Center', 'Código CC', 'Classificação'.\n"
            "- Estrutura hierárquica: Diretoria > Gerência > Área > CC.\n"
            "- Códigos pontuados/hifenizados (ex.: '001.001.002', '01-02-003') "
            "indicam profundidade. Mantenha o formato original.\n"
            "- Para cada CC, preencha CC_COD, CC_DESC e (quando possível) CC_CLASS, "
            "TIPO, GERENCIA, DIRETORIA. Os campos CC_N1..N5 ficam VAZIOS — o "
            "pós-processamento reconstrói.\n\n"
            "Extraia TODOS os CCs, sem filtrar agrupadores."
        )

    def extra_chunk_instruction(self) -> str:
        return (
            "⚠️ REFORÇO SOBRE AGRUPADORES (importante):\n"
            "Em CADA parte do documento que processar, SEMPRE inclua como linhas "
            "do CSV os CCs agrupadores (totalizadores) que sejam pais dos CCs "
            "analíticos dessa parte. Sem isso, a hierarquia CC_N1..N5 não pode ser "
            "reconstruída com os nomes corretos.\n\n"
            "Não tem problema repetir entre chunks: a deduplicação é automática."
        )

    def post_process(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pós-processa o cadastro de CCs.

        1. Decide qual campo usar como código hierárquico:
           - Se CC_CLASS estiver preenchido em pelo menos 50% dos registros, usa CC_CLASS.
           - Senão, usa CC_COD.
        2. Filtra agrupadores (CCs cujo código é prefixo de outro).
        3. Reconstrói CC_N1..N5 (COD + DESC).
        """
        if not records:
            return records

        non_empty_class = sum(
            1 for r in records if str(r.get("CC_CLASS", "")).strip()
        )
        use_class = non_empty_class >= max(1, len(records) * 0.5)
        code_field = "CC_CLASS" if use_class else "CC_COD"

        processed = _rebuild_hierarchy(
            records,
            code_field=code_field,
            desc_field="CC_DESC",
            n_field_prefix="CC_N",
            levels=5,
        )

        # CC_CLASS: se vazio, usa o próprio CC_COD (compatível com formato Handit)
        for rec in processed:
            cc_cod = str(rec.get("CC_COD", "")).strip()
            if cc_cod and not str(rec.get("CC_CLASS", "")).strip():
                rec["CC_CLASS"] = cc_cod

        return processed

    def custom_validations(self, records: List[Dict[str, Any]]) -> List[str]:
        issues: List[str] = []

        for i, rec in enumerate(records, 1):
            cc_cod = str(rec.get("CC_COD", "")).strip()
            if cc_cod and " " in cc_cod:
                issues.append(
                    f"Registro #{i}: CC_COD='{cc_cod}' contém espaços. "
                    "Deve ser código contínuo sem espaços."
                )

        return issues


# =============================================================================
# Plano de Contas
# =============================================================================

class PlanoDeContasAgent(Agent):
    structure_id = "plano_de_contas"

    def key_field(self) -> str:
        return "CONTA_CONTABIL_COD"

    def system_prompt(self) -> str:
        return (
            "Você é um especialista em contabilidade brasileira e estruturação de "
            "planos de contas. Sua tarefa é extrair o plano de contas completo "
            "(tanto contas SINTÉTICAS quanto ANALÍTICAS) do documento.\n\n"
            "IMPORTANTE — extraia TODAS as contas (sintéticas + analíticas):\n"
            "- Contas SINTÉTICAS (Tipo='S', totalizadoras, agrupadoras como 'ATIVO', "
            "'ATIVO CIRCULANTE', 'BANCOS', etc.) → EXTRAIA como linhas normais.\n"
            "- Contas ANALÍTICAS (Tipo='A', folha da hierarquia, que recebem lançamento) "
            "→ EXTRAIA como linhas normais.\n"
            "- Um pós-processamento automático vai remover as sintéticas do arquivo "
            "final e usar suas descrições para preencher a hierarquia das analíticas. "
            "Por isso precisamos de TODAS no retorno.\n\n"
            "Regras por campo:\n"
            "1. CONTA_CONTABIL_COD é obrigatório — código numérico/pontuado da conta "
            "(ex.: '1', '1.1', '1.1.1', '1.1.1.01', '3010').\n"
            "2. CONTA_CONTABIL_DESC é obrigatório — NOME da conta (ex.: 'ATIVO', "
            "'ATIVO CIRCULANTE', 'Caixa Geral - Matriz'). NUNCA coloque o código aqui.\n"
            "3. CONTA_CONTABIL_CLASS: se o documento não tiver um código de "
            "classificação separado, use o mesmo valor de CONTA_CONTABIL_COD.\n"
            "4. NATUREZA_LANCAMENTO_COD: 'D' (Devedora) ou 'C' (Credora). "
            "Ativo/Despesa/Custo → D; Passivo/PL/Receita → C. Contas redutoras "
            "((-) depreciação acumulada, (-) PECLD, etc.) têm natureza INVERSA ao grupo. "
            "Para sintéticas, pode deixar vazio se não souber.\n"
            "5. CONTA_N1..N5 (COD e DESC): você NÃO precisa preencher. O "
            "pós-processamento reconstrói a hierarquia automaticamente a partir do "
            "código (quebra por ponto) e das descrições das sintéticas. Deixe vazios.\n"
            "6. DRE_N1_COD/DESC: preencha quando o documento indicar a linha da DRE. "
            "Caso contrário, deixe vazio.\n"
            "7. PACOTE: só se o documento explicitar um agrupador Handit. Senão, vazio.\n"
            "8. Deduplicar por CONTA_CONTABIL_COD.\n\n"
            "EXEMPLO do que extrair (para um plano com 'ATIVO > ATIVO CIRCULANTE > "
            "CAIXA > Caixa Geral Matriz'):\n"
            "  Linha 1: COD='1',        DESC='ATIVO',                 NATUREZA='D'\n"
            "  Linha 2: COD='1.1',      DESC='ATIVO CIRCULANTE',      NATUREZA='D'\n"
            "  Linha 3: COD='1.1.1',    DESC='CAIXA E EQUIVALENTES',  NATUREZA='D'\n"
            "  Linha 4: COD='1.1.1.01', DESC='Caixa Geral - Matriz',  NATUREZA='D'\n"
            "O pós-processamento filtra automaticamente as linhas 1-3 (sintéticas) e "
            "popula CONTA_N1_DESC='ATIVO', CONTA_N2_DESC='ATIVO CIRCULANTE', etc. na linha 4."
        )

    def extract_instructions(self) -> str:
        return (
            "Procure no documento TODAS as contas do plano (sintéticas + analíticas):\n"
            "- Colunas/indicações como 'Tipo' (S=Sintética, A=Analítica), 'Classificação', "
            "'Código' e 'Descrição/Nome'. Traga TODAS as linhas, não filtre por Tipo.\n"
            "- Estrutura hierárquica: Grupo (1 dígito) > Subgrupo (2 dígitos) > "
            "Sintética (3+ dígitos) > Analítica (4+ dígitos). Todos os níveis devem "
            "aparecer como linhas separadas.\n"
            "- Códigos pontuados (ex.: 1.1.1.01) indicam profundidade. Mantenha o "
            "formato original do código.\n"
            "- Para cada conta, só preencha CONTA_CONTABIL_COD, CONTA_CONTABIL_DESC e "
            "(quando possível) NATUREZA_LANCAMENTO_COD + DRE_N1_COD/DESC. Os campos "
            "CONTA_N1..N5 ficam VAZIOS — o pós-processamento reconstrói.\n\n"
            "Se o documento tiver centenas de contas, extraia TODAS. Se exceder o "
            "limite de output, registre em `notes` quantas ficaram de fora."
        )

    def extra_chunk_instruction(self) -> str:
        return (
            "⚠️ REFORÇO SOBRE SINTÉTICAS (muito importante):\n"
            "Em CADA parte/chunk do documento que você processar, SEMPRE inclua como "
            "linhas do CSV as contas sintéticas (totalizadoras) que sejam pais das "
            "contas analíticas dessa parte — mesmo que você ache que já mandou em "
            "outra parte. Não tem problema repetir: a deduplicação é automática.\n\n"
            "Exemplo: se esta parte tem as analíticas '1.1.2.01 Banco X' e "
            "'1.1.2.02 Banco Y', você DEVE também incluir as linhas:\n"
            "  1,ATIVO,...\n"
            "  1.1,ATIVO CIRCULANTE,...\n"
            "  1.1.2,BANCOS - CONTA MOVIMENTO,...\n"
            "  1.1.2.01,Banco X,...\n"
            "  1.1.2.02,Banco Y,...\n\n"
            "Sem as linhas das sintéticas, a hierarquia CONTA_N1..N5 não consegue "
            "ser reconstruída com os nomes corretos. Se o documento não mostra o "
            "nome da sintética pai, deixe a DESC vazia (não invente), mas mande a "
            "linha com o código mesmo assim."
        )

    def post_process(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pós-processamento determinístico após extração do Claude.

        Estratégia: o Claude extrai TODAS as contas (sintéticas + analíticas).
        Aqui filtramos as sintéticas e reconstruímos CONTA_N1..N5 a partir do
        código da analítica + descrições coletadas.
        """
        processed = _rebuild_hierarchy(
            records,
            code_field="CONTA_CONTABIL_COD",
            desc_field="CONTA_CONTABIL_DESC",
            n_field_prefix="CONTA_N",
            levels=5,
        )
        # CONTA_CONTABIL_CLASS: se vazio, usa o próprio COD
        for rec in processed:
            cod = str(rec.get("CONTA_CONTABIL_COD", "")).strip()
            if cod and not str(rec.get("CONTA_CONTABIL_CLASS", "")).strip():
                rec["CONTA_CONTABIL_CLASS"] = cod
        return processed

    def custom_validations(self, records: List[Dict[str, Any]]) -> List[str]:
        issues: List[str] = []

        for i, rec in enumerate(records, 1):
            nat = str(rec.get("NATUREZA_LANCAMENTO_COD", "")).strip().upper()
            if nat and nat not in {"D", "C"}:
                issues.append(
                    f"Registro #{i} (conta={rec.get('CONTA_CONTABIL_COD')}): "
                    f"NATUREZA_LANCAMENTO_COD='{nat}' inválido. Deve ser 'D' ou 'C'."
                )

        for i, rec in enumerate(records, 1):
            desc_upper = str(rec.get("CONTA_CONTABIL_DESC", "")).upper()
            dre_desc = str(rec.get("DRE_N1_DESC", "")).upper()
            nat = str(rec.get("NATUREZA_LANCAMENTO_COD", "")).strip().upper()
            combined = f"{desc_upper} {dre_desc}"

            expected = None
            if any(w in combined for w in ["DESPESA", "CUSTO", "DEDUÇÃO", "DEDUCAO"]):
                expected = "D"
            elif any(w in combined for w in ["RECEITA", "PATRIMÔNIO", "PATRIMONIO", "PASSIVO"]):
                expected = "C"

            if "(-)" in desc_upper or "PECLD" in desc_upper or "ACUMULADA" in desc_upper:
                continue

            if expected and nat and nat != expected:
                issues.append(
                    f"Registro #{i} ({rec.get('CONTA_CONTABIL_COD')} - "
                    f"{rec.get('CONTA_CONTABIL_DESC')}): natureza '{nat}' pode "
                    f"estar inconsistente com a descrição (esperado '{expected}')."
                )

        # Detecta se o Claude trocou _COD por _DESC (colocou descrição no campo de código).
        # Usa o separador detectado nos próprios dados.
        sep = _detect_separator([
            str(r.get("CONTA_CONTABIL_COD", "")).strip() for r in records
        ])
        code_pattern = re.compile(r"^[\w.\-/]+$")
        swapped_count = 0
        first_sample = None
        for i, rec in enumerate(records, 1):
            cod = str(rec.get("CONTA_CONTABIL_COD", "")).strip()
            if not (sep and code_pattern.match(cod) and sep in cod):
                continue
            parts = cod.split(sep)
            for level_idx in range(1, min(len(parts), 5) + 1):
                expected = sep.join(parts[:level_idx])
                n_cod = str(rec.get(f"CONTA_N{level_idx}_COD", "")).strip()
                if not n_cod:
                    continue
                # Se o campo _COD tem só letras (sem dígitos), é descrição (swap)
                if not any(ch.isdigit() for ch in n_cod):
                    swapped_count += 1
                    if first_sample is None:
                        first_sample = (
                            f"ex.: conta {cod} → CONTA_N{level_idx}_COD='{n_cod}' "
                            f"(esperado '{expected}')"
                        )
                    break

        if swapped_count > 0:
            issues.append(
                f"{swapped_count} registros têm descrição em CONTA_N*_COD em vez do "
                f"código numérico. {first_sample}. Verifique a hierarquia no xlsx final."
            )

        return issues


# =============================================================================
# Razão Contábil
# =============================================================================

class RazaoContabilAgent(Agent):
    structure_id = "razao_contabil"

    def key_field(self) -> str:
        return ""

    def system_prompt(self) -> str:
        return (
            "Você é um especialista em razão contábil e escrituração de movimentos "
            "financeiros brasileiros. Sua tarefa é extrair lançamentos contábeis "
            "mantendo integridade de datas, valores e naturezas.\n\n"
            "Regras de ouro:\n"
            "1. DATA_LANCAMENTO no formato DD/MM/AAAA. Converta qualquer outro "
            "formato de data (ex.: 2024-11-05 → 05/11/2024).\n"
            "2. FILIAL_COD, CC_COD, CONTA_CONTABIL_COD, VALOR_LANCAMENTO são OBRIGATÓRIOS.\n"
            "3. VALOR_LANCAMENTO sempre POSITIVO com duas casas decimais (ex.: 1000.43). "
            "Use abs() se o documento traz valores negativos.\n"
            "4. NATUREZA_LANCAMENTO: 'D' ou 'C'. Regra de inferência:\n"
            "   - Se documento tem 'Tipo do Movimento': Saída→D, Entrada→C, Pagamento→D, Recebimento→C.\n"
            "   - Se valor tem sinal: negativo→D, positivo→C.\n"
            "   - Se documento tem débito/crédito explícito: siga o documento.\n"
            "5. Se um lançamento não tem CC (ex.: movimento bancário sem departamento), "
            "use CC_COD='0' (padrão do FP&A Base para 'sem CC').\n"
            "6. HISTORICO_LANCAMENTO: preserve o texto original, truncando se maior que 500 chars.\n"
            "7. Campos de partida dobrada (CONTA_DEB, CONTA_CRE, CC_DEB, CC_CRE, "
            "ITEM_CONTABIL_*) só preencha se o documento for de fato partida dobrada. "
            "Razão de caixa (tipo Omie Movimentos) é monoentry — esses campos ficam vazios.\n"
            "8. UNIDADE_NEGOCIO: use 'Projeto' do Omie ou equivalente.\n"
            "9. ORIGEM: use 'Tipo do Movimento' ou módulo de origem do ERP.\n"
            "10. Extraia TODOS os lançamentos. Nunca sumarize ou agregue."
        )

    def extract_instructions(self) -> str:
        return (
            "Procure no documento:\n"
            "- Colunas típicas: Data, Valor, Débito/Crédito, Histórico, Conta, CC, Filial\n"
            "- Movimentos financeiros: Entradas/Saídas, Pagamentos/Recebimentos\n"
            "- Lançamentos contábeis: Data + Conta + Valor + Natureza\n"
            "- Extratos: Data + Descrição + Valor\n\n"
            "Para arquivos com muitos lançamentos (centenas/milhares), extraia TODOS. "
            "Se exceder o limite de tokens, extraia o máximo possível e registre em "
            "notes quantos ficaram de fora e em qual data parou."
        )

    def custom_validations(self, records: List[Dict[str, Any]]) -> List[str]:
        issues: List[str] = []
        date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")

        for i, rec in enumerate(records, 1):
            data = str(rec.get("DATA_LANCAMENTO", "")).strip()
            if data and not date_re.match(data):
                issues.append(
                    f"Registro #{i}: DATA_LANCAMENTO='{data}' fora do padrão DD/MM/AAAA."
                )

            nat = str(rec.get("NATUREZA_LANCAMENTO", "")).strip().upper()
            if nat and nat not in {"D", "C"}:
                issues.append(
                    f"Registro #{i}: NATUREZA_LANCAMENTO='{nat}' inválido (deve ser D ou C)."
                )

            valor = str(rec.get("VALOR_LANCAMENTO", "")).strip()
            if valor:
                try:
                    v = float(valor.replace(",", "."))
                    if v < 0:
                        issues.append(
                            f"Registro #{i}: VALOR_LANCAMENTO={v} é negativo. "
                            "Deve ser positivo (natureza indica débito/crédito)."
                        )
                except ValueError:
                    issues.append(
                        f"Registro #{i}: VALOR_LANCAMENTO='{valor}' não é um número válido."
                    )

        return issues


# =============================================================================
# Fábrica
# =============================================================================

_AGENT_REGISTRY: Dict[str, Type[Agent]] = {
    "estrutura_empresarial": EmpresaAgent,
    "centro_de_custo": CentroDeCustoAgent,
    "plano_de_contas": PlanoDeContasAgent,
    "razao_contabil": RazaoContabilAgent,
}


def get_agent_class(structure_id: str) -> Type[Agent]:
    """Retorna a classe do agente para uma estrutura dada."""
    if structure_id not in _AGENT_REGISTRY:
        raise ValueError(f"Não há agente registrado para estrutura '{structure_id}'.")
    return _AGENT_REGISTRY[structure_id]
