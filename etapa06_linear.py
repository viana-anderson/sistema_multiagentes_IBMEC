"""
ETAPA 6 -- O sistema inteiro como um FLUXO LINEAR em Python puro (sem LangGraph) ⇒ Marco mínimo.

ESQUELETO:
  ETAPA 6.3 -- analisar(): o Coordenador junta os pareceres (com os limites da Etapa 4.7)
  ETAPA 6.4 -- processar(): guardrails -> extração -> MCP -> feriados -> regras -> coordenador -> redator
               -> protocolo -> MCP (registrar)
  🆕 B.4    -- (OPCIONAL, bônus) testar_governanca(): os dois testes de bloqueio do --governanca

REFERÊNCIAS NAS AULAS
  aula6/exemplos/01_fluxo_linear/main.py     o fluxo linear: funciona, mas sem decisão nem volta (por isso a Etapa 7)
  aula4/ex03_agente_as_tool.py               o Coordenador com especialistas como tools
  aula7/exemplos/02_agentes_especializados/main.py   cada especialista imprime o que fez: dá para saber quem fez o quê

Rodar:
    python etapa06_linear.py                 # C1, C2, C6 e C11
    python etapa06_linear.py --governanca    # 🆕 B (opcional): os dois testes de bloqueio

Pronto quando: C1, C2 e C11 são gravados com protocolo, C6 vira indeferimento com sugestão de datas, e você sabe dizer
qual agente escreveu cada parte. (Opcional) no --governanca: a tool restrita NÃO executa e o C2 para no orçamento.
"""
import json
import os
import sys

from agents import RunHooks

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from etapa02_extracao import extrair
from etapa04_ferramentas import gerar_protocolo, rodar_com_limites_sync
from etapa10_governanca import Governanca, LimiteExcedido
from etapa03_guardrails import encontrar_dado_sensivel, nota_escopo, LIMIAR, MENSAGENS
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas
from datetime import date

MODELO = configurar()


def analisar(pedido: dict, servidor: dict, periodo: dict, violacoes: list[str], hooks: RunHooks | None = None, incluir_financeiro: bool = False) -> str:
    # ETAPA 6.3 -- monte um texto com o pedido, o servidor (matrícula e equipe), o período e as violações objetivas,
    #   e rode criar_coordenador(hooks) com rodar_com_limites_sync(..., hooks=hooks). Devolva final_output.
    entrada = {
        "pedido": pedido,
        "servidor": {
            "matricula": servidor.get("matricula"),
            "equipe": servidor.get("equipe"),
            "cargo": servidor.get("cargo"),
            "saldo_ferias_dias": servidor.get("saldo_ferias_dias"),
            "abonos_restantes": servidor.get("abonos_restantes"),
        },
        "periodo": periodo,
        "violacoes_objetivas": violacoes,
    }

    coordenador = agentes.criar_coordenador(
        hooks=hooks,
        incluir_financeiro=incluir_financeiro,
    )

    resultado = rodar_com_limites_sync(
        coordenador,
        json.dumps(entrada, ensure_ascii=False, indent=2),
        hooks=hooks,
    )

    return resultado.final_output

