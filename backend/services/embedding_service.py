"""Embedding 服务：支持本地 ONNX（fastembed）、sentence-transformers、或 OpenAI 兼容 API。

三种后端及其取舍（也是本项目的部署选型记录）：

- ``fastembed``：ONNX Runtime 推理，无需 torch，模型仅约百 MB 量级，
  启动快、依赖轻，是**云部署的默认后端**；
- ``local``：sentence-transformers，模型选择面更广、生态成熟，
  但依赖链会把 torch（约 2GB）一并装进来，适合本机开发；
- ``openai``：任意 OpenAI 兼容的 embeddings 接口。

注意：不同后端（甚至同一后端的不同模型）的向量空间互不通用，
切换 ``embedding.mode`` 或 ``model_name`` 后必须**重建索引**，否则检索结果无意义。
"""
import math
import os

from config import config

_local_model = None
_fastembed_model = None


def _l2_normalize(vec: list[float]) -> list[float]:
    """手工做 L2 归一化。

    cosine 度量下归一化后内积即余弦相似度；不依赖 numpy 是为了让该模块
    在最小依赖环境下也能单独跑通（部署时用得上）。
    """
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _get_fastembed_model():
    """惰性加载 fastembed 模型（首次调用会下载模型文件，务必保持单例）。"""
    global _fastembed_model
    if _fastembed_model is None:
        # 国内 HuggingFace 镜像不支持新的 Xet 传输协议（会返回 401），
        # 必须在导入 huggingface_hub 之前关掉它，否则模型下载必然失败
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

        from fastembed import TextEmbedding

        model_name = config.get("embedding.fastembed.model_name", "BAAI/bge-small-zh-v1.5")
        # 缓存目录默认落在系统临时目录（重启可能被清理），放到项目内可控目录，
        # 既便于随包发布模型、也避免容器每次冷启动重新下载
        cache_dir = config.resolve_path(
            config.get("embedding.fastembed.cache_dir", "./models/fastembed")
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        _fastembed_model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
    return _fastembed_model


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

    if mode == "fastembed":
        model = _get_fastembed_model()
        # embed() 返回 numpy 数组的生成器，逐条转成 float 列表
        vecs = [[float(x) for x in v] for v in model.embed(texts)]
        if config.get("embedding.fastembed.normalize_embeddings", True):
            return [_l2_normalize(v) for v in vecs]
        return vecs

    # 本地 sentence-transformers
    model = _get_local_model()
    normalize = config.get("embedding.local.normalize_embeddings", True)
    vecs = model.encode(texts, normalize_embeddings=normalize)
    return [v.tolist() for v in vecs]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def describe() -> dict:
    """返回当前后端信息（健康检查与「关于」页展示用）。"""
    mode = config.get("embedding.mode", "local")
    if mode == "fastembed":
        model_name = config.get("embedding.fastembed.model_name", "BAAI/bge-small-zh-v1.5")
    elif mode == "openai":
        model_name = config.get("embedding.openai.model", "text-embedding-ada-002")
    else:
        model_name = config.get("embedding.local.model_name", "shibing624/text2vec-base-chinese")
    return {"mode": mode, "model": model_name}
