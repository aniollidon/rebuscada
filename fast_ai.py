import json
import os

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---------- Backends ----------

def _openai_api(messages: list, model: str) -> str:
    """Crida l'API oficial d'OpenAI."""
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    completion = client.chat.completions.create(model=model, messages=messages)
    return completion.choices[0].message.content


def _chatanywhere_api(messages: list, model: str) -> str:
    """Crida l'API de ChatAnywhere (compatible amb OpenAI)."""
    client = OpenAI(
        api_key=os.environ.get("CHATANYWHERE_API_KEY"),
        base_url="https://api.chatanywhere.tech/v1",
    )
    completion = client.chat.completions.create(model=model, messages=messages)
    return completion.choices[0].message.content


def _gemini_api(messages: list, model: str) -> str:
    """Crida l'API de Google Gemini via REST."""
    api_key = os.environ.get("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    # Converteix el format OpenAI messages -> Gemini contents
    system_text = ""
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            system_text = msg["content"]
        else:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Prepend system instruction al primer missatge d'usuari si existeix
    if system_text and contents:
        contents[0]["parts"][0]["text"] = system_text + "\n\n" + contents[0]["parts"][0]["text"]

    payload = {"contents": contents}
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ---------- Configuració per defecte de cada backend ----------

_BACKENDS = {
    "OPENAI": {
        "fn": _openai_api,
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-5-mini",
    },
    "CHATANYWHERE": {
        "fn": _chatanywhere_api,
        "model_env": "CHATANYWHERE_MODEL",
        "default_model": "gpt-3.5-turbo",
    },
    "GEMINI": {
        "fn": _gemini_api,
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.0-flash",
    },
}


def fast_ai(content: str, backend: str | None = None) -> str:
    """Genera contingut amb la IA configurada.

    El backend es selecciona amb el paràmetre `backend` o amb la variable
    d'entorn AI_API (valors: OPENAI, CHATANYWHERE, GEMINI). Per defecte: OPENAI.
    """
    backend = (backend or os.environ.get("AI_API", "OPENAI")).strip().upper()

    if backend not in _BACKENDS:
        raise ValueError(f"Backend '{backend}' no reconegut. Opcions: {', '.join(_BACKENDS.keys())}")

    cfg = _BACKENDS[backend]
    model = os.environ.get(cfg["model_env"], cfg["default_model"])

    base_content = (
        "No s'accepten expressions ni paraules compostes, ni duplicats.\n"
        "El resultat ha de ser EXCLUSIVAMENT un objecte JSON amb una única clau 'paraules' i un array de les paraules.\n"
        "Sense comentaris, sense explicacions, sense text addicional."
    )

    messages = [
        {"role": "system", "content": "Ets un assistent lingüístic català molt estricte amb el format."},
        {"role": "user", "content": content + base_content},
    ]

    print(f"[fast_ai] Backend: {backend} | Model: {model}")
    return cfg["fn"](messages, model)


if __name__ == "__main__":
    concept = "felicitat"
    res = fast_ai(
        f"Genera una llista de 100 noms i verbs únics en català relacionades amb el concepte de '{concept}'. "
        "Totes les paraules han d'estar en la seva forma singular i ser una sola paraula."
    )
    print(res)
    print()
