"""检索链路独立验证脚本（开发用，不依赖 LLM key）。

用法：
    python verify_retrieval.py <kb_id> <query>

作用：走 embedding（本地 sentence-transformers）+ Chroma 检索的完整链路，
打印命中的 chunk 与余弦相似度，用于在接入 LLM 前验证 RAG 检索是否正常。
"""
import sys

from services import embedding_service, retrieval_service


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python verify_retrieval.py <kb_id> <query>")
        sys.exit(1)

    kb_id, query = sys.argv[1], sys.argv[2]

    print(f"[1/3] 向量化查询: {query!r}")
    qvec = embedding_service.embed_one(query)
    print(f"      向量维度 = {len(qvec)}")

    print(f"[2/3] 在知识库 {kb_id} 中检索 ...")
    results = retrieval_service.search(kb_id, qvec, top_k=5)

    print("[3/3] 检索结果（按相似度降序）:")
    if not results:
        print("      （无结果）")
        return
    for i, r in enumerate(results, 1):
        print(f"  #{i}  similarity={r['similarity']:.4f}  doc={r['document_name']}")
        print(f"       {r['content'][:120]!r}")


if __name__ == "__main__":
    main()