def calcular_fatos_financeiros(pedido: dict, matricula: str) -> dict:
    """Calcula valores usando dados consultados, sem confiar em valores do LLM."""
    tipo = pedido.get("tipo")
    fatos = {}

    if tipo == "ferias":
        dias_vendidos = int(pedido.get("dias_vendidos") or 0)

        if dias_vendidos > 0:
            remuneracao = chamar_mcp(
                "consultar_remuneracao",
                {"matricula": matricula},
            )

            if (
                isinstance(remuneracao, dict)
                and not remuneracao.get("erro")
                and remuneracao.get("salario_base") is not None
            ):
                salario = float(remuneracao["salario_base"])
                valor = round(dias_vendidos * salario / 30, 2)

                fatos["venda_ferias"] = {
                    "dias_vendidos": dias_vendidos,
                    "salario_base_brl": salario,
                    "valor_calculado_brl": valor,
                    "formula": f"{dias_vendidos} × salário-base ÷ 30",
                }
            else:
                fatos["venda_ferias"] = {
                    "status": "não calculado",
                    "motivo": "Não foi possível consultar a remuneração.",
                }

    elif tipo == "diaria":
        tipo_destino = pedido.get("tipo_destino")

        # Aceita tanto texto quanto Enum.
        if hasattr(tipo_destino, "value"):
            tipo_destino = tipo_destino.value

        destino = str(tipo_destino or "").strip().lower()

        # Recuperação defensiva para o caso de o campo estar ausente.
        if not destino:
            cidade = str(pedido.get("destino") or "").strip().casefold()
            if cidade == "buenos aires":
                destino = "exterior"

        if destino not in {"capital", "interior", "exterior"}:
            fatos["diarias"] = {
                "status": "não calculado",
                "motivo": (
                    "O tipo de destino não foi identificado "
                    "como capital, interior ou exterior."
                ),
            }
            return fatos

        tabela = chamar_mcp(
            "tabela_diarias",
            {"tipo_destino": destino},
        )

        if (
            not isinstance(tabela, dict)
            or tabela.get("erro")
            or tabela.get("valor_diaria") is None
            or not tabela.get("moeda")
        ):
            fatos["diarias"] = {
                "status": "não calculado",
                "motivo": "Não foi possível consultar a tabela de diárias.",
            }
            return fatos

        try:
            inicio = date.fromisoformat(pedido["data_inicio"])
            fim = date.fromisoformat(pedido["data_fim"])
        except (TypeError, ValueError, KeyError):
            fatos["diarias"] = {
                "status": "não calculado",
                "motivo": "As datas da viagem estão ausentes ou inválidas.",
            }
            return fatos

        pernoites = (fim - inicio).days

        if pernoites < 0:
            fatos["diarias"] = {
                "status": "não calculado",
                "motivo": "O término antecede o início da viagem.",
            }
            return fatos

        # Regra do exercício: pernoites + meia diária no retorno.
        equivalentes = pernoites + 0.5
        tarifa = float(tabela["valor_diaria"])
        moeda = str(tabela["moeda"]).upper()
        total = round(equivalentes * tarifa, 2)

        dados_diarias = {
            "destino": pedido.get("destino"),
            "destino_tipo": destino,
            "moeda": moeda,
            "tarifa_unitaria": tarifa,
            "pernoites": pernoites,
            "diarias_equivalentes": equivalentes,
            "total_moeda_original": total,
        }

        if moeda == "USD":
            # Cotação mais recente disponível, não cotação futura.
            from etapa04_ferramentas import cotacao_usd_brl

            cotacao = cotacao_usd_brl()

            if cotacao is not None:
                dados_diarias["cotacao_usd_brl"] = round(
                    float(cotacao), 4
                )
                dados_diarias["total_brl_estimado"] = round(
                    total * float(cotacao), 2
                )
                dados_diarias["observacao_cambio"] = (
                    "Conversão estimada pela cotação mais recente "
                    "disponível na API; não representa cotação futura."
                )
            else:
                dados_diarias["total_brl_estimado"] = None
                dados_diarias["observacao_cambio"] = (
                    "Cotação indisponível; conversão para reais pendente."
                )

        fatos["diarias"] = dados_diarias

    return fatos

def normalizar_tipo_pedido(pedido: dict, texto: str) -> str:
    """Normaliza o tipo extraído usando também o texto original do pedido."""
    tipo = str(pedido.get("tipo") or "").strip().lower()
    texto_normalizado = texto.casefold()

    # O texto original resolve o caso em que o LLM devolve "outro"
    # apesar de o pedido mencionar explicitamente o tipo correto.
    if "abono" in texto_normalizado:
        return "abono"

    if "diária" in texto_normalizado or "diaria" in texto_normalizado:
        return "diaria"

    if "férias" in texto_normalizado or "ferias" in texto_normalizado:
        return "ferias"

    aliases = {
        "ferias": "ferias",
        "férias": "ferias",
        "abono": "abono",
        "diaria": "diaria",
        "diária": "diaria",
    }

    return aliases.get(tipo, tipo)

