from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import time
import requests

# Carrega variáveis do .env (para uso local)
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# ⚠️ COLOQUE AQUI OS DADOS DA SUA Z-API
ZAPI_INSTANCE_ID = "3EA9E25E43B7E155E1EC324DD30A57B5"
ZAPI_TOKEN = "86FF22205B06C0F041C0707F"

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


class Prompt(BaseModel):
    question: str


def run_assistant(question: str) -> str:
    """Roda o assistente da OpenAI e devolve a resposta em texto."""
    # cria thread
    thread = client.beta.threads.create()

    # envia pergunta
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=question
    )

    # roda o assistente
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID,
    )

    # espera terminar
    while True:
        status = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        if status.status == "completed":
            break
        time.sleep(0.5)

    # pega resposta
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    answer = messages.data[0].content[0].text.value

    return answer


@app.post("/ask")
def ask_ai(data: Prompt):
    answer = run_assistant(data.question)
    return {"response": answer}


@app.post("/webhook")
def whatsapp_webhook(payload: dict):
    """
    Webhook chamado pela Z-API quando chegar mensagem no WhatsApp.
    Normalmente o texto vem em payload["text"]["message"] e o número em payload["phone"].
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

    # envia resposta de volta pelo WhatsApp usando Z-API
    send_url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    body = {
        "phone": phone,
        "message": answer,
    }

    try:
        r = requests.post(send_url, json=body, timeout=10)
        print("Resposta enviada:", r.status_code, r.text)
    except Exception as e:
        print("Erro ao enviar mensagem:", e)

    return {"status": "sent"}
