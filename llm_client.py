import os
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv(override=True)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL")
        )
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def chat_completion(messages, model=None, temperature=None):
    from config import get_config
    model = model or os.getenv("LLM_MODEL") or get_config("llm", "model", "gpt-4o-mini")
    temperature = temperature if temperature is not None else get_config("llm", "temperature", 0.2)

    client = get_client()
    return client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature
    )
