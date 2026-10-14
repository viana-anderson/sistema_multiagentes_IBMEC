"""
ETAPA 2 -- Extração estruturada do pedido (15 min) e 🆕 A -- votação em paralelo (OPCIONAL, bônus).

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 2.1 -- complete o modelo Pydantic `Pedido` (campos + Field(description=...))
  ETAPA 2.2 -- criar_extrator(): um Agent com output_type=Pedido
  ETAPA 2.3 -- extrair(): roda UM extrator e devolve um Pedido
  --- daqui para baixo é OPCIONAL (item 🆕 A, vale bônus). Pule se estiver sem tempo: o resto do sistema não depende dele.
  🆕 A.1    -- INSTRUCOES_VOTANTES: 3 instruções ligeiramente diferentes
  🆕 A.2    -- extrair_com_votacao(): os 3 extratores AO MESMO TEMPO (asyncio.gather)
  (PRONTO)  -- votar(): maioria por campo; sem maioria em tipo/datas -> divergencia=True
  (PRONTO)  -- no __main__: o tempo em paralelo x em sequência

REFERÊNCIAS NAS AULAS
  aula2/agente_output.py                   output_type com um BaseModel simples
  aula2/agente_output2.py                  Enum + listas + Field(description=...)          <- o mais parecido
  aula7/exemplos/08_paralelismo/main.py    🆕 A: o CONCEITO de paralelismo (lá: tarefas DIFERENTES para ganhar tempo;
                                           aqui: a MESMA tarefa 3 vezes para ganhar confiabilidade)
  aula3/agente_parada3.py                  Runner.run (assíncrono) dentro de asyncio, como em A.2
  aula3/agente_retry.py                    por que a data de hoje entra nas instruções (já feito abaixo, com texto_hoje())

Rodar:
    python etapa02_extracao.py            # extrai C1, C2, C5 e C11
    python etapa02_extracao.py --votacao  # 🆕 A: C1, C2 e C9 com 3 votos e o tempo medido

Pronto quando: C2 sai com dias_vendidos=10, C11 com tipo_destino="exterior", C5 com matricula=None;
               na votação, C1/C2 unânimes e C9 mostrando os votos.
"""
import asyncio
import sys
import time
from collections import Counter
from enum import Enum
import re

from agents import Agent, Runner
from pydantic import BaseModel, Field

from dados.casos import CASOS
from etapa04_ferramentas import texto_hoje
from provedor import configurar

MODELO = configurar()


class TipoPedido(str, Enum):
    FERIAS = "ferias"
    ABONO = "abono"
    DIARIA = "diaria"
    LICENCA_SAUDE = "licenca_saude"
    OUTRO = "outro"


class TipoDestino(str, Enum):
    CAPITAL = "capital"
    INTERIOR = "interior"
    EXTERIOR = "exterior"


