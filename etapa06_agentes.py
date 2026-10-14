"""
ETAPA 6 -- Os especialistas, cada um com UMA responsabilidade e SÓ as tools de que precisa.

ESQUELETO:
  ETAPA 6.1 -- criar_normas(), criar_escala(), criar_financeiro(), criar_redator()
  ETAPA 6.2 -- criar_coordenador(): usa Normas, Escala e Financeiro como TOOLS (as_tool)

As tools abaixo (PRONTAS) só repassam a chamada ao MCP Server do RH (cliente_mcp.chamar_mcp_async). Dar a cada agente
só as tools dele é o PRIVILÉGIO MÍNIMO (Etapa 9.1); o hook do 🆕 B (etapa10_governanca.py) confere isso em tempo de execução.

REFERÊNCIAS NAS AULAS
  aula4/ex03_agente_as_tool.py                         Coordenador que chama especialistas como tools    <- o mais parecido
  aula2/agente_handoff2.py                             as_tool com tool_name e tool_description
  aula4/ex02_handoff_roteamento.py                     handoff: compare (quem responde no fim?)
  aula7/exemplos/02_agentes_especializados/main.py     uma responsabilidade por agente
  aula7/agentes.py                                     ModelSettings(temperature=0) para respostas mais estáveis
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o problema de dar tools DEMAIS a um agente
"""
import json

from agents import Agent, ModelSettings, RunHooks, function_tool

from etapa05_cliente_mcp import chamar_mcp_async
from etapa04_ferramentas import cotacao_usd_brl

CONFIG = ModelSettings(temperature=0)


# ------------------------------------------------------------------ tools (PRONTAS)
@function_tool
async def consultar_normas(tema: str) -> str:
    """Regras da norma interna sobre um tema: férias, prazos, escala, abono, diária, aprovação, saúde ou dados."""
    return json.dumps(await chamar_mcp_async("consultar_normas", {"tema": tema}), ensure_ascii=False)


@function_tool
async def consultar_escala(equipe: str, inicio: str, fim: str) -> str:
    """Afastamentos da equipe que se sobrepõem ao período (AAAA-MM-DD) e o limite de afastados da regra N5."""
    return json.dumps(await chamar_mcp_async("consultar_escala", {"equipe": equipe, "inicio": inicio, "fim": fim}),
                      ensure_ascii=False)


@function_tool
async def tabela_diarias(tipo_destino: str) -> str:
    """Moeda e valor da diária para o tipo de destino: capital, interior ou exterior."""
    return json.dumps(await chamar_mcp_async("tabela_diarias", {"tipo_destino": tipo_destino}), ensure_ascii=False)


@function_tool
async def consultar_remuneracao(matricula: str) -> str:
    """[RESTRITA] Salário-base de um servidor. Só para calcular a venda de férias (N2)."""
    print(f"[tool] consultar_remuneracao({matricula}) EXECUTOU")  # o 🆕 B prova que, barrada, ela NÃO executa
    return json.dumps(await chamar_mcp_async("consultar_remuneracao", {"matricula": matricula}), ensure_ascii=False)


@function_tool
def cotacao_dolar() -> str:
    """Cotação atual do dólar em reais (USD->BRL). Devolve 'indisponível' se a API falhar: nunca invente o câmbio."""
    cotacao = cotacao_usd_brl()
    return f"{cotacao:.4f}" if cotacao else "indisponível"


