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

# ⚠️ Ideal depois é jogar isso pro .env
ZAPI_INSTANCE_ID = "3EA9E25E43B7E155E1EC324DD30A57B5"
ZAPI_TOKEN = "86FF22205B06C0F041C0707F"
ZAPI_CLIENT_TOKEN = "F11bc68dcc0434bb7b87a95abc68507ebS"

# Webhook do Google Sheets (Apps Script)
SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbwAVMCIJNDJ5lP_PanYqD-7YFsY5mXy8TSI11CgvgA6e_Z3VVmzqXTcphFF3t9cO7XG5Q/exec"

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


class Prompt(BaseModel):
    question: str


# ====== MEMÓRIA POR NÚMERO (THREADS) ======
PHONE_THREADS: dict[str, str] = {}  # {phone: thread_id}


def get_thread_id_for_phone(phone: str) -> str:
    """Retorna o thread_id para um número. Cria se não existir."""
    if phone in PHONE_THREADS:
        return PHONE_THREADS[phone]

    thread = client.beta.threads.create()
    PHONE_THREADS[phone] = thread.id
    print(f"Nova thread criada para {phone}: {thread.id}")
    return thread.id


def run_assistant(question: str) -> str:
    """Versão simples, usada pelo /ask (sem Whats)."""
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


def run_assistant_for_phone(phone: str, question: str) -> str:
    """Versão com memória por número, usada no WhatsApp."""
    thread_id = get_thread_id_for_phone(phone)

    # adiciona a nova mensagem na thread
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=question
    )

    # roda o assistente
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ASSISTANT_ID,
    )

    while True:
        status = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id
        )
        if status.status == "completed":
            break
        time.sleep(0.5)

    messages = client.beta.threads.messages.list(thread_id=thread_id)
    answer = messages.data[0].content[0].text.value
    return answer


# ====== CLASSIFICAÇÃO E PLANILHA ======

def classificar_lead(mensagem: str) -> str:
    """
    Classificação simples só pra filtrar o que cai na planilha.
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
    """Envia os dados do lead para o webhook do Google Sheets, apenas se for lead 'morno' ou 'quente'."""
    status_lead = classificar_lead(mensagem_recebida)

    # Não salva leads frios (só "oi", "blz", etc.)
    if status_lead == "frio":
        print("Lead frio, não enviado para planilha.")
        return

    payload = {
        "numero": numero,
        "nome": "",               # depois podemos preencher com ajuda da L.I.A
        "segmento": "",           # idem
        "interesse": "",          # idem
        "mensagemRecebida": mensagem_recebida or "",
        "mensagemEnviada": mensagem_enviada or "",
        "statusLead": status_lead,
        "objetivo": "",           # futuro: IA pode extrair isso
        "etapa": "novo",          # etapa inicial
        "observacoes": "Capturado automaticamente pela L.I.A em " + datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    try:
        r = requests.post(SHEETS_WEBHOOK_URL, json=payload, timeout=10)
        print("Lead enviado para planilha:", r.status_code, r.text)
    except Exception as e:
        print("Erro ao enviar lead para planilha:", e)


# ====== ENDPOINTS ======

@app.post("/ask")
def ask_ai(data: Prompt):
    answer = run_assistant(data.question)
    return {"response": answer}


@app.post("/webhook")
def whatsapp_webhook(payload: dict):
    """
    Webhook chamado pela Z-API quando chegar mensagem no WhatsApp.
      - texto em payload["text"]["message"]
      - número em payload["phone"]
    """
    print("Webhook recebido:", payload)

    # ignora mensagens que você mesmo enviou
    if payload.get("fromMe"):
        return {"status": "ignored"}

    phone = str(payload.get("phone") or "")
    text_block = payload.get("text") or {}
    message = text_block.get("message")

    if not phone or not message:
        return {"status": "no_text"}

    # gera resposta com a IA (com memória por número)
    answer = run_assistant_for_phone(phone, message)

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

    # registra lead na planilha (somente morno/quente)
    try:
        enviar_para_planilha(
            numero=phone,
            mensagem_recebida=message,
            mensagem_enviada=answer,
        )
    except Exception as e:
        print("Erro ao registrar lead:", e)

    return {"status": "ok"}