class Pedido(BaseModel):
    # ETAPA 2.1 -- complete os campos. O primeiro já está pronto como modelo.
    #   matricula: str | None          (4 dígitos; None se o servidor não informou)
    #   data_inicio: str | None        (AAAA-MM-DD)
    #   data_fim: str | None           (AAAA-MM-DD; no abono, igual à data_inicio)
    #   dias_vendidos: int             (0 a 10; abono pecuniário, regra N2 -- use Field(default=0, ge=0, le=10, ...))
    #   destino: str | None            (só para diária: a cidade)
    #   tipo_destino: TipoDestino | None
    #   justificativa: str             (resumo do motivo, sem dados de saúde)
    #   Escreva a DESCRIPTION de cada um: é a "instrução" que o LLM lê para preencher o campo.
    #   Referência: aula2/agente_output2.py (Ocorrencia, Envolvido, PapelEnvolvido)
    tipo: TipoPedido = Field(description=(
        "Classifique a intenção principal do pedido. Use 'ferias' quando "
        "o servidor quiser tirar férias, mesmo que também queira vender dias. "
        "Use 'abono' quando quiser usar um dia de abono. "
        "Use 'diaria' quando mencionar viagem a serviço, congresso ou missão. "
        "Exemplo: 'Vou a serviço a Buenos Aires para um congresso' é diaria, "
        "não abono. Use 'licenca_saude' para afastamento por doença e 'outro' "
        "quando nenhuma categoria se aplicar."))
    
    matricula: str | None = Field(
        default=None,
        description=(
            "Matrícula do servidor com exatamente 4 dígitos, se informada "
            "no pedido. Se não estiver informada, use null. Não invente matrícula."))

    data_inicio: str | None = Field(
        default=None,
        description=(
            "Data inicial no formato AAAA-MM-DD. Converta DD/MM/AAAA para AAAA-MM-DD. "
            "Exemplo: 08/06/2027 deve resultar em 2027-06-08. "
            "Se o texto não informar uma data exata (apenas um mês, como 'em agosto de 2027'), "
            "não invente um dia: use null."))

    data_fim: str | None = Field(
        default=None,
        description=(
            "Data final no formato AAAA-MM-DD. Exemplo: 11/06/2027 deve resultar "
            "em 2027-06-11. Se o texto informar apenas um mês, sem dia inicial "
            "ou final exatos, use null. Em pedidos de abono com data definida, "
            "repita a data_inicio."))

    dias_vendidos: int = Field(
        default=0,
        ge=0,
        le=10,
        description=(
            "Quantidade de dias de férias que o servidor pediu explicitamente "
            "para vender, entre 0 e 10. Use 0 quando não houver pedido explícito "
            "de venda de dias. Não confunda dias de férias usufruídos com dias vendidos."))

    destino: str | None = Field(
        default=None,
        description=(
            "Nome da cidade de destino para pedidos de diária. Extraia o nome "
            "próprio da cidade, não a categoria geográfica. Exemplo: em "
            "'Vou a serviço a Buenos Aires', use 'Buenos Aires'."))

    tipo_destino: TipoDestino | None = Field(
        default=None,
        description=(
             "Classificação geográfica do destino de uma diária. Use 'exterior' "
            "para cidades fora do Brasil, como Buenos Aires, Argentina. Use "
            "'capital' para uma capital brasileira e 'interior' para outras "
            "localidades brasileiras. Buenos Aires deve ser classificada como "
            "exterior, nunca como interior."))

    justificativa: str = Field(
        description=(
            "Resumo breve do motivo do pedido. Não inclua diagnósticos, "
            "detalhes médicos nem outros dados de saúde. Se o motivo não "
            "for informado, registre que não foi informado."))

def menciona_apenas_mes(texto: str) -> bool:
    padrao = (
        r"\b(?:em|no mês de|durante o mês de)\s+"
        r"(janeiro|fevereiro|março|marco|abril|maio|junho|"
        r"julho|agosto|setembro|outubro|novembro|dezembro)"
        r"\s+(?:de\s+)?\d{4}\b"
    )
    return bool(re.search(padrao, texto, flags=re.IGNORECASE))

def criar_extrator(instrucoes: str, input_guardrails: list | None = None) -> Agent:
    # ETAPA 2.2 -- devolva Agent(name="Extrator", instructions=instrucoes, output_type=Pedido,
    #   input_guardrails=input_guardrails or [])
    #   (os guardrails só entram na Etapa 3; até lá, a lista fica vazia)
    return Agent(
        name="Extrator",
        instructions=instrucoes,
        output_type=Pedido,
        input_guardrails=input_guardrails or [],
    )