# ------------------------------------------------------------------ ETAPA 6.1: especialistas
def criar_normas() -> Agent:
    # ETAPA 6.1 -- Agent(name="Normas", instructions=..., tools=[consultar_normas], model_settings=CONFIG)
    #   Responsabilidade: dizer QUAIS regras se aplicam ao pedido e explicá-las em linguagem simples.
    #   NÃO calcula valores, NÃO consulta a escala. Recebe também as violações objetivas (etapa06_regras.py) para explicá-las.
    return Agent(
        name="Normas",
        instructions="""
Você é o especialista em normas administrativas de RH.

Sua única responsabilidade é identificar e explicar as regras aplicáveis
ao pedido, utilizando linguagem simples, objetiva e formal.

Procedimento:
1. Leia o pedido, os dados do servidor, o período solicitado e as violações
   objetivas informadas pelo sistema.
2. Consulte a ferramenta consultar_normas para obter o texto das normas
   pertinentes ao assunto.
3. Explique quais regras se aplicam e como elas se relacionam com o pedido.
4. Explique cada violação objetiva recebida, identificando a regra envolvida.
5. Se uma informação normativa não estiver disponível, declare essa limitação.

Restrições:
- Não consulte a escala de servidores.
- Não calcule valores financeiros.
- Não invente regras, prazos ou exceções.
- Não altere nem descarte as violações objetivas fornecidas pelo sistema.
- Diferencie o conteúdo consultado na norma de sua própria explicação.
- Não exponha CPF ou dados de saúde.
- Não tome a decisão administrativa final.
""",
        tools=[consultar_normas],
        model_settings=CONFIG,
    )


def criar_escala() -> Agent:
    # ETAPA 6.1 -- tools=[consultar_escala]. Confere a N5 e, se houver conflito, SUGERE outro período
    #   (com o mesmo número de dias, começando num dia permitido).
    return Agent(
        name="Escala",
        instructions="""
Você é o especialista em escala e afastamentos de servidores.

Sua única responsabilidade é analisar conflitos de escala e sugerir
datas alternativas quando os dados permitirem.

PROCEDIMENTO
1. Identifique o tipo de pedido, a equipe, a data inicial e a data final.
2. Leia as violações objetivas fornecidas pelo sistema.
3. Se equipe e período estiverem disponíveis, consulte consultar_escala
   para verificar os afastamentos sobrepostos.
4. Explique os conflitos com base nos resultados efetivamente recebidos.
5. Se houver conflito, procure uma alternativa com a mesma duração,
   respeitando as restrições de início aplicáveis ao tipo de pedido.
6. Só afirme que uma alternativa está livre se ela tiver sido verificada.
7. Se não puder verificar uma alternativa, declare essa limitação.

RESTRIÇÕES
- Não invente afastamentos, datas, limites ou resultados de consulta.
- Não altere nem descarte violações objetivas do sistema.
- Não consulte remuneração nem calcule valores financeiros.
- Não decida pelo deferimento ou indeferimento.
- Não exponha CPF ou dados de saúde.
""",
tools=[consultar_escala],
model_settings=CONFIG,
    )


def criar_financeiro() -> Agent:
    # ETAPA 6.1 -- tools=[tabela_diarias, consultar_remuneracao, cotacao_dolar].
    #   Venda de férias (N2): dias_vendidos x salario_base / 30. Diárias (N7): uma por pernoite + meia no retorno;
    #   no exterior, em USD convertido pela cotação. Mostre a conta. Câmbio indisponível -> "a calcular".
    #   É o ÚNICO agente que vê o salário.
    return Agent(
        name="Financeiro",
        instructions="""
Você é o especialista em cálculos financeiros de solicitações de RH.

Sua responsabilidade é calcular valores relacionados à venda de férias
e ao pagamento de diárias, utilizando exclusivamente as ferramentas
disponibilizadas e os dados efetivamente fornecidos.

VENDA DE FÉRIAS — REGRA N2
1. Só consulte a remuneração quando o pedido envolver venda de férias.
2. Utilize consultar_remuneracao com a matrícula do servidor.
3. Calcule o valor proporcional usando:
   valor = quantidade de dias vendidos × salário-base / 30.
4. Apresente a quantidade de dias, o salário-base consultado e a conta.
5. Se faltar algum dado ou a consulta falhar, informe a limitação.

DIÁRIAS — REGRA N7
1. Consulte tabela_diarias com o tipo de destino: capital, interior ou exterior.
2. Identifique as datas da viagem e a quantidade de pernoites.
3. Calcule uma diária por pernoite, acrescida de meia diária no retorno,
   conforme a regra fornecida para o cenário.
4. Mostre a quantidade de diárias equivalentes, a tarifa aplicável
   e o cálculo total.
5. Para destinos no exterior, se a tarifa estiver em dólares, consulte
   cotacao_dolar e converta o total para reais.
6. Se a cotação estiver indisponível, não invente o câmbio: informe
   o valor na moeda original, quando conhecido, e indique o total em reais
   como "a calcular".

Restrições:
- Não consulte remuneração para pedidos que não envolvam venda de férias.
- Você é o único especialista autorizado a consultar a remuneração.
- Não invente salários, tarifas, cotações ou datas.
- Diferencie valores consultados de valores calculados.
- Não decida se o pedido deve ser deferido ou indeferido.
- Não exponha CPF ou dados de saúde.
""",
        tools=[
            tabela_diarias,
            consultar_remuneracao,
            cotacao_dolar,
        ],
        model_settings=CONFIG,
    )



