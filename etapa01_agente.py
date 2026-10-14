"""
ETAPA 1 -- Primeiro agente com tool local (15 min).

ESQUELETO: implemente as etapas na ordem. Cada uma está marcada com um comentário e um
raise NotImplementedError: troque esse raise pelo código da etapa e rode o arquivo.
  ETAPA 1.1 -- a tool consultar_servidor (SEM o salário)
  ETAPA 1.2 -- o agente AtendenteRH com a tool
  ETAPA 1.3 -- duas perguntas: uma que precisa da tool e uma que não precisa

REFERÊNCIAS NAS AULAS
  aula1/segundo_agente.py                            Agent + @function_tool + Runner.run_sync (o básico)
  exercicios_resolvidos/aula4/ex10_function_tool.py  tool que consulta uma TABELA e devolve JSON  <- o mais parecido
  aula8/exemplos/02_agente_tool/main.py              o agente decide quando chamar a tool (e quando não)

Rodar (a partir de aula10/):
    python etapa01_agente.py

Pronto quando: a tool é chamada só na primeira pergunta (o print dentro dela prova).
"""
import json

from agents import Agent, Runner, function_tool

from dados_rh import servidor_publico
from provedor import configurar

MODELO = configurar()  # LLM REAL: PROVEDOR no .env (openai ou ollama)


# ETAPA 1.1 -- a tool
#   - ponha um print("[tool] consultar_servidor", matricula) no começo, para provar quando ela roda;
#   - devolva json.dumps(servidor_publico(matricula), ensure_ascii=False). A consulta servidor_publico() (dados_rh.py)
#     já vem pronta: tira o salário (dado restrito, ver Etapas 5 e 9) e trata matrícula inexistente;
#   - capriche na DOCSTRING (com Args:): é o que o LLM lê para decidir chamar a tool. Esse é o ponto da etapa.
#   Referência: exercicios_resolvidos/aula4/ex10_function_tool.py (consultar_protocolo)
@function_tool
def consultar_servidor(matricula: str) -> str:
    """Consulta os dados de um servidor público pela matrícula.

    Retorna os dados cadastrais e funcionais do servidor em formato JSON,
    sem incluir informações salariais.

    Args:
        matricula: Número de matrícula do servidor público que será consultado.
    """
    print("[tool] consultar_servidor", matricula)

    return json.dumps(
        servidor_publico(matricula),
        ensure_ascii=False
    )


def criar_atendente() -> Agent:
    # ETAPA 1.2 -- o agente
    #   Agent(name="AtendenteRH", instructions=..., tools=[consultar_servidor])
    #   Instruções: atende servidores, responde em português e de forma breve, usa a tool quando a pergunta
    #   for sobre os dados de UM servidor, e não inventa saldo de cabeça.
    #   Referência: aula1/segundo_agente.py
    return Agent(
        name="AtendenteRH",
        instructions=(
            "Você é um atendente de Recursos Humanos. "
            "Responda sempre em português e de forma breve. "

            "IMPORTANTE: existem dois tipos de perguntas. "

            "1. PERGUNTAS SOBRE UM SERVIDOR: se a pergunta solicitar "
            "dados individuais, como dias de férias de uma matrícula, "
            "chame consultar_servidor e informe a matrícula correta. "

            "2. PERGUNTAS CONCEITUAIS: se a pergunta solicitar a "
            "definição de um conceito geral, como 'O que é abono "
            "pecuniário?', responda diretamente, sem chamar nenhuma "
            "ferramenta. "

            "Nunca chame consultar_servidor sem uma matrícula explícita. "
            "Nunca invente dados pessoais ou funcionais. "
            "Nunca informe dados salariais."

            "Para dúvidas conceituais, forneça definições corretas e objetivas. "
            "Não invente conceitos nem confunda benefícios diferentes. "
            "Se não souber a resposta com segurança, informe essa limitação."
        ),
        tools=[consultar_servidor],
    )


def main() -> None:
    # ETAPA 1.3 -- rode as duas perguntas com Runner.run_sync e imprima resultado.final_output
    #   1) "Quantos dias de férias a matrícula 1002 ainda tem?"   (precisa da tool)
    #   2) "O que é abono pecuniário?"                            (não precisa)
    #   Referência: aula8/exemplos/02_agente_tool/main.py
    agente = criar_atendente()

    perguntas = [
        "Quantos dias de férias a matrícula 1002 ainda tem?",
        "O que é abono pecuniário?"
    ]

    for pergunta in perguntas:
        print(f"\n[pergunta] {pergunta}")

        resultado = Runner.run_sync(
            agente,
            pergunta
        )

        print(resultado.final_output)

if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    main()