INSTRUCOES_EXTRATOR = (
    f"Hoje é {texto_hoje()}. "  # (PRONTO) a data real: o modelo não tem relógio (aula3/agente_retry.py)
    
    "VALORES AUSENTES: quando uma informação não estiver explícita no pedido, "
    "retorne null real no campo correspondente, sem aspas. Nunca escreva "
    "'null', 'None', explicações ou frases no lugar de um valor ausente. "
    "Não invente matrícula. A matrícula deve conter exatamente 4 dígitos. "

    "Retorne os dados no formato estruturado definido pelo modelo Pedido. "

    "Classifique o pedido como ferias, abono, diaria, licenca_saude ou outro. "
    "IMPORTANTE: quando o servidor mencionar viagem a serviço, viagem para "
    "congresso ou missão de trabalho, classifique como 'diaria', mesmo que "
    "não utilize literalmente a palavra diária. "
    "Exemplo: 'Vou a serviço a Buenos Aires de 08/06/2027 a 11/06/2027 "
    "para um congresso' deve ser classificado como 'diaria'. "
    "Não classifique viagem a serviço como 'outro'. "

    "Extraia a matrícula somente quando estiver explícita. "
    "Se não estiver informada, use null. "

    "ATENÇÃO ÀS DATAS: toda data preenchida deve estar no formato AAAA-MM-DD, "
    "com ano de quatro dígitos, mês de dois dígitos e dia de dois dígitos. "
    "Converta datas como 07/06/2027 para 2027-06-07. "
    "Nunca devolva datas no formato DD-MM-AA ou DD/MM/AAAA. "
    "Não invente datas; use null quando não houver informação suficiente. "

    "Em pedidos de abono, data_fim deve ser igual a data_inicio. "
    "Preencha dias_vendidos somente quando houver pedido explícito de venda "
    "de dias de férias. Caso contrário, use 0. O valor deve estar entre 0 e 10. "

    "Em pedidos de diária, destino deve conter o nome da cidade de destino, "
    "e não a classificação geográfica. Por exemplo, para uma viagem a Buenos Aires, "
    "destino='Buenos Aires' e tipo_destino='exterior'. "
    "Destinos fora do Brasil devem ser classificados como exterior, "
    "nunca como capital ou interior. "
    "Use capital ou interior somente para destinos no Brasil, quando for possível "
    "determinar essa classificação. "

    "A justificativa deve ser um resumo breve do motivo informado, sem dados de saúde. "
    "Se nenhum motivo for informado, use 'Motivo não informado'. "
    "Não invente informações que não constem no pedido."
)


def extrair(texto: str) -> Pedido:
    # ETAPA 2.3 -- rode criar_extrator(INSTRUCOES_EXTRATOR) com Runner.run_sync e devolva final_output
    #   (é um objeto Pedido, não texto!)
    agente = criar_extrator(INSTRUCOES_EXTRATOR)
    resultado = Runner.run_sync(agente, texto)
    pedido = resultado.final_output

    atualizacoes = {}

    # Pedidos que mencionam apenas um mês não devem receber datas inventadas.
    if menciona_apenas_mes(texto):
        atualizacoes["data_inicio"] = None
        atualizacoes["data_fim"] = None

    else:
        # Recupera datas explícitas no formato DD/MM/AAAA.
        datas = re.findall(
            r"\b(\d{2})/(\d{2})/(\d{4})\b",
            texto,
        )

        if len(datas) >= 2:
            dia, mes, ano = datas[0]
            atualizacoes["data_inicio"] = f"{ano}-{mes}-{dia}"

            dia, mes, ano = datas[1]
            atualizacoes["data_fim"] = f"{ano}-{mes}-{dia}"

        elif len(datas) == 1:
            dia, mes, ano = datas[0]
            data = f"{ano}-{mes}-{dia}"

            # Em pedidos de abono com uma data explícita,
            # início e fim correspondem ao mesmo dia.
            if pedido.tipo == TipoPedido.ABONO:
                atualizacoes["data_inicio"] = data
                atualizacoes["data_fim"] = data

    # Recupera a matrícula diretamente do texto original.
    correspondencia = re.search(
        r"\bmatrícula\s+(\d{4})\b",
        texto,
        flags=re.IGNORECASE,
    )

    atualizacoes["matricula"] = (
        correspondencia.group(1) if correspondencia else None
    )

    # Abono não representa venda de dias de férias.
    if pedido.tipo == TipoPedido.ABONO:
        atualizacoes["dias_vendidos"] = 0

    # Normaliza valores que o modelo pode devolver como texto.
    valores_nulos = {
        "", "null", "none", "not specified",
        "não informado", "nao informado",
        "não informada", "nao informada",
        "não fornecido", "nao fornecido",
    }

    for campo in ("data_inicio", "data_fim"):
        valor = getattr(pedido, campo)
        if (
            campo not in atualizacoes
            and valor is not None
            and valor.strip().casefold() in valores_nulos
        ):
            atualizacoes[campo] = None

    # Recupera o destino de viagens a serviço quando explícito no texto.
    if pedido.tipo == TipoPedido.DIARIA:
        destino_exterior = re.search(
            r"\b(?:a|para)\s+(Buenos Aires)\b",
            texto,
            flags=re.IGNORECASE,
        )

        if destino_exterior:
            atualizacoes["destino"] = "Buenos Aires"
            atualizacoes["tipo_destino"] = TipoDestino.EXTERIOR

    destino = pedido.destino
    if destino is not None and destino.strip().casefold() in valores_nulos:
        atualizacoes["destino"] = None

    justificativa = pedido.justificativa
    if justificativa.strip().casefold() in valores_nulos:
        atualizacoes["justificativa"] = "Motivo não informado"

    # Sem destino informado, não deve haver classificação geográfica.
    if not pedido.destino or pedido.destino.strip().casefold() in valores_nulos:
        atualizacoes["destino"] = None
        atualizacoes["tipo_destino"] = None

    # Recupera o motivo explícito da viagem.
    if (
        pedido.tipo == TipoPedido.DIARIA
        and re.search(r"\bcongresso\b", texto, flags=re.IGNORECASE)
    ):
        atualizacoes["justificativa"] = "Participação em congresso"

    return pedido.model_copy(update=atualizacoes)


