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
from typing import Any, Dict, List, Type

from .base import Agent


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
            "custo para empresas brasileiras. Sua tarefa é extrair CCs com toda a "
            "hierarquia disponível (Tipo, Gerência, Diretoria, níveis N1-N5).\n\n"
            "Regras de ouro:\n"
            "1. CC_COD é obrigatório e deve ser o código reduzido (único por CC).\n"
            "2. CC_CLASS, quando existe, é o código de classificação hierárquica "
            "(ex.: '01.01.001') que codifica os níveis. Preserve o formato original.\n"
            "3. Para CCs hierárquicos (ex.: '001.001.002'), derive automaticamente "
            "CC_N1_COD..CC_N5_COD quebrando pelo ponto. CC_N1_DESC..CC_N5_DESC use o "
            "nome do nó pai se disponível na mesma tabela ou em outra seção do documento.\n"
            "4. TIPO, GERENCIA, DIRETORIA: preencha se houver informação explícita. "
            "Nunca invente. Se não houver, deixe vazio e anote em notes.\n"
            "5. Cada CC deve aparecer UMA só vez. Se o mesmo CC_COD aparecer em "
            "múltiplas filiais (Omie replica), consolide e registre em notes.\n"
            "6. Ignore linhas que são apenas cabeçalhos de hierarquia (linhas sem "
            "CC_COD reduzido, apenas com código estruturado de nível superior)."
        )

    def extract_instructions(self) -> str:
        return (
            "Procure no documento:\n"
            "- Colunas como 'Centro de Custo', 'CC', 'Department', 'Departamento', "
            "'Cost Center', 'Código CC'\n"
            "- Hierarquia: Diretoria > Gerência > Área > CC\n"
            "- Códigos pontuados (ex.: 001.001.002) indicam hierarquia\n"
            "- Colunas 'Tipo' (Administrativo, Produção, etc.) e 'Gerência'\n\n"
            "Se o documento tem estrutura hierárquica implícita (níveis em colunas "
            "separadas), consolide na linha do CC folha, preenchendo CC_N1..CC_N5."
        )

    def custom_validations(self, records: List[Dict[str, Any]]) -> List[str]:
        issues: List[str] = []

        for i, rec in enumerate(records, 1):
            cc_class = str(rec.get("CC_CLASS", "")).strip()
            if cc_class and "." in cc_class:
                parts = cc_class.split(".")
                for level_idx, level_part in enumerate(parts[:5], 1):
                    expected_key = ".".join(parts[:level_idx])
                    n_cod = str(rec.get(f"CC_N{level_idx}_COD", "")).strip()
                    if n_cod and n_cod != expected_key:
                        issues.append(
                            f"Registro #{i} (CC_COD={rec.get('CC_COD')}): "
                            f"CC_N{level_idx}_COD='{n_cod}' não bate com a quebra "
                            f"esperada '{expected_key}' de CC_CLASS='{cc_class}'."
                        )
                        break

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
            "planos de contas. Sua tarefa é extrair as contas ANALÍTICAS (folha da "
            "hierarquia, Tipo='A', que recebem lançamento) do documento.\n\n"
            "REGRA CRÍTICA — só extraia contas ANALÍTICAS:\n"
            "- Ignore contas SINTÉTICAS (Tipo='S', totalizadoras, agrupadoras como "
            "'ATIVO', 'ATIVO CIRCULANTE', 'CAIXA E EQUIVALENTES', 'BANCOS', etc.).\n"
            "- Contas sintéticas NÃO viram linhas do xlsx — elas aparecem APENAS nos "
            "campos CONTA_N1..CONTA_N5 das contas analíticas (como hierarquia pai).\n"
            "- Se a conta não tem subdivisão (é folha da árvore), ela é analítica e "
            "deve ser extraída.\n\n"
            "Outras regras:\n"
            "1. CONTA_CONTABIL_COD é obrigatório — código da conta analítica (ex.: "
            "1.1.1.01, 3010).\n"
            "2. CONTA_CONTABIL_CLASS: se o documento não tiver um código de "
            "classificação separado, use o mesmo valor de CONTA_CONTABIL_COD.\n"
            "3. NATUREZA_LANCAMENTO_COD: sempre 'D' (Devedora) ou 'C' (Credora). "
            "Ativo/Despesa/Custo → D; Passivo/PL/Receita → C. Contas redutoras "
            "((-) depreciação acumulada, (-) PECLD, etc.) têm natureza INVERSA ao grupo.\n"
            "4. HIERARQUIA — muito importante entender a diferença:\n"
            "   - CONTA_N{i}_COD: o CÓDIGO NUMÉRICO do nível pai (ex.: '1', '1.1', "
            "'1.1.1', obtido quebrando o código da conta analítica pelo '.').\n"
            "   - CONTA_N{i}_DESC: a DESCRIÇÃO/NOME do nível pai (ex.: 'ATIVO', "
            "'ATIVO CIRCULANTE', 'CAIXA E EQUIVALENTES').\n"
            "   NUNCA coloque a descrição no campo _COD. NUNCA coloque o código no "
            "campo _DESC. Exemplo para a conta analítica '1.1.1.01 — Caixa Geral Matriz':\n"
            "     CONTA_N1_COD='1', CONTA_N1_DESC='ATIVO'\n"
            "     CONTA_N2_COD='1.1', CONTA_N2_DESC='ATIVO CIRCULANTE'\n"
            "     CONTA_N3_COD='1.1.1', CONTA_N3_DESC='CAIXA E EQUIVALENTES DE CAIXA'\n"
            "5. DRE_N1_COD/DESC: preencha quando o documento indicar a linha da DRE. "
            "Caso contrário, deixe vazio.\n"
            "6. PACOTE: só se o documento explicitar um agrupador Handit. Senão, vazio.\n"
            "7. Deduplicar por CONTA_CONTABIL_COD."
        )

    def extract_instructions(self) -> str:
        return (
            "Procure no documento:\n"
            "- Colunas/indicações como 'Tipo' (S=Sintética, A=Analítica). Use para "
            "filtrar: só extraia as linhas com Tipo='A'.\n"
            "- Estrutura hierárquica: Grupo (1 dígito) > Subgrupo (2 dígitos) > "
            "Sintética (3+ dígitos) > Analítica (4+ dígitos, normalmente com código "
            "mais longo que a sintética pai).\n"
            "- Códigos pontuados (ex.: 1.1.1.01) indicam profundidade hierárquica. "
            "A última parte do código costuma ser a analítica.\n"
            "- Para cada conta analítica, preencha os CONTA_N*_COD com os prefixos "
            "do código (quebras por ponto) e CONTA_N*_DESC com os nomes das contas "
            "sintéticas pais (buscando no próprio documento).\n\n"
            "Se o documento tiver centenas de contas analíticas, extraia TODAS. Se "
            "exceder o limite de output, registre em `notes` quantas ficaram de fora."
        )

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
        # Em vez de reportar linha por linha, consolida num único alerta.
        code_pattern = re.compile(r"^[\d.]+$")
        swapped_count = 0
        first_sample = None
        for i, rec in enumerate(records, 1):
            cod = str(rec.get("CONTA_CONTABIL_COD", "")).strip()
            if not (code_pattern.match(cod) and "." in cod):
                continue
            parts = cod.split(".")
            for level_idx in range(1, min(len(parts), 5) + 1):
                expected = ".".join(parts[:level_idx])
                n_cod = str(rec.get(f"CONTA_N{level_idx}_COD", "")).strip()
                # Ignora vazio (já tratado pela diretriz de omitir campos vazios)
                if not n_cod:
                    continue
                # Se o campo _COD tem letras, provavelmente é descrição (swap)
                if not code_pattern.match(n_cod):
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
