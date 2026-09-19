"""检索策略对比评测：纯向量 / BM25 / 混合 + RRF。

用途：用可复核的数据回答「为什么这个项目要做混合检索」，
而不是只说"用了 RRF"。结论见 docs/retrieval-eval.md。

评测集构建方式：按知识库每篇文档的主题逐篇写一条**改写式**问题
（刻意避开文档标题用词，否则会高估关键词路），正解 = 该篇文档名。

用法：
    cd backend
    PKB_CONFIG=config.demo.yaml python retrieval_eval.py     # 演示库（21 篇 / 699 分块）
    或直接 python retrieval_eval.py                          # 默认读 config.yaml 的知识库
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# 复用 config.py 的 .env 加载逻辑（HF_ENDPOINT / 密钥等）
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from services import (  # noqa: E402
    chat_service,
    embedding_service,
    kb_service,
    retrieval_service,
)

# ===== 评测集：(问题, 正解文档名) =====
CASES: list[tuple[str, str]] = [
    ("大模型的输出为什么每次都不一样", "01-基础概念.md"),
    ("为什么要把文字切成更小的单位再喂给模型", "01-基础概念.md"),
    ("把词变成向量以后为什么能表达语义关系", "01-基础概念.md"),
    ("残差连接是用来解决什么问题的", "02-Transformer原理.md"),
    ("归一化一般放在网络结构的哪个位置", "02-Transformer原理.md"),
    ("怎么让模型稳定地输出 JSON 这类结构化数据", "03-Prompt工程.md"),
    ("给模型设定一个人格角色为什么能提升效果", "13-Prompt技巧原理详解.md"),
    ("文档切块的时候为什么要留一部分重复内容", "14-RAG工程细节详解.md"),
    ("切块太大或者太小分别会带来什么麻烦", "14-RAG工程细节详解.md"),
    ("两路召回结果怎么合并不需要做分数归一化", "14-RAG工程细节详解.md"),
    ("衡量两个向量方向接近程度该怎么算", "12-向量与相似度详解.md"),
    ("向量数据库为什么需要近似最近邻算法", "项目-RAG检索专题详解.md"),
    ("只调一小部分参数就能适配新任务的方法叫什么", "05-微调入门.md"),
    ("让模型对齐人类偏好通常分几个阶段", "05-微调入门.md"),
    ("模型编造事实是缺陷吗", "06-评估与安全.md"),
    ("怎么判断一个检索问答系统做得好不好", "06-评估与安全.md"),
    ("模型是怎么知道该调用哪个外部能力的", "07-Agent智能体.md"),
    ("多个智能体互相配合有哪几种组织方式", "07-Agent智能体.md"),
    ("图片是怎么变成模型能处理的序列的", "08-多模态.md"),
    ("从噪声一步步生成图像靠的是什么机制", "08-多模态.md"),
    ("上下文窗口里的空间该怎么分配才合理", "15-上下文工程详解.md"),
    ("为什么让模型多想一会儿反而更准", "16-推理模型详解.md"),
    ("会思考的模型那种内部草稿是怎么练出来的", "16-推理模型详解.md"),
    ("同步函数和异步函数在服务端该怎么选", "项目-FastAPI并发专题详解.md"),
    ("这个项目用了哪些手段避免模型乱编答案", "项目-DESIGN.md"),
]

DEPTH = 10


def _ranked_docs(hits: list[dict]) -> list[str]:
    """把检索结果压成「文档名有序去重列表」，用于按文档粒度判定命中。"""
    out: list[str] = []
    for h in hits:
        name = h.get("document_name") or ""
        if name and name not in out:
            out.append(name)
    return out


def _metrics(ranked: list[str], expected: str) -> tuple[bool, bool, bool, float]:
    r1 = bool(ranked) and ranked[0] == expected
    r3 = expected in ranked[:3]
    r5 = expected in ranked[:5]
    mrr = 0.0
    for i, name in enumerate(ranked, 1):
        if name == expected:
            mrr = 1.0 / i
            break
    return r1, r3, r5, mrr


def main() -> None:
    kbs = kb_service.list_kbs()
    if not kbs:
        print("没有知识库，无法评测")
        return
    kb = kbs[0]
    total = retrieval_service._collection(kb["id"]).count()
    print("知识库：%s（%d 个分块）" % (kb["name"], total))
    print("评测集：%d 条    单路/融合深度 top%d" % (len(CASES), DEPTH))
    print()

    agg = {"语义": [0, 0, 0, 0.0], "关键词": [0, 0, 0, 0.0], "混合+RRF": [0, 0, 0, 0.0]}
    detail = []

    for question, expected in CASES:
        qv = embedding_service.embed_one(question)
        sem = retrieval_service.search(kb["id"], qv, DEPTH)
        kw = retrieval_service.bm25_search(kb["id"], question, DEPTH)
        fused = chat_service._rrf_fuse(sem, kw, DEPTH)

        rec = {"q": question, "expected": expected}
        for name, hits in (("语义", sem), ("关键词", kw), ("混合+RRF", fused)):
            ranked = _ranked_docs(hits)
            r1, r3, r5, mrr = _metrics(ranked, expected)
            agg[name][0] += r1
            agg[name][1] += r3
            agg[name][2] += r5
            agg[name][3] += mrr
            rec[name] = (ranked[0] if ranked else "(空)", r1, r5)
        detail.append(rec)

    n = len(CASES)
    print("=" * 96)
    print("%-12s %8s %8s %8s %8s" % ("策略", "R@1", "R@3", "R@5", "MRR"))
    print("-" * 96)
    for name in ("语义", "关键词", "混合+RRF"):
        a = agg[name]
        print("%-12s %7.1f%% %7.1f%% %7.1f%% %8.3f" % (
            name, a[0] / n * 100, a[1] / n * 100, a[2] / n * 100, a[3] / n))
    print("=" * 96)
    print()

    print("逐条明细（标记 ✓=首位命中  ~=前5命中  ✗=前5未命中）")
    print("-" * 96)
    all_miss = []
    for r in detail:
        parts = []
        for name in ("语义", "关键词", "混合+RRF"):
            top1, r1, r5 = r[name]
            parts.append("%s:%s%s" % (name, "✓" if r1 else ("~" if r5 else "✗"), top1[:24]))
        print("Q: %s" % r["q"])
        print("   正解 %s" % r["expected"])
        print("   %s" % "   |   ".join(parts))
        if not any(r[nm][2] for nm in ("语义", "关键词", "混合+RRF")):
            all_miss.append(r)

    print()
    print("=" * 96)
    if all_miss:
        print("三路前 5 均未命中（需人工复核标注是否过窄）：")
        for r in all_miss:
            print("  - %s   （标注：%s）" % (r["q"], r["expected"]))
    else:
        print("所有问题至少有一路在前 5 命中正解")


if __name__ == "__main__":
    main()
