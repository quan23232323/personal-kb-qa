"""chat_service 核心逻辑单测：RRF 融合、检索过滤、决策分发、Prompt 构建、问答持久化。

所有 LLM / embedding / Chroma 依赖均被 mock，不访问网络、不加载模型。
"""
import json
from types import SimpleNamespace

import pytest

from config import config
from services import chat_service, embedding_service, kb_service, llm_service, retrieval_service


def _tool_call(name: str, arguments: str):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


@pytest.fixture()
def retrieval_cfg(monkeypatch):
    """固定检索阈值，避免受 config.yaml 调参影响。"""
    monkeypatch.setitem(
        config.data,
        "retrieval",
        {"top_k": 5, "similarity_threshold": 0.4, "hybrid": True, "bm25_min_score": 1.0},
    )


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """存储重定向到临时目录并初始化表结构。"""
    monkeypatch.setitem(
        config.data,
        "storage",
        {
            "sqlite_path": str(tmp_path / "kb.db"),
            "chroma_persist_dir": str(tmp_path / "chroma"),
            "upload_dir": str(tmp_path / "uploads"),
        },
    )
    from database import init_db

    init_db()


def _hit(cid, sim=None, bm25=None, name="doc.md"):
    h = {"id": cid, "content": f"内容{cid}", "document_name": name}
    if sim is not None:
        h["similarity"] = sim
    if bm25 is not None:
        h["bm25_score"] = bm25
    return h


class TestRrfFuse:
    def test_overlap_chunk_ranks_first_and_merges_scores(self):
        fused = chat_service._rrf_fuse(
            [_hit("a", sim=0.9), _hit("b", sim=0.8)],
            [_hit("b", bm25=3.2), _hit("c", bm25=1.5)],
            top_k=5,
        )
        assert [c["id"] for c in fused] == ["b", "a", "c"]  # b 两路都命中，RRF 排第一
        assert fused[0]["matched_by"] == "语义+关键词"
        assert fused[0]["bm25_score"] == 3.2
        assert fused[0]["similarity"] == 0.8
        assert fused[1]["matched_by"] == "语义"
        assert fused[2]["matched_by"] == "关键词"
        assert fused[2]["similarity"] is None

    def test_top_k_truncates(self):
        vector = [_hit(f"v{i}", sim=0.9) for i in range(8)]
        fused = chat_service._rrf_fuse(vector, [], top_k=5)
        assert len(fused) == 5

    def test_keyword_only_hit(self):
        fused = chat_service._rrf_fuse([], [_hit("k", bm25=2.0)], top_k=5)
        assert fused[0]["similarity"] is None
        assert fused[0]["bm25_score"] == 2.0
        assert fused[0]["matched_by"] == "关键词"


class TestRetrieve:
    def test_vector_only_mode_filters_below_threshold(self, monkeypatch, retrieval_cfg):
        monkeypatch.setitem(config.data, "retrieval", {"top_k": 5, "similarity_threshold": 0.4, "hybrid": False, "bm25_min_score": 1.0})
        monkeypatch.setattr(embedding_service, "embed_one", lambda q: [0.1])
        monkeypatch.setattr(
            retrieval_service, "search",
            lambda kb, qv, k: [_hit("good", sim=0.8), _hit("bad", sim=0.2)],
        )
        out = chat_service._retrieve("kb1", "问题")
        assert [c["id"] for c in out] == ["good"]

    def test_keyword_hit_needs_absolute_min_score(self, monkeypatch, retrieval_cfg):
        monkeypatch.setattr(embedding_service, "embed_one", lambda q: [0.1])
        monkeypatch.setattr(retrieval_service, "search", lambda kb, qv, k: [])
        monkeypatch.setattr(
            retrieval_service, "bm25_search",
            lambda kb, q, k: [_hit("strong", bm25=2.5), _hit("weak", bm25=0.3)],
        )
        out = chat_service._retrieve("kb1", "问题")
        assert [c["id"] for c in out] == ["strong"]

    def test_weak_everything_returns_empty(self, monkeypatch, retrieval_cfg):
        monkeypatch.setattr(embedding_service, "embed_one", lambda q: [0.1])
        monkeypatch.setattr(retrieval_service, "search", lambda kb, qv, k: [_hit("x", sim=0.1)])
        monkeypatch.setattr(retrieval_service, "bm25_search", lambda kb, q, k: [])
        assert chat_service._retrieve("kb1", "问题") == []


