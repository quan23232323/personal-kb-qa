"""LLM 调用服务：支持 OpenAI 兼容 API 与本地 Ollama（OpenAI 兼容端点）。"""
from config import config


def _llm_params() -> tuple:
    mode = config.get("llm.mode", "ollama")
    if mode == "openai":
        base_url = config.get("llm.openai.base_url")
        api_key = config.get("llm.openai.api_key")
        if not api_key or "${" in api_key:
            raise ValueError(
                "OPENAI_API_KEY 未设置：请在启动后端前 export OPENAI_API_KEY=<你的 DeepSeek key>"
            )
        model = config.get("llm.openai.model", "gpt-4o-mini")
        temperature = config.get("llm.openai.temperature", 0.7)
        max_tokens = config.get("llm.openai.max_tokens", 2000)
    else:
        base = config.get("llm.ollama.base_url", "http://localhost:11434").rstrip("/")
        base_url = base + "/v1"  # Ollama 的 OpenAI 兼容端点
        api_key = "ollama"
        model = config.get("llm.ollama.model", "qwen2.5:7b")
        temperature = config.get("llm.ollama.temperature", 0.7)
        max_tokens = None
    return base_url, api_key, model, temperature, max_tokens


def _client(base_url: str, api_key: str):
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key=api_key)


def _build_kwargs(model, temperature, max_tokens, messages, stream=False) -> dict:
    kwargs = {"model": model, "messages": messages, "temperature": temperature, "stream": stream}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return kwargs


def chat(prompt: str) -> str:
    base_url, api_key, model, temperature, max_tokens = _llm_params()
    client = _client(base_url, api_key)
    kwargs = _build_kwargs(model, temperature, max_tokens, [{"role": "user", "content": prompt}])
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def chat_stream(prompt: str):
    base_url, api_key, model, temperature, max_tokens = _llm_params()
    client = _client(base_url, api_key)
    kwargs = _build_kwargs(
        model, temperature, max_tokens, [{"role": "user", "content": prompt}], stream=True
    )
    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
