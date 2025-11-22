from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import time
import requests
from datetime import datetime

# Carrega variáveis do .env (uso local)
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# ⚠️ ATENÇÃO: ideal é jogar isso pro .env depois e regenerar os tokens
ZAPI_INSTANCE_ID = "3EA9E25E43B7E155E1EC324DD30A57B5"
ZAPI_TOKEN = "86FF22205B06C0F041C0707F"
ZAPI_CLIENT_TOKEN = "F11bc68dcc0434bb7b87a95abc68507ebS"

# Webhook do Google Sheets (Apps Script)
SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwAVMCIJNDJ5lP_PanYqD-7YFsY5mXy8TSI11CgvgA6e_Z3VVmzqXTcphFF3t9cO7XG5Q/exec"

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


class Prompt(BaseModel):
    question: str


def run_assistant(question: str) -> str:
    """Roda o assistente da OpenAI e devolve a resposta em texto."""
    thread = client.beta.threads.create()

    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=question
    )

    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID,
    )

    while True:
        status = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        if status.status == "completed":
            break
        time.sleep(0.5)

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    answer = messages.data[0].content[0].text.value

    return answer


def classificar_lead(mensagem: str) -> str:
    """
    Classificação bem simples só pra começar.
    Depois podemos melhorar usando a própria IA.
    """
    texto = (mensagem or "").lower()

    palavras_quente = ["preço", "valor", "quanto", "custa", "investimento", "fechar", "contratar", "quero o bot"]
    palavras_morno = ["como funciona", "explica", "explicar", "saber mais", "informação", "interesse"]

    if any(p in texto for p in palavras_quente):
        return "quente"
    if any(p in texto for p in palavras_morno):
        return "morno"
    return "frio"


def enviar_para_planilha(
    numero: str,
    mensagem_recebida: str,
    mensagem_enviada: str,
):
    """Envia os dados do lead para o webhook do Google Sheets."""
    status_lead = classificar_lead(mensagem_recebida)

    payload = {
        "numero": numero,
        "nome": "",               # por enquanto deixamos vazio; depois podemos pedir pra IA captar
        "segmento": "",           # idem
        "interesse": "",          # idem
        "mensagemRecebida": mensagem_recebida or "",
        "mensagemEnviada": mensagem_enviada or "",
        "statusLead": status_lead,
        "objetivo": "",           # podemos usar no futuro
        "etapa": "novo",          # etapa inicial
        "observacoes": "Capturado automaticamente pela L.I.A em " + datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    try:
        r = requests.post(SHEETS_WEBHOOK_URL, json=payload, timeout=10)
        print("Lead enviado para planilha:", r.status_code, r.text)
    except Exception as e:
        print("Erro ao enviar lead para planilha:", e)


@app.post("/ask")
def ask_ai(data: Prompt):
    answer = run_assistant(data.question)
    return {"response": answer}


@app.post("/webhook")
def whatsapp_webhook(payload: dict):
    """
    Webhook chamado pela Z-API quando chegar mensagem no WhatsApp.
    Normalmente:
      - texto vem em payload["text"]["message"]
      - número vem em payload["phone"]
    """
    print("Webhook recebido:", payload)

    # ignora mensagens que você mesmo enviou
    if payload.get("fromMe"):
        return {"status": "ignored"}

    phone = payload.get("phone")
    text_block = payload.get("text") or {}
    message = text_block.get("message")

    if not phone or not message:
        return {"status": "no_text"}

    # gera resposta com a IA
    answer = run_assistant(message)

    # monta chamada para Z-API
    send_url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    body = {
        "phone": phone,
        "message": answer,
    }
    headers = {
        "Client-Token": ZAPI_CLIENT_TOKEN
    }

    # envia resposta pro WhatsApp
    try:
        r = requests.post(send_url, json=body, headers=headers, timeout=10)
        print("Resposta enviada:", r.status_code, r.text)
    except Exception as e:
        print("Erro ao enviar mensagem:", e)

    # envia também para a planilha (captura de lead)
    try:
        enviar_para_planilha(
            numero=str(phone),
            mensagem_recebida=message,
            mensagem_enviada=answer,
        )
    except Exception as e:
        print("Erro ao registrar lead:", e)

    return {"status": "ok"}
