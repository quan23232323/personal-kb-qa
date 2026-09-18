"""API 层测试：统一响应封装、异常处理、鉴权中间件、上传-分块链路。

存储重定向到临时目录；embedding mock 为固定向量，不加载模型。
"""
import time

import pytest
from fastapi.testclient import TestClient

import main
from config import config
from services import embedding_service, kb_service, retrieval_service


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setitem(
        config.data,
        "storage",
        {
            "sqlite_path": str(tmp_path / "kb.db"),
            "chroma_persist_dir": str(tmp_path / "chroma"),
            "upload_dir": str(tmp_path / "uploads"),
        },
    )
    monkeypatch.setitem(config.data, "security", {"api_key": ""})
    monkeypatch.setattr(retrieval_service, "_client", None)
    monkeypatch.setattr(retrieval_service, "_bm25_cache", {})
    monkeypatch.setattr(embedding_service, "embed", lambda texts: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(embedding_service, "embed_one", lambda text: [0.1, 0.2])

    from database import init_db

    init_db()
    with TestClient(main.app) as c:
        yield c


def _create_kb(client, name="测试库"):
    resp = client.post("/api/knowledge-bases", json={"name": name, "description": ""})
    assert resp.status_code == 200
    return resp.json()["data"]


class TestResponseEnvelope:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0 and body["data"]["status"] == "ok"

    def test_unknown_api_route_returns_404_envelope(self, client):
        resp = client.get("/api/no-such-route")
        assert resp.status_code == 404
        assert resp.json()["code"] == 404

    def test_validation_error_returns_422_envelope(self, client):
        resp = client.post("/api/knowledge-bases", json={"description": "缺 name"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 422 and body["message"] == "请求参数校验失败"


class TestKnowledgeBaseCrud:
    def test_create_list_get_delete(self, client):
        kb = _create_kb(client, "生命周期库")

        assert any(k["id"] == kb["id"] for k in client.get("/api/knowledge-bases").json()["data"])
        assert client.get(f"/api/knowledge-bases/{kb['id']}").json()["data"]["name"] == "生命周期库"

        resp = client.delete(f"/api/knowledge-bases/{kb['id']}")
        assert resp.status_code == 200
        assert client.get(f"/api/knowledge-bases/{kb['id']}").status_code == 404

    def test_missing_kb_returns_404(self, client):
        assert client.get("/api/knowledge-bases/not-exist").status_code == 404


class TestGenericErrorHandling:
    def test_500_is_generic_without_internal_detail(self, client, monkeypatch):
        def boom():
            raise RuntimeError("内部机密路径 C:/secrets/key.pem")

        monkeypatch.setattr(kb_service, "list_kbs", boom)
        raw = TestClient(main.app, raise_server_exceptions=False)
        resp = raw.get("/api/knowledge-bases")
        assert resp.status_code == 500
        assert resp.json()["message"] == "服务器内部错误，请查看后端日志"
        assert "机密" not in resp.text  # 异常原文不外泄


class TestApiKeyMiddleware:
    def test_rejects_missing_and_wrong_key(self, client, monkeypatch):
        monkeypatch.setitem(config.data, "security", {"api_key": "right-key"})
        assert client.get("/api/knowledge-bases").status_code == 401
        assert client.get(
            "/api/knowledge-bases", headers={"X-API-Key": "wrong-key"}
        ).status_code == 401

    def test_accepts_correct_key(self, client, monkeypatch):
        monkeypatch.setitem(config.data, "security", {"api_key": "right-key"})
        resp = client.get("/api/knowledge-bases", headers={"X-API-Key": "right-key"})
        assert resp.status_code == 200

    def test_non_api_paths_not_guarded(self, client, monkeypatch):
        monkeypatch.setitem(config.data, "security", {"api_key": "right-key"})
        assert client.get("/health").status_code == 200


class TestUploadPipeline:
    def test_upload_then_chunks(self, client):
        kb = _create_kb(client)
        resp = client.post(
            f"/api/knowledge-bases/{kb['id']}/documents",
            files={"file": ("demo.md", "第一段内容。第二段内容。".encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200
        doc = resp.json()["data"]

        # TestClient 会同步跑完 BackgroundTasks；轮询兜底
        for _ in range(20):
            docs = client.get(f"/api/knowledge-bases/{kb['id']}/documents").json()["data"]
            if docs[0]["status"] != "processing":
                break
            time.sleep(0.1)
        assert docs[0]["status"] == "completed", docs[0].get("error_message")
        assert docs[0]["chunk_count"] >= 1

        chunks = client.get(f"/api/documents/{doc['id']}/chunks").json()["data"]
        assert chunks["chunk_count"] == docs[0]["chunk_count"]
        assert any("第一段内容" in c["content"] for c in chunks["chunks"])

    def test_rejects_content_extension_mismatch(self, client):
        kb = _create_kb(client)
        resp = client.post(
            f"/api/knowledge-bases/{kb['id']}/documents",
            files={"file": ("fake.pdf", b"<html>not a pdf</html>", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_oversized_file_rejected(self, client, monkeypatch):
        monkeypatch.setitem(config.data, "document", {"max_file_size_mb": 1, "chunk_size": 500, "chunk_overlap": 50})
        kb = _create_kb(client)
        resp = client.post(
            f"/api/knowledge-bases/{kb['id']}/documents",
            files={"file": ("big.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
        )
        assert resp.status_code == 413