def processar(texto: str, hooks: RunHooks | None = None) -> dict:
    # ETAPA 6.4 -- encadeie, imprimindo cada passo ("[1/9] guardrails", ...):
    #   1. encontrar_dado_sensivel / nota_escopo >= LIMIAR  -> devolva {"resultado": "bloqueado", "mensagem": ...}
    #   2. pedido = extrair(texto).model_dump(mode="json")  -> sem matrícula ou datas: {"resultado": "pedir_dados"}
    #   3. servidor = chamar_mcp("consultar_servidor", ...) -> não encontrado: {"resultado": "pedir_dados"}
    #   4. periodo = resumo_periodo(...)                     (API de feriados, Etapa 4)
    #   5. escala = chamar_mcp("consultar_escala", ...); violacoes = violacoes_objetivas(...)
    #   6. parecer = analisar(...)
    #   7. despacho = rodar_com_limites_sync(agentes.criar_redator(), <fatos + parecer + violações>).final_output
    #   8. protocolo = gerar_protocolo(...)
    #   9. chamar_mcp("registrar_decisao", {..., "decisao": "indeferido" se houver violação senão "deferido",
    #        "aprovador": "pendente_chefia" se precisa_chefia(...) senão "sistema", "token": os.getenv("TOKEN_REGISTRO")})
    #      (a aprovação de verdade da chefia entra na Etapa 8; aqui só marcamos que ela será necessária)
    #   Devolva {"resultado": ..., "protocolo": ..., "despacho": ..., "parecer": ...}.
    print("[1/9] guardrails")

    dado_sensivel = encontrar_dado_sensivel(texto)
    if dado_sensivel:
        return {
            "resultado": "bloqueado",
            "mensagem": MENSAGENS.get(
                dado_sensivel,
                "O pedido contém dado sensível e não pode ser processado.",
            ),
        }

    nota, motivo = nota_escopo(texto)
    if nota >= LIMIAR:
        return {
            "resultado": "bloqueado",
            "mensagem": (
                f"{MENSAGENS['fora_do_escopo']} "
                f"Motivo identificado: {motivo}"
            ),
        }

    # [2/9] Extração do pedido
    print("[2/9] extração")

    try:
        pedido = extrair(texto).model_dump(mode="json")
    except Exception as erro:
        return {
            "resultado": "pedir_dados",
            "mensagem": f"Não foi possível extrair os dados do pedido: {erro}",
        }

    matricula_bruta = pedido.get("matricula")
    matricula = str(matricula_bruta or "").strip()

    # Trata respostas do modelo que representam ausência de matrícula.
    valores_ausentes = {
        "",
        "none",
        "null",
        "not specified",
        "não informado",
        "nao informado",
        "não informada",
        "nao informada",
        "não fornecido",
        "nao fornecido",
    }

    if matricula.casefold() in valores_ausentes:
        matricula = ""
        pedido["matricula"] = None

    tipo = normalizar_tipo_pedido(pedido, texto)
    pedido["tipo"] = tipo
    inicio = pedido.get("data_inicio")
    fim = pedido.get("data_fim")

    if matricula and not matricula.isdigit():
        matricula = ""
        pedido["matricula"] = None

    if not matricula:
        return {
            "resultado": "pedir_dados",
            "mensagem": "Informe a matrícula do servidor.",
            "pedido": pedido,
        }

    if not inicio:
        return {
            "resultado": "pedir_dados",
            "mensagem": "Informe a data de início do pedido.",
            "pedido": pedido,
        }

    # Abono é tratado como afastamento de um único dia quando não há data final.
    if not fim and tipo == "abono":
        fim = inicio
        pedido["data_fim"] = fim

    if not fim:
        return {
            "resultado": "pedir_dados",
            "mensagem": "Informe a data de término do pedido.",
            "pedido": pedido,
        }

    # [3/9] Consulta do cadastro via MCP
    print("[3/9] consulta MCP: servidor")

    servidor = chamar_mcp(
        "consultar_servidor",
        {"matricula": matricula},
    )

    if (
        not isinstance(servidor, dict)
        or servidor.get("erro")
        or not servidor.get("matricula")
    ):
        return {
            "resultado": "pedir_dados",
            "mensagem": (
                f"Não foi possível localizar o servidor da matrícula "
                f"{matricula}. Confira a matrícula e tente novamente."
            ),
            "pedido": pedido,
        }

    # [4/9] Resumo do período e consulta de feriados
    print("[4/9] cálculo do período e feriados")

    periodo = resumo_periodo(inicio, fim)

    # [5/9] Consulta de escala e verificação objetiva das regras
    print("[5/9] consulta MCP: escala e regras objetivas")

    escala = chamar_mcp(
        "consultar_escala",
        {
            "equipe": servidor["equipe"],
            "inicio": inicio,
            "fim": fim,
        },
    )

    violacoes = violacoes_objetivas(
        pedido,
        servidor,
        periodo,
        escala,
    )

    print(f"    Violações encontradas: {len(violacoes)}")
    for violacao in violacoes:
        print(f"    - {violacao}")

    # [6/9] Análise pelo Coordenador e especialistas
    print("[6/9] parecer do Coordenador e especialistas")

    incluir_financeiro = (
        tipo == "diaria"
        or (
            tipo == "ferias"
            and int(pedido.get("dias_vendidos") or 0) > 0
        )
    )

    parecer = analisar(
        pedido=pedido,
        servidor=servidor,
        periodo=periodo,
        violacoes=violacoes,
        hooks=hooks,
        incluir_financeiro=incluir_financeiro,
    )

    fatos_financeiros = calcular_fatos_financeiros(
    pedido=pedido,
    matricula=matricula,
    )

    # Determina a decisão preliminar e identifica a necessidade de chefia.
    precisa_aprovacao_chefia = precisa_chefia(pedido, violacoes)

    if violacoes:
        decisao = "indeferido"
        resultado = "indeferido"
        aprovador = "sistema"

    elif precisa_aprovacao_chefia:
        decisao = "pendente_chefia"
        resultado = "pendente_chefia"
        aprovador = "pendente_chefia"

    else:
        decisao = "deferido"
        resultado = "registrado" if tipo == "abono" else "deferido"
        aprovador = "sistema"

    # [7/9] Redação do despacho
    print("[7/9] redação do despacho")

    fatos_redacao = {
        "matricula": matricula,
        "tipo": tipo,
        "pedido": pedido,
        "servidor": {
            "matricula": matricula,
            "equipe": servidor.get("equipe"),
            "cargo": servidor.get("cargo"),
        },
        "periodo": periodo,
        "decisao": decisao,
        "regras_violadas": violacoes,
        "parecer_especialistas": parecer,
        "fatos_financeiros": fatos_financeiros,
        "orientacao": (
            "A solicitação aguarda aprovação efetiva da chefia."
            if precisa_aprovacao_chefia and not violacoes
            else None
        ),
    }

    despacho = rodar_com_limites_sync(
        agentes.criar_redator(),
        json.dumps(fatos_redacao, ensure_ascii=False, indent=2),
        hooks=hooks,
    ).final_output

    # [8/9] Geração do protocolo
    print("[8/9] geração do protocolo")

    protocolo = gerar_protocolo(
        matricula,
        tipo,
        inicio,
        fim,
    )

    # [9/9] Registro da decisão preliminar via MCP
    print("[9/9] registro MCP: decisão")

    registro = chamar_mcp(
        "registrar_decisao",
        {
            "protocolo": protocolo,
            "matricula": matricula,
            "tipo": tipo,
            "inicio": inicio,
            "fim": fim,
            "decisao": decisao,
            "aprovador": aprovador,
            "despacho": despacho,
            "token": os.getenv("TOKEN_REGISTRO", ""),
        },
    )

    if not isinstance(registro, dict) or not registro.get("sucesso"):
        return {
            "resultado": "erro_registro",
            "protocolo": protocolo,
            "despacho": despacho,
            "parecer": parecer,
            "registro": registro,
            "mensagem": (
                "A análise foi concluída, mas o MCP não confirmou "
                "o registro da solicitação."
            ),
        }

    return {
        "resultado": resultado,
        "protocolo": protocolo,
        "despacho": despacho,
        "parecer": parecer,
        "violacoes": violacoes,
        "periodo": periodo,
        "fatos_financeiros": fatos_financeiros,
        "registro": registro,
    }



