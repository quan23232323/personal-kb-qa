"""retrieval_service 纯函数单测：中文 bigram 分词、chunk 序号解析。"""
from services import retrieval_service


class TestTokenize:
    def test_english_lowercased(self):
        assert retrieval_service._tokenize("RAG Agents") == ["rag", "agents"]

    def test_numbers_kept_whole(self):
        assert retrieval_service._tokenize("GPT-4o 2026") == ["gpt", "4o", "2026"]

    def test_chinese_bigram(self):
        # 知识库 -> 知识 / 识库，无单字噪声
        assert retrieval_service._tokenize("知识库") == ["知识", "识库"]

    def test_mixed_text(self):
        tokens = retrieval_service._tokenize("RAG检索优化")
        assert tokens == ["rag", "检索", "索优", "优化"]

    def test_empty_and_punct_only(self):
        assert retrieval_service._tokenize("") == []
        assert retrieval_service._tokenize("！？。，") == []

    def test_no_single_char_noise(self):
        # 单个汉字不产生 token（噪声控制设计）
        assert retrieval_service._tokenize("我") == []


class TestChunkIndex:
    def test_valid_suffix(self):
        assert retrieval_service._chunk_index("doc-uuid_12") == 12

    def test_invalid_suffix_returns_zero(self):
        assert retrieval_service._chunk_index("doc-uuid_x") == 0

    def test_content_containing_underscore(self):
        # 文档 id 本身含下划线时取最后一段
        assert retrieval_service._chunk_index("a_b_3") == 3
