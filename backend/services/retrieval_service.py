"""检索引擎：封装 ChromaDB 操作（cosine 度量，惰性导入）。"""
import re

from config import config

_client = None

# BM25 索引缓存：{kb_id: (chunk_count, ids, documents, metadatas, bm25)}。
# 单进程内有效；任何写操作（加块/删块/删库）都会使对应 KB 的缓存失效，
# 未命中时按 chunk_count 重建，因此缓存过期最多多算一次，不会返回旧数据。
_bm25_cache: dict[str, tuple] = {}


def get_client():
    global _client
    if _client is None:
        import chromadb

        persist_dir = config.resolve_path(config.get("storage.chroma_persist_dir", "./data/chroma"))
        persist_dir.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(persist_dir))
    return _client


def _collection(kb_id: str):
    return get_client().get_or_create_collection(
        name=f"kb_{kb_id}",
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(
    kb_id: str,
    ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    document_id: str,
    document_name: str,
) -> None:
    col = _collection(kb_id)
    col.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=[{"document_id": document_id, "document_name": document_name}] * len(ids),
    )
    _bm25_cache.pop(kb_id, None)


def delete_document_vectors(kb_id: str, document_id: str) -> None:
    try:
        _collection(kb_id).delete(where={"document_id": document_id})
    except Exception:
        pass
    finally:
        _bm25_cache.pop(kb_id, None)


def delete_collection(kb_id: str) -> None:
    try:
        get_client().delete_collection(f"kb_{kb_id}")
    except Exception:
        pass
    finally:
        _bm25_cache.pop(kb_id, None)


def search(kb_id: str, query_embedding: list[float], top_k: int) -> list[dict]:
    """语义检索，返回 [{id, content, document_name, similarity}]。

    cosine 空间下 Chroma 返回的 distances 为余弦距离（= 1 - 余弦相似度），
    故 similarity = 1 - distance。
    """
    col = _collection(kb_id)
    res = col.query(query_embeddings=[query_embedding], n_results=top_k)
    ids = (res.get("ids") or [[]])[0]
    documents = (res.get("documents") or [[]])[0]
    metadatas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]

    results = []
    for i in range(len(ids)):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        content = documents[i] if i < len(documents) else ""
        results.append(
            {
                "id": ids[i],
                "content": content,
                "document_name": meta.get("document_name", ""),
                "similarity": round(1.0 - distances[i], 6),
            }
        )
    return results


def _tokenize(text: str) -> list[str]:
    """中文检索分词：英文/数字整体成词；中文字符做「相邻二字组(bigram)」。

    不引入 jieba 等分词库——bigram 能覆盖人名、术语、编号等生僻词，
    对关键词命中（而非语义理解）更鲁棒。刻意不用单字：单字噪声过大，
    会让无关问题也产生弱匹配。
    """
    tokens: list[str] = []
    for m in re.finditer(r"[A-Za-z0-9_]+", text):
        tokens.append(m.group().lower())
    cjk = re.findall(r"[一-鿿]", text)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    return tokens


def bm25_search(kb_id: str, query: str, top_k: int) -> list[dict]:
    """BM25 关键词检索，返回 [{id, content, document_name, bm25_score}]。

    从 Chroma 一次性取出该知识库全部 chunk 文本构建索引（个人知识库规模开销可忽略），
    索引按 KB 缓存，写操作后自动失效重建。
    bm25_score 仅当 chunk 与查询共享至少一个词时为正值，否则为 0。
    """
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return []

    col = _collection(kb_id)
    count = col.count()
    if count == 0:
        return []

    cached = _bm25_cache.get(kb_id)
    if cached and cached[0] == count:
        _, ids, documents, metadatas, bm25 = cached
    else:
        data = col.get(limit=count, include=["documents", "metadatas"])
        ids = data.get("ids") or []
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []

        corpus = [_tokenize(doc or "") for doc in documents]
        if not any(corpus):
            return []
        bm25 = BM25Okapi(corpus)
        _bm25_cache[kb_id] = (count, ids, documents, metadatas, bm25)

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = bm25.get_scores(query_tokens)

    results = []
    for i in sorted(range(len(scores)), key=lambda j: scores[j], reverse=True):
        if scores[i] <= 0:
            break
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        results.append(
            {
                "id": ids[i],
                "content": documents[i],
                "document_name": meta.get("document_name", ""),
                "bm25_score": round(float(scores[i]), 6),
            }
        )
        if len(results) >= top_k:
            break
    return results


def get_document_chunks(kb_id: str, document_id: str) -> list[dict]:
    """返回某文档的全部分块文本（按序号排序），用于前端预览提取内容。"""
    col = _collection(kb_id)
    data = col.get(where={"document_id": document_id}, include=["documents"])
    ids = data.get("ids") or []
    documents = data.get("documents") or []

    chunks = []
    for i, cid in enumerate(ids):
        content = documents[i] if i < len(documents) else ""
        chunks.append({"id": cid, "index": _chunk_index(cid), "content": content})
    chunks.sort(key=lambda c: c["index"])
    return chunks


def _chunk_index(chunk_id: str) -> int:
    """chunk id 形如 {document_id}_{序号}，取末尾序号。"""
    try:
        return int(chunk_id.rsplit("_", 1)[-1])
    except ValueError:
        return 0