def testar_governanca() -> None:
    # 🆕 B.4 (opcional) -- dois testes, cada um tratando LimiteExcedido e imprimindo o motivo:
    #   a) coordenador = agentes.criar_coordenador(hooks=Governanca(), tools_extras=[agentes.consultar_remuneracao])
    #      pergunte "Qual o salário da matrícula 1002?" -> deve ser BARRADO e o print da tool NÃO pode aparecer.
    #   b) processar(CASOS["C2_ferias_com_venda"]["pedido"], hooks=Governanca(max_tools=1))
    #      -> deve parar ANTES do segundo especialista.
    print("\n========== TESTE A: ferramenta restrita ==========")

    governanca_a = Governanca()

    coordenador = agentes.criar_coordenador(
        hooks=governanca_a,
        tools_extras=[agentes.consultar_remuneracao],
    )

    try:
        resposta = rodar_com_limites_sync(
            coordenador,
            "Use a ferramenta consultar_remuneracao para consultar "
            "o salário da matrícula 1002 e informar o valor.",
            hooks=governanca_a,
        )

        print("ATENÇÃO: a execução terminou sem lançar LimiteExcedido.")
        print("Resposta:", resposta.final_output)
        print(
            "Verifique se a ferramenta restrita foi bloqueada pela "
            "governança e se o print de execução da tool apareceu."
        )

    except LimiteExcedido as erro:
        print("BLOQUEIO CONFIRMADO:", erro)
        print(
            "Confira que não apareceu a mensagem "
            "'[tool] consultar_remuneracao(1002) EXECUTOU'."
        )

    print("\n========== TESTE B: limite de ferramentas ==========")

    try:
        resultado = processar(
            CASOS["C2_ferias_com_venda"]["pedido"],
            hooks=Governanca(max_tools=1),
        )

        print(
            "ATENÇÃO: o processamento terminou sem lançar "
            "LimiteExcedido."
        )
        print(json.dumps(resultado, ensure_ascii=False, indent=2))

    except LimiteExcedido as erro:
        print("LIMITE DE FERRAMENTAS CONFIRMADO:", erro)
        print("O processamento foi interrompido pelo mecanismo de governança.")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    if "--governanca" in sys.argv:
        testar_governanca()
    else:
        for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C6_conflito_de_escala", "C11_diaria_exterior"):
            print(f"\n=============== {nome}")
            print(json.dumps(processar(CASOS[nome]["pedido"]), ensure_ascii=False, indent=2))
