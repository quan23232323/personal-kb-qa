"""演示模式护栏：公网 Demo 的额度控制与写操作限制。

公网演示有两类真实成本：**LLM 额度**（访客每问一句都在花钱）和
**数据完整性**（谁都能上传/删除知识库）。本模块用四道闸门把它们关起来，
全部由 config.yaml 的 ``demo`` 段控制，默认关闭——关闭时逻辑零开销、行为与本地一致。

1. 按访客 IP 的每日提问上限
2. 单次提问的字数上限（防止有人粘贴整本书）
3. 全站每日提问总上限（最终兜底，即使 IP 被伪造也封顶成本）
4. 写操作白名单：只放行「向知识库提问」，上传/删除/新建一律拒绝

额度账本落在**独立的 SQLite 文件**（默认 data/demo_quota.db），与业务库解耦：
演示库被清空重建也不会丢额度记录。所有写账本操作串行化，避免并发下超发。
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from config import config

# 演示模式下唯一放行的写操作：问答（含 SSE 流式）
_ALLOWED_WRITE_PATH = re.compile(r"^/api/knowledge-bases/[^/]+/chat(?:/stream)?$")

_LOCK = threading.Lock()


# ---------- 配置读取 ----------

def is_enabled() -> bool:
    return bool(config.get("demo.enabled", False))


def per_ip_daily() -> int:
    return int(config.get("demo.per_ip_daily", 3) or 0)


def global_daily() -> int:
    return int(config.get("demo.global_daily", 0) or 0)


def max_question_chars() -> int:
    return int(config.get("demo.max_question_chars", 0) or 0)


# ---------- 账本 ----------

def _quota_path() -> Path:
    p = config.resolve_path(config.get("demo.quota_db", "./data/demo_quota.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_quota_path()), timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quota("
        " day TEXT NOT NULL, scope TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY(day, scope))"
    )
    return conn


def _used(conn: sqlite3.Connection, day: str, scope: str) -> int:
    row = conn.execute("SELECT used FROM quota WHERE day=? AND scope=?", (day, scope)).fetchone()
    if row is None:
        conn.execute("INSERT INTO quota(day, scope, used) VALUES(?,?,0)", (day, scope))
        return 0
    return int(row[0])


def _prune(conn: sqlite3.Connection) -> None:
    """清掉一周前的记录，避免账本无限增长。"""
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    conn.execute("DELETE FROM quota WHERE day < ?", (cutoff,))


# ---------- 访客识别 ----------

def client_ip(request) -> str:
    """取访客 IP：反向代理下以 X-Forwarded-For 首个地址为准。

    uvicorn 在云部署模式已开启 proxy_headers，request.client.host 通常已是真实 IP；
    这里再兜一层 XFF，是为了兼容代理未重写 client 的场景。
    """
    xff = request.headers.get("x-forwarded-for", "") if request.headers else ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    host = getattr(getattr(request, "client", None), "host", None)
    return host or "unknown"


# ---------- 对外接口 ----------

def check_and_consume(request, question: str) -> dict:
    """追问前校验并记账；超额抛 429，超长抛 400。返回额度快照。"""
    if not is_enabled():
        return {}

    limit_chars = max_question_chars()
    if limit_chars and len(question) > limit_chars:
        raise HTTPException(
            status_code=400,
            detail=f"演示环境单次提问不超过 {limit_chars} 字，请精简后重试",
        )

    ip = client_ip(request)
    day = date.today().isoformat()
    ip_scope = f"ip:{ip}"

    with _LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            total = _used(conn, day, "global")
            mine = _used(conn, day, ip_scope)

            if global_daily() and total >= global_daily():
                conn.execute("ROLLBACK")
                raise HTTPException(
                    status_code=429,
                    detail="今日全站演示额度已用完，明天再来试试（演示环境限制额度以控制成本）",
                )
            if per_ip_daily() and mine >= per_ip_daily():
                conn.execute("ROLLBACK")
                raise HTTPException(
                    status_code=429,
                    detail=f"你今天已用完 {per_ip_daily()} 次演示额度，明天再来试试",
                )

            conn.execute("UPDATE quota SET used=used+1 WHERE day=? AND scope=?", (day, "global"))
            conn.execute("UPDATE quota SET used=used+1 WHERE day=? AND scope=?", (day, ip_scope))
            conn.execute("COMMIT")
            return {
                "ip": ip,
                "ip_used": mine + 1,
                "ip_limit": per_ip_daily(),
                "global_used": total + 1,
                "global_limit": global_daily(),
            }
        finally:
            conn.close()


def snapshot(request) -> dict:
    """只读当前额度（不记账），用于健康检查/前端提示。"""
    if not is_enabled():
        return {"enabled": False}
    day = date.today().isoformat()
    ip = client_ip(request)
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        total = _used(conn, day, "global")
        mine = _used(conn, day, f"ip:{ip}")
        _prune(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()
    return {
        "enabled": True,
        "ip_limit": per_ip_daily(),
        "ip_used": mine,
        "ip_remaining": max(per_ip_daily() - mine, 0) if per_ip_daily() else None,
        "global_limit": global_daily(),
        "global_used": total,
        "max_question_chars": max_question_chars(),
    }


def is_write_blocked(method: str, path: str) -> bool:
    """演示模式下，除问答外的写操作一律拦截。"""
    if not is_enabled():
        return False
    if method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    if not path.startswith("/api"):
        return False
    return not _ALLOWED_WRITE_PATH.match(path)
