from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import os
import time

# Carrega variáveis do .env
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()

class Prompt(BaseModel):
    question: str

@app.post("/ask")
def ask_ai(data: Prompt):
    # cria thread
    thread = client.beta.threads.create()

    # envia pergunta
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=data.question
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

    return {"response": answer}