class TestDecideRetrieval:
    def test_search_tool_uses_llm_query(self, monkeypatch):
        captured = {}

        def fake_chat_with_tools(messages, tools, temperature=None):
            captured["messages"] = messages
            captured["temperature"] = temperature
            return None, [_tool_call("search_knowledge_base", json.dumps({"query": "RAG 架构"}))]

        monkeypatch.setattr(llm_service, "chat_with_tools", fake_chat_with_tools)
        action, payload, direct = chat_service._decide_retrieval("怎么搭建RAG？", [{"role": "user", "content": "上一轮"}])
        assert (action, payload, direct) == ("search", "RAG 架构", None)
        # 决策用低温（稳定路由），且历史与当前问题都进了消息
        assert captured["temperature"] == config.get("llm.decision_temperature", 0.2)
        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][-1]["content"] == "怎么搭建RAG？"
        assert any(m["content"] == "上一轮" for m in captured["messages"])

    def test_search_without_query_falls_back_to_question(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("search_knowledge_base", "{}")]),
        )
        assert chat_service._decide_retrieval("原始问题") == ("search", "原始问题", None)

    def test_clarify_tool(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("ask_clarification", '{"question": "你指的是哪个文档？"}')]),
        )
        assert chat_service._decide_retrieval("那个东西") == ("clarify", "你指的是哪个文档？", None)

    def test_clarify_empty_question_gets_default(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("ask_clarification", "{}")]),
        )
        action, payload, _ = chat_service._decide_retrieval("嗯")
        assert action == "clarify" and payload

    def test_no_tool_call_is_direct_answer(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: ("你好呀！", None),
        )
        assert chat_service._decide_retrieval("在吗") == ("direct", None, "你好呀！")

    def test_malformed_args_fall_back_to_question(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("search_knowledge_base", "not-json{")]),
        )
        assert chat_service._decide_retrieval("问题") == ("search", "问题", None)

    def test_llm_error_falls_back_to_search(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("api down")

        monkeypatch.setattr(llm_service, "chat_with_tools", boom)
        assert chat_service._decide_retrieval("问题") == ("search", "问题", None)


class TestBuildPrompt:
    def test_contains_context_chunks_and_question(self):
        history = [{"role": "user", "content": "之前的问题"}, {"role": "assistant", "content": "之前的回答"}]
        chunks = [{"content": "块一"}, {"content": "块二"}]
        prompt = chat_service._build_prompt("当前问题", chunks, history)
        assert "对话上下文：" in prompt
        assert "用户：之前的问题" in prompt
        assert "助手：之前的回答" in prompt
        assert "[1] 块一" in prompt and "[2] 块二" in prompt
        assert "用户问题：当前问题" in prompt

    def test_no_history_section_when_empty(self):
        prompt = chat_service._build_prompt("问题", [{"content": "块"}], None)
        assert "对话上下文" not in prompt


@pytest.mark.usefixtures("tmp_db")
class TestChatPersistence:
    KB_NAME = "单测知识库"

    def _setup_mocks(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("search_knowledge_base", '{"query": "测试"}')]),
        )
        monkeypatch.setattr(embedding_service, "embed_one", lambda q: [0.0])
        monkeypatch.setattr(retrieval_service, "search", lambda kb, qv, k: [_hit("c1", sim=0.9)])
        monkeypatch.setattr(retrieval_service, "bm25_search", lambda kb, q, k: [])
        monkeypatch.setattr(llm_service, "chat", lambda prompt: "这是回答。")

    def test_chat_saves_messages_and_sources(self, monkeypatch):
        self._setup_mocks(monkeypatch)
        kb = kb_service.create_kb(self.KB_NAME, "")

        msg = chat_service.chat(kb["id"], "测试问题", None)
        assert msg["role"] == "assistant"
        assert msg["content"] == "这是回答。"
        assert len(msg["sources"]) == 1
        assert msg["sources"][0]["document_name"] == "doc.md"
        assert msg["sources"][0]["matched_by"] == "语义"

        sessions = chat_service.list_sessions(kb["id"])
        assert len(sessions) == 1 and sessions[0]["title"] == "测试问题"
        msgs = chat_service.list_messages(sessions[0]["id"])
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "测试问题"

    def test_reused_session_keeps_history(self, monkeypatch):
        self._setup_mocks(monkeypatch)
        kb = kb_service.create_kb(self.KB_NAME, "")

        first = chat_service.chat(kb["id"], "第一问", None)
        second = chat_service.chat(kb["id"], "第二问", first["session_id"])
        assert second["session_id"] == first["session_id"]

        msgs = chat_service.list_messages(first["session_id"])
        assert [m["content"] for m in msgs] == ["第一问", "这是回答。", "第二问", "这是回答。"]

    def test_no_chunks_answers_no_info(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("search_knowledge_base", '{"query": "x"}')]),
        )
        monkeypatch.setattr(embedding_service, "embed_one", lambda q: [0.0])
        monkeypatch.setattr(retrieval_service, "search", lambda kb, qv, k: [])
        monkeypatch.setattr(retrieval_service, "bm25_search", lambda kb, q, k: [])
        kb = kb_service.create_kb(self.KB_NAME, "")

        msg = chat_service.chat(kb["id"], "问题", None)
        assert msg["content"] == chat_service.NO_INFO_ANSWER
        assert msg["sources"] == []

    def test_clarify_path_saves_without_sources(self, monkeypatch):
        monkeypatch.setattr(
            llm_service, "chat_with_tools",
            lambda m, t, temperature=None: (None, [_tool_call("ask_clarification", '{"question": "能说具体点吗？"}')]),
        )
        kb = kb_service.create_kb(self.KB_NAME, "")

        msg = chat_service.chat(kb["id"], "那个", None)
        assert msg["content"] == "能说具体点吗？"
        assert msg["sources"] == []

    def test_stream_emits_full_event_sequence(self, monkeypatch):
        self._setup_mocks(monkeypatch)
        kb = kb_service.create_kb(self.KB_NAME, "")

        events = [e["event"] for e in chat_service.chat_stream(kb["id"], "流式问题", None)]
        assert events[0] == "thinking"
        assert "token" in events and "sources" in events
        assert events[-1] == "done"
