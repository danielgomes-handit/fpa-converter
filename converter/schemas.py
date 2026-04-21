"""Definição das 4 estruturas oficiais de carga do FP&A Base."""

from dataclasses import dataclass
from typing import List


@dataclass
class FieldSpec:
    name: str
    required: bool
    description: str
    format_hint: str = ""


@dataclass
class StructureSpec:
    id: str
    label: str
    fields: List[FieldSpec]

    @property
    def required_fields(self) -> List[str]:
        return [f.name for f in self.fields if f.required]

    @property
    def all_fields(self) -> List[str]:
        return [f.name for f in self.fields]


ESTRUTURA_EMPRESARIAL = StructureSpec(
    id="estrutura_empresarial",
    label="Estrutura Empresarial",
    fields=[
        FieldSpec("FILIAL_COD", True, "Código da Filial", "texto ou número"),
        FieldSpec("FILIAL_DESC", True, "Nome da Filial", "texto"),
        FieldSpec("EMPRESA_COD", True, "Código da Empresa", "texto ou número"),
        FieldSpec("EMPRESA_DESC", True, "Nome da Empresa", "texto"),
    ],
)


CENTRO_DE_CUSTO = StructureSpec(
    id="centro_de_custo",
    label="Centro de Custo",
    fields=[
        FieldSpec("CC_COD", True, "Código reduzido do CC"),
        FieldSpec("CC_CLASS", False, "Código de classificação (ex.: 01.01.001)"),
        FieldSpec("CC_DESC", True, "Descrição do CC"),
        FieldSpec("TIPO_COD", False, "Código do tipo"),
        FieldSpec("TIPO_DESC", False, "Descrição do tipo"),
        FieldSpec("GERENCIA_COD", False, "Código da gerência"),
        FieldSpec("GERENCIA_DESC", False, "Descrição da gerência"),
        FieldSpec("DIRETORIA_COD", False, "Código da diretoria"),
        FieldSpec("DIRETORIA_DESC", False, "Descrição da diretoria"),
        FieldSpec("CC_N1_COD", False, "Nível 1 - código"),
        FieldSpec("CC_N1_DESC", False, "Nível 1 - descrição"),
        FieldSpec("CC_N2_COD", False, "Nível 2 - código"),
        FieldSpec("CC_N2_DESC", False, "Nível 2 - descrição"),
        FieldSpec("CC_N3_COD", False, "Nível 3 - código"),
        FieldSpec("CC_N3_DESC", False, "Nível 3 - descrição"),
        FieldSpec("CC_N4_COD", False, "Nível 4 - código"),
        FieldSpec("CC_N4_DESC", False, "Nível 4 - descrição"),
        FieldSpec("CC_N5_COD", False, "Nível 5 - código"),
        FieldSpec("CC_N5_DESC", False, "Nível 5 - descrição"),
    ],
)


PLANO_DE_CONTAS = StructureSpec(
    id="plano_de_contas",
    label="Plano de Contas",
    fields=[
        FieldSpec("CONTA_CONTABIL_COD", True, "Código reduzido da conta"),
        FieldSpec("CONTA_CONTABIL_CLASS", False, "Código de classificação"),
        FieldSpec("CONTA_CONTABIL_DESC", True, "Descrição da conta"),
        FieldSpec("NATUREZA_LANCAMENTO_COD", False, "D (Devedora) ou C (Credora)"),
        FieldSpec("NATUREZA_LANCAMENTO_DESC", False, "Devedora ou Credora"),
        FieldSpec("PACOTE_COD", False, "Agrupador Handit (opcional)"),
        FieldSpec("PACOTE_DESC", False, "Descrição do pacote"),
        FieldSpec("DRE_N1_COD", False, "Código da linha DRE"),
        FieldSpec("DRE_N1_DESC", False, "Descrição da linha DRE"),
        FieldSpec("CONTA_N1_COD", False, "Nível 1 - código"),
        FieldSpec("CONTA_N1_DESC", False, "Nível 1 - descrição"),
        FieldSpec("CONTA_N2_COD", False, "Nível 2 - código"),
        FieldSpec("CONTA_N2_DESC", False, "Nível 2 - descrição"),
        FieldSpec("CONTA_N3_COD", False, "Nível 3 - código"),
        FieldSpec("CONTA_N3_DESC", False, "Nível 3 - descrição"),
        FieldSpec("CONTA_N4_COD", False, "Nível 4 - código"),
        FieldSpec("CONTA_N4_DESC", False, "Nível 4 - descrição"),
        FieldSpec("CONTA_N5_COD", False, "Nível 5 - código"),
        FieldSpec("CONTA_N5_DESC", False, "Nível 5 - descrição"),
    ],
)


RAZAO_CONTABIL = StructureSpec(
    id="razao_contabil",
    label="Razão Contábil",
    fields=[
        FieldSpec("DATA_LANCAMENTO", True, "Data do lançamento", "DD/MM/AAAA"),
        FieldSpec("FILIAL_COD", True, "Código da filial"),
        FieldSpec("CC_COD", True, "Código do CC (usar 0 quando não houver)"),
        FieldSpec("CONTA_CONTABIL_COD", True, "Código da conta contábil"),
        FieldSpec("NATUREZA_LANCAMENTO", False, "D ou C"),
        FieldSpec("VALOR_LANCAMENTO", True, "Valor positivo com 2 casas decimais"),
        FieldSpec("LOTE_LANCAMENTO", False, "Lote contábil"),
        FieldSpec("NUMERO_LANCAMENTO", False, "Número do lançamento"),
        FieldSpec("SEQUENCIA_LANCAMENTO", False, "Sequência"),
        FieldSpec("HISTORICO_LANCAMENTO", False, "Descritivo"),
        FieldSpec("FOR_CLI_DESC", False, "Fornecedor ou cliente"),
        FieldSpec("UNIDADE_NEGOCIO", False, "Unidade de negócio"),
        FieldSpec("ORIGEM", False, "Módulo de origem"),
        FieldSpec("CONTA_CONTABIL_DEB", False, "Conta débito (partida dobrada)"),
        FieldSpec("CONTA_CONTABIL_CRE", False, "Conta crédito (partida dobrada)"),
        FieldSpec("CC_DEB", False, "CC débito (partida dobrada)"),
        FieldSpec("CC_CRE", False, "CC crédito (partida dobrada)"),
        FieldSpec("ITEM_CONTABIL_DEB", False, "Item contábil débito"),
        FieldSpec("ITEM_CONTABIL_CRE", False, "Item contábil crédito"),
        FieldSpec("ITEM_CONTABIL", False, "Item contábil"),
    ],
)


ALL_STRUCTURES = [
    ESTRUTURA_EMPRESARIAL,
    CENTRO_DE_CUSTO,
    PLANO_DE_CONTAS,
    RAZAO_CONTABIL,
]


def get_structure(structure_id: str) -> StructureSpec:
    for s in ALL_STRUCTURES:
        if s.id == structure_id:
            return s
    raise ValueError(f"Estrutura desconhecida: {structure_id}")
