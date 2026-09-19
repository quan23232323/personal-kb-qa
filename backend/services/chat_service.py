"""RAG 问答编排：会话/消息持久化、检索兜底、Prompt 构建、LLM 调用（含流式）。"""
import json
import logging
import uuid

from config import config
from database import db
from utils.time_utils import now_iso
from . import embedding_service, llm_service, retrieval_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个知识库助手。请根据以下参考资料回答用户问题。
如果参考资料中没有相关信息，请如实告知。
{context}
参考资料：
{chunks}

用户问题：{question}

请回答："""

NO_INFO_ANSWER = "知识库中暂无相关信息，无法回答该问题。"

# 推理型模型会把 max_tokens 优先用于思维链，偶尔导致正文为空（finish_reason=length）。
# 空回答比「不知道」更糟——用户只会以为系统坏了，因此统一兜底为一句可理解的提示。
EMPTY_ANSWER_FALLBACK = "这次回答没能正常生成（生成可能被截断）。请再问一次，或把问题说得更具体一些。"


def _ensure_answer(answer: str | None) -> str:
    """把空字符串统一兜底，避免把空气泡展示给用户。"""
    text = (answer or "").strip()
    return text or EMPTY_ANSWER_FALLBACK

# 检索决策（方案 A/B）：让 LLM 先判断问题如何处理——检索 / 澄清 / 直接回答
DECISION_SYSTEM = """你是知识库问答助手的调度器，负责判断用户问题该如何处理：
- 问题需要依据用户上传的文档、资料或私有内容回答时：调用 search_knowledge_base，query 填适合检索的关键词或问句。
- 仅当问题完全缺少可检索的实体或关键词（如「那个」「它」等指代不明、且没有上下文）时：调用 ask_clarification 反问用户澄清。只要能提取到关键词就优先检索，不要过度澄清。
- 闲聊、问候、常识、或与知识库无关的问题：不要调用工具，直接简短友好地回答。"""

# 偏检索决策：知识库本身就是某个领域的资料集（例如一整本教科书、一套产品文档），
# 用户问的「通用常识」往往正是库里的内容。此时若沿用上面的宽松规则，模型会凭先验
# 直接作答、不给引用，知识库等于没用。该模式把「直接回答」收窄到真正的闲聊与实时信息。
DECISION_SYSTEM_PREFER_SEARCH = """你是知识库问答助手的调度器，负责判断用户问题该如何处理：
- 只要问题涉及任何可检索的主题、概念、术语或事实（包括你自认为已经掌握的通用知识），一律调用 search_knowledge_base，query 填适合检索的关键词或问句。用户选定了知识库，回答就应当以库内资料为依据。
- 仅当问题完全缺少可检索的实体或关键词（如「那个」「它」等指代不明、且没有上下文）时：调用 ask_clarification 反问用户澄清。只要能提取到关键词就优先检索，不要过度澄清。
- 只有纯粹的问候、闲聊、情绪表达，以及明确依赖实时信息的问题（如今天的天气、当前股价、最新新闻）才不调用工具，直接简短回答。"""

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": "在用户的知识库中检索相关文档内容。仅当问题需要依据用户上传的文档/资料回答时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用于检索的关键词或问句"}
            },
            "required": ["query"],
        },
    },
}

CLARIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_clarification",
        "description": "当用户问题模糊、有歧义或缺少必要信息、无法确定要检索什么时，反问用户澄清。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "向用户提出的澄清问题"}
            },
            "required": ["question"],
        },
    },
}


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


def _decide_retrieval(question: str, history: list[dict] | None = None) -> tuple[str, str | None, str | None]:
    """让 LLM 判断如何处理：返回 (action, payload, direct_answer)。

    action ∈ {'search', 'clarify', 'direct'}；search 的 payload 是检索词，clarify 的 payload 是澄清问题。
    """
    try:
        system_prompt = (
            DECISION_SYSTEM_PREFER_SEARCH
            if config.get("retrieval.prefer_search", False)
            else DECISION_SYSTEM
        )
        messages = [{"role": "system", "content": system_prompt}]
        for m in history or []:
            role = "assistant" if m.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": m.get("content", "")})
        messages.append({"role": "user", "content": question})

        content, tool_calls = llm_service.chat_with_tools(
            messages, [SEARCH_TOOL, CLARIFY_TOOL],
            temperature=config.get("llm.decision_temperature", 0.2),
        )
        if tool_calls:
            tc = tool_calls[0]
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, AttributeError):
                args = {}
            if tc.function.name == "ask_clarification":
                return "clarify", args.get("question") or "能再具体说明一下吗？", None
            if tc.function.name == "search_knowledge_base":
                return "search", args.get("query") or question, None
            return "search", question, None
        return "direct", None, (content or "").strip()
    except Exception:
        # 判断失败时保守回退：直接走检索（原行为）
        return "search", question, None


def _recent_history(session_id: str, limit: int = 6) -> list[dict]:
    """取会话最近几轮消息，供决策与生成理解上下文（多轮澄清）。"""
    msgs = list_messages(session_id)
    return msgs[-limit:] if len(msgs) > limit else msgs


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


def _build_prompt(question: str, chunks: list[dict], history: list[dict] | None = None) -> str:
    chunk_text = "\n\n".join(f"[{i + 1}] {c['content']}" for i, c in enumerate(chunks))
    context = ""
    if history:
        lines = [f"{'助手' if m.get('role') == 'assistant' else '用户'}：{m.get('content', '')}" for m in history]
        context = "对话上下文：\n" + "\n".join(lines) + "\n"
    return SYSTEM_PROMPT.format(context=context, chunks=chunk_text, question=question)


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
    history = _recent_history(session_id)
    _save_message(session_id, "user", question)

    action, payload, direct_answer = _decide_retrieval(question, history)
    if action == "clarify":
        answer = payload or NO_INFO_ANSWER
        sources = []
    elif action == "search":
        chunks = _retrieve(kb_id, payload)
        if not chunks:
            answer = NO_INFO_ANSWER
            sources = []
        else:
            try:
                answer = _ensure_answer(llm_service.chat(_build_prompt(question, chunks, history)))
            except Exception as e:
                raise RuntimeError(f"LLM 调用失败: {e}")
            sources = _sources_from_chunks(chunks)
    else:
        answer = direct_answer or NO_INFO_ANSWER
        sources = []

    mid = _save_message(session_id, "assistant", answer, sources)
    return _get_message(mid)


def chat_stream(kb_id: str, question: str, session_id: str | None):
    """SSE 生成器：任何异常统一转成 error 事件，避免流中断导致前端挂起。

    异常详情只进日志；发给前端的错误信息保持笼统，避免泄露内部实现。
    """
    try:
        yield from _chat_stream_impl(kb_id, question, session_id)
    except Exception:
        logger.exception("流式问答处理异常 kb_id=%s question=%r", kb_id, question[:50])
        yield {
            "event": "error",
            "data": json.dumps(
                {"type": "error", "content": "服务内部错误，请查看后端日志"},
                ensure_ascii=False,
            ),
        }


def _chat_stream_impl(kb_id: str, question: str, session_id: str | None):
    session_id = _ensure_session(kb_id, session_id, question)
    history = _recent_history(session_id)
    _save_message(session_id, "user", question)
    yield {
        "event": "thinking",
        "data": json.dumps({"type": "thinking", "content": ""}, ensure_ascii=False),
    }

    action, payload, direct_answer = _decide_retrieval(question, history)
    if action == "clarify":
        answer = payload or NO_INFO_ANSWER
        sources = []
        yield {"event": "token", "data": json.dumps({"type": "token", "content": answer}, ensure_ascii=False)}
    elif action == "search":
        chunks = _retrieve(kb_id, payload)
        if not chunks:
            answer = NO_INFO_ANSWER
            sources = []
            yield {"event": "token", "data": json.dumps({"type": "token", "content": answer}, ensure_ascii=False)}
        else:
            sources = _sources_from_chunks(chunks)
            collected = []
            for token in llm_service.chat_stream(_build_prompt(question, chunks, history)):
                collected.append(token)
                yield {"event": "token", "data": json.dumps({"type": "token", "content": token}, ensure_ascii=False)}
            answer = "".join(collected).strip()
            if not answer:
                # 正文为空时要把兜底文案作为 token 补发，否则前端只会显示一个空气泡
                answer = EMPTY_ANSWER_FALLBACK
                yield {"event": "token", "data": json.dumps({"type": "token", "content": answer}, ensure_ascii=False)}
    else:
        answer = direct_answer or NO_INFO_ANSWER
        sources = []
        yield {"event": "token", "data": json.dumps({"type": "token", "content": answer}, ensure_ascii=False)}

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