# ------------------------------------------------------------------ 🆕 A: votação (OPCIONAL, bônus)
# Para ligar no grafo depois de pronto: USAR_VOTACAO = True em etapa07_grafo.py.
# 🆕 A.1 -- três instruções LIGEIRAMENTE diferentes para a MESMA tarefa (comece cada uma com f"Hoje é {texto_hoje()}. ")
#   ex.: um extrator literal; um que confere as datas contra o calendário; um que "pensa como o RH".
INSTRUCOES_VOTANTES: list[str] = []  # TODO 🆕 A.1: preencha com 3 strings


async def extrair_com_votacao(texto: str) -> tuple[Pedido, bool, list[Pedido]]:
    # 🆕 A.2 -- crie os 3 extratores e rode-os AO MESMO TEMPO:
    #     resultados = await asyncio.gather(*(Runner.run(e, texto) for e in extratores))
    #   depois chame votar([r.final_output for r in resultados]) e devolva (pedido_final, divergencia, votos).
    #   Conceito: aula7/exemplos/08_paralelismo/main.py (fan-out/fan-in), aqui em asyncio, sem grafo.
    raise NotImplementedError("🆕 A.2: extrair_com_votacao")


def votar(votos: list[Pedido]) -> tuple[Pedido, bool]:
    """(PRONTO) Maioria por campo. Sem maioria (2 de 3) em `tipo` ou nas datas -> divergencia=True: o sistema vai
    pedir esclarecimento em vez de adivinhar. Os campos não votados vêm do primeiro voto."""
    decidido, divergencia = {}, False
    for campo in ("tipo", "matricula", "data_inicio", "data_fim", "dias_vendidos"):
        valor, quantos = Counter(getattr(voto, campo) for voto in votos).most_common(1)[0]
        decidido[campo] = valor
        if quantos < 2 and campo in ("tipo", "data_inicio", "data_fim"):
            divergencia = True
    return votos[0].model_copy(update=decidido), divergencia


def _demo_extracao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C5_sem_matricula", "C11_diaria_exterior"):
        pedido = extrair(CASOS[nome]["pedido"])
        print(f"\n{nome}\n  {pedido.model_dump()}")


def _demo_votacao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C9_divergencia"):
        texto = CASOS[nome]["pedido"]
        inicio = time.perf_counter()
        pedido, divergencia, votos = asyncio.run(extrair_com_votacao(texto))
        segundos = time.perf_counter() - inicio
        print(f"\n{nome}  ({segundos:.1f}s, divergencia={divergencia})")
        for i, voto in enumerate(votos, 1):
            print(f"  voto {i}: tipo={voto.tipo.value} {voto.data_inicio}..{voto.data_fim} vende={voto.dias_vendidos}")
        print(f"  decisão: {pedido.model_dump()}")
    # (PRONTO) os mesmos 3 extratores EM SEQUÊNCIA, para comparar: o paralelo fica perto do tempo de UMA chamada?
    texto = CASOS["C2_ferias_com_venda"]["pedido"]
    inicio = time.perf_counter()
    for instrucoes in INSTRUCOES_VOTANTES:
        Runner.run_sync(criar_extrator(instrucoes), texto)
    print(f"\nC2 em sequência: {time.perf_counter() - inicio:.1f}s (compare com o tempo do C2 em paralelo, acima)")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    _demo_votacao() if "--votacao" in sys.argv else _demo_extracao()
