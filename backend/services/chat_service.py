"""RAG 问答编排：会话/消息持久化、检索兜底、Prompt 构建、LLM 调用（含流式）。"""
import json
import uuid

from config import config
from database import db
from utils.time_utils import now_iso
from . import embedding_service, llm_service, retrieval_service

SYSTEM_PROMPT = """你是一个知识库助手。请根据以下参考资料回答用户问题。
如果参考资料中没有相关信息，请如实告知。

参考资料：
{chunks}

用户问题：{question}

请回答："""

NO_INFO_ANSWER = "知识库中暂无相关信息，无法回答该问题。"


def _ensure_session(kb_id: str, session_id: str | None, question: str) -> str:
    """有 session_id 且属于该 kb 则复用，否则新建会话。"""
    with db() as conn:
        if session_id:
            row = conn.execute(
                "SELECT id FROM chat_sessions WHERE id = ? AND kb_id = ?", (session_id, kb_id)
            ).fetchone()
            if row:
                return session_id
        sid = str(uuid.uuid4())
        now = now_iso()
        conn.execute(
            "INSERT INTO chat_sessions(id, kb_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (sid, kb_id, question[:30], now, now),
        )
        return sid


def _save_message(session_id: str, role: str, content: str, sources: list[dict] | None = None) -> str:
    mid = str(uuid.uuid4())
    now = now_iso()
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_messages(id, session_id, role, content, sources, created_at) VALUES (?,?,?,?,?,?)",
            (mid, session_id, role, content, json.dumps(sources or [], ensure_ascii=False), now),
        )
        conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    return mid


def _get_message(mid: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (mid,)).fetchone()
    d = dict(row)
    d["sources"] = json.loads(d.get("sources") or "[]")
    return d


def _retrieve(kb_id: str, question: str) -> list[dict]:
    """混合检索：向量语义 + BM25 关键词，RRF 融合后按相关性过滤。

    返回的每个 chunk 含 {id, content, document_name, similarity, bm25_score, matched_by}，
    其中 similarity 为向量余弦相似度（关键词-only 时为 None）。
    """
    top_k = config.get("retrieval.top_k", 5)
    threshold = config.get("retrieval.similarity_threshold", 0.4)
    bm25_min = config.get("retrieval.bm25_min_score", 1.0)
    hybrid = config.get("retrieval.hybrid", True)

    q_vec = embedding_service.embed_one(question)
    vector_hits = retrieval_service.search(kb_id, q_vec, top_k)

    if hybrid:
        keyword_hits = retrieval_service.bm25_search(kb_id, question, top_k)
        fused = _rrf_fuse(vector_hits, keyword_hits, top_k)
    else:
        fused = [
            {
                "id": h["id"],
                "content": h["content"],
                "document_name": h["document_name"],
                "similarity": h["similarity"],
                "bm25_score": 0.0,
                "matched_by": "语义",
            }
            for h in vector_hits
        ]

    # 相关判定：向量相似度达标，或关键词分数达到绝对下限（过滤弱匹配噪声）
    return [
        c
        for c in fused
        if (c["similarity"] is not None and c["similarity"] >= threshold)
        or c["bm25_score"] >= bm25_min
    ]


def _rrf_fuse(vector_hits: list[dict], keyword_hits: list[dict], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion：按名次倒数融合两路结果，无需归一化不同量纲的分数。"""
    by_id: dict[str, dict] = {}
    for rank, h in enumerate(vector_hits):
        by_id[h["id"]] = {
            "id": h["id"],
            "content": h["content"],
            "document_name": h["document_name"],
            "similarity": h["similarity"],
            "bm25_score": 0.0,
            "_rrf": 1.0 / (60 + rank + 1),
        }
    for rank, h in enumerate(keyword_hits):
        entry = by_id.get(h["id"])
        score = 1.0 / (60 + rank + 1)
        if entry is None:
            by_id[h["id"]] = {
                "id": h["id"],
                "content": h["content"],
                "document_name": h["document_name"],
                "similarity": None,
                "bm25_score": h["bm25_score"],
                "_rrf": score,
            }
        else:
            entry["_rrf"] += score
            entry["bm25_score"] = h["bm25_score"]

    fused = sorted(by_id.values(), key=lambda x: x["_rrf"], reverse=True)[:top_k]
    for c in fused:
        c.pop("_rrf", None)
        if c["similarity"] is not None and c["bm25_score"] > 0:
            c["matched_by"] = "语义+关键词"
        elif c["similarity"] is not None:
            c["matched_by"] = "语义"
        else:
            c["matched_by"] = "关键词"
    return fused


def _build_prompt(question: str, chunks: list[dict]) -> str:
    chunk_text = "\n\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(chunks))
    return SYSTEM_PROMPT.format(chunks=chunk_text, question=question)


def _sources_from_chunks(chunks: list[dict]) -> list[dict]:
    return [
        {
            "content": c["content"],
            "document_name": c["document_name"],
            "similarity": c["similarity"],
            "matched_by": c["matched_by"],
        }
        for c in chunks
    ]


def chat(kb_id: str, question: str, session_id: str | None) -> dict:
    session_id = _ensure_session(kb_id, session_id, question)
    _save_message(session_id, "user", question)

    chunks = _retrieve(kb_id, question)
    if not chunks:
        answer = NO_INFO_ANSWER
        sources = []
    else:
        try:
            answer = llm_service.chat(_build_prompt(question, chunks))
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}")
        sources = _sources_from_chunks(chunks)

    mid = _save_message(session_id, "assistant", answer, sources)
    return _get_message(mid)


def chat_stream(kb_id: str, question: str, session_id: str | None):
    """SSE 生成器：任何异常统一转成 error 事件，避免流中断导致前端挂起。"""
    try:
        yield from _chat_stream_impl(kb_id, question, session_id)
    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps({"type": "error", "content": f"服务异常: {e}"}, ensure_ascii=False),
        }


def _chat_stream_impl(kb_id: str, question: str, session_id: str | None):
    session_id = _ensure_session(kb_id, session_id, question)
    _save_message(session_id, "user", question)
    yield {
        "event": "thinking",
        "data": json.dumps({"type": "thinking", "content": ""}, ensure_ascii=False),
    }

    chunks = _retrieve(kb_id, question)
    if not chunks:
        answer = NO_INFO_ANSWER
        sources = []
        yield {"event": "token", "data": json.dumps({"type": "token", "content": answer}, ensure_ascii=False)}
    else:
        sources = _sources_from_chunks(chunks)
        collected = []
        for token in llm_service.chat_stream(_build_prompt(question, chunks)):
            collected.append(token)
            yield {"event": "token", "data": json.dumps({"type": "token", "content": token}, ensure_ascii=False)}
        answer = "".join(collected).strip()

    mid = _save_message(session_id, "assistant", answer, sources)
    yield {
        "event": "sources",
        "data": json.dumps({"type": "sources", "content": sources}, ensure_ascii=False),
    }
    yield {
        "event": "done",
        "data": json.dumps(
            {"type": "done", "content": "", "message_id": mid, "session_id": session_id},
            ensure_ascii=False,
        ),
    }


def list_sessions(kb_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions WHERE kb_id = ? ORDER BY updated_at DESC", (kb_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_messages(session_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY rowid ASC", (session_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d.get("sources") or "[]")
        out.append(d)
    return out
