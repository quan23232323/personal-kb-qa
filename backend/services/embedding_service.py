"""Embedding 服务：支持本地 sentence-transformers 或 OpenAI 兼容 API。"""
from config import config

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        model_name = config.get("embedding.local.model_name", "shibing624/text2vec-base-chinese")
        device = config.get("embedding.local.device", "cpu")
        _local_model = SentenceTransformer(model_name, device=device)
    return _local_model


def _openai_client():
    from openai import OpenAI

    return OpenAI(
        api_key=config.get("embedding.openai.api_key"),
        base_url=config.get("embedding.openai.base_url"),
    )


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    mode = config.get("embedding.mode", "local")
    if mode == "openai":
        client = _openai_client()
        model = config.get("embedding.openai.model", "text-embedding-ada-002")
        resp = client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]
    # 本地模式
    model = _get_local_model()
    normalize = config.get("embedding.local.normalize_embeddings", True)
    vecs = model.encode(texts, normalize_embeddings=normalize)
    return [v.tolist() for v in vecs]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