def criar_redator() -> Agent:
    # ETAPA 6.1 -- sem tools. Escreve o DESPACHO (deferimento ou indeferimento) usando SÓ os fatos recebidos:
    #   matrícula, período, decisão, regras citadas, valores e, no indeferimento, a sugestão de datas.
    #   Nunca escreve CPF nem dado de saúde (N10). Se receber um feedback (da validação ou da chefia), corrige.
    return Agent(
        name="Redator",
        instructions="""
Você é responsável por redigir o despacho administrativo de uma solicitação
de RH, em português brasileiro formal, claro e objetivo.

Utilize exclusivamente os fatos e resultados recebidos na entrada, incluindo:
- matrícula do servidor;
- tipo e período da solicitação;
- decisão administrativa já informada pelo sistema;
- regras aplicáveis e pareceres recebidos;
- violações objetivas;
- valores calculados;
- sugestões de datas alternativas, quando existirem.

Estruture o despacho com:
1. Identificação da solicitação, usando somente os dados fornecidos.
2. Síntese dos fatos e do período solicitado.
3. Fundamentação normativa.
4. Valores, quando aplicáveis.
5. Conclusão compatível com a decisão recebida.
6. Orientação ou sugestão de período alternativo, quando aplicável.

Se receber feedback da validação ou da chefia, corrija o texto conforme
esse feedback, sem alterar os fatos ou a decisão autorizada.

Restrições:
- Não decida por conta própria se o pedido será deferido ou indeferido.
- Não invente fatos, regras, valores, datas ou aprovações.
- Não transforme uma pendência de aprovação em aprovação efetiva.
- Nunca inclua CPF ou dados de saúde, conforme a regra N10.
- Não inclua informações que não tenham sido fornecidas.
- Se faltar informação necessária, indique a pendência em vez de inventá-la.
""",
        tools=[],
        model_settings=CONFIG,
    )


# ------------------------------------------------------------------ ETAPA 6.2: coordenador
def criar_coordenador(hooks: RunHooks | None = None, tools_extras: list | None = None, incluir_financeiro: bool = True) -> Agent:
    # ETAPA 6.2 -- Agent(name="Coordenador", instructions=..., tools=[
    #       criar_normas().as_tool(tool_name="parecer_normas", tool_description=..., hooks=hooks,
    #                              failure_error_function=None),
    #       criar_escala().as_tool(tool_name="parecer_escala", ..., hooks=hooks, failure_error_function=None),
    #       criar_financeiro().as_tool(tool_name="parecer_financeiro", ..., hooks=hooks, failure_error_function=None),
    #       *(tools_extras or [])])
    #   O Coordenador decide QUAIS especialistas consultar (abono não precisa do Financeiro) e junta os pareceres.
    #   hooks=hooks nas as_tool faz o hook do 🆕 B enxergar também as tools DENTRO de cada especialista.
    #   failure_error_function=None: sem isso, um erro dentro do especialista (inclusive o bloqueio do 🆕 B) vira só
    #   um texto de erro para o Coordenador, que segue em frente. Com None, o erro interrompe a execução.
    #   tools_extras serve só para o teste do 🆕 B (dar de propósito consultar_remuneracao ao Coordenador).
    #   Referência: aula4/ex03_agente_as_tool.py
    especialista_normas = criar_normas().as_tool(
        tool_name="parecer_normas",
        tool_description=(
            "Recebe um único argumento textual chamado input. "
            "Explica as normas aplicáveis ao pedido e as violações objetivas."
        ),
        hooks=hooks,
        failure_error_function=None,
    )

    especialista_escala = criar_escala().as_tool(
        tool_name="parecer_escala",
        tool_description=(
            "Recebe um único argumento textual chamado input. "
            "Analisa conflitos de escala e sugere alternativas quando possível."
        ),
        hooks=hooks,
        failure_error_function=None,
    )

    especialista_financeiro = criar_financeiro().as_tool(
        tool_name="parecer_financeiro",
        tool_description=(
            "Recebe um único argumento textual chamado input. "
            "Calcula venda de férias somente quando houver dias vendidos "
            "e calcula diárias somente para pedidos de diária."
        ),
        hooks=hooks,
        failure_error_function=None,
    )

    ferramentas_coordenador = [
        especialista_normas,
        especialista_escala,
    ]

    if incluir_financeiro:
        ferramentas_coordenador.append(especialista_financeiro)

    ferramentas_coordenador.extend(tools_extras or [])

    return Agent(
        name="Coordenador",
        instructions="""
Você é o coordenador da análise administrativa de solicitações de RH.

Sua tarefa é selecionar os especialistas estritamente necessários,
reunir os pareceres efetivamente recebidos e apresentar uma análise
consolidada. As verificações objetivas feitas pelo Python prevalecem
sobre opiniões ou inferências do modelo.

REGRAS DE ROTEAMENTO — SIGA EXATAMENTE

1. Sempre chame parecer_normas para explicar as regras aplicáveis.

2. Chame parecer_escala somente para pedidos de férias ou abono
   que tenham dados suficientes para analisar a escala.
   Se o sistema já informou violações objetivas, inclua-as na consulta.
   Não peça ao especialista que refaça cálculos já fornecidos pelo sistema
   como se os resultados anteriores não existissem.

3. Chame parecer_financeiro SOMENTE nestes casos:
   a) férias com dias_vendidos maior que zero; ou
   b) solicitação do tipo DIARIA.

4. Para ABONO, nunca chame parecer_financeiro.

5. Para FERIAS com dias_vendidos igual a zero, nunca chame
   parecer_financeiro.

6. Para pedidos incompletos, não invente matrícula, datas, dias vendidos,
   destino ou qualquer outro dado. Registre o que está faltando.

COMO CHAMAR OS ESPECIALISTAS

- Cada chamada deve conter um argumento textual conciso e completo.
- Informe explicitamente o tipo de pedido, a matrícula, as datas,
  os dias vendidos, as violações objetivas e os resultados já conhecidos,
  quando esses dados estiverem disponíveis.
- Não inclua comentários, Markdown ou explicações fora do argumento.
- Faça apenas uma chamada de especialista por vez.
- Não repita chamadas que já foram concluídas com sucesso.
- Se uma chamada falhar, não invente nem simule o parecer ausente.
  Informe que a análise correspondente não pôde ser concluída.

CONSOLIDAÇÃO

- Separe fatos fornecidos pelo sistema, resultados consultados,
  cálculos e sugestões.
- Preserve integralmente as violações objetivas recebidas.
- Peça ao especialista Normas que explique as regras relacionadas
  às violações.
- Inclua sugestões de datas somente se tiverem sido efetivamente
  produzidas por um especialista ou por uma rotina determinística.
- Não afirme que uma data alternativa está livre sem consulta à escala.
- Não transforme sugestões em fatos confirmados.
- Não redija o despacho administrativo final. Essa tarefa pertence
  ao Redator.

LIMITES DE AUTORIDADE

- Não tome a decisão administrativa final.
- Não aprove pedidos em nome da chefia.
- Não declare uma aprovação sem confirmação efetiva.
- Não consulte remuneração por conta própria.
- Não invente dados, regras, valores ou resultados de ferramentas.
- Não exponha CPF ou dados de saúde.

FORMATO DA RESPOSTA

Organize o resultado em:
1. Dados do pedido.
2. Violações objetivas informadas pelo sistema.
3. Parecer normativo.
4. Parecer de escala, se aplicável.
5. Parecer financeiro, se aplicável.
6. Pendências e limitações da análise.

Não inclua seções de pareceres que não foram solicitados ou executados.
""",
        tools=ferramentas_coordenador,
        model_settings=CONFIG,
    )


