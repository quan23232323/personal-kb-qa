"""file_utils 单测：文件名清洗、类型探测（扩展名 + 魔数）。"""
from utils import file_utils


class TestSanitizeFilename:
    def test_keeps_basename_only(self):
        assert file_utils.sanitize_filename("../../etc/passwd") == "passwd"
        assert file_utils.sanitize_filename("C:\\evil\\report.pdf") == "report.pdf"

    def test_replaces_illegal_chars(self):
        assert file_utils.sanitize_filename('a*b<c>d?e"f|g.pdf') == "a_b_c_d_e_f_g.pdf"

    def test_keeps_chinese_and_common_chars(self):
        assert file_utils.sanitize_filename("知识库-RAG_v2.pdf") == "知识库-RAG_v2.pdf"

    def test_empty_becomes_upload(self):
        assert file_utils.sanitize_filename("...") == "upload"
        assert file_utils.sanitize_filename("") == "upload"

    def test_strips_leading_dots(self):
        assert file_utils.sanitize_filename(".hidden.md") == "hidden.md"


class TestDetectType:
    def test_pdf_magic_ok(self):
        assert file_utils.detect_type("a.pdf", b"%PDF-1.7 ...") == "pdf"

    def test_pdf_magic_mismatch_rejected(self):
        # 扩展名是 pdf 但内容不是（伪装文件）
        assert file_utils.detect_type("evil.pdf", b"<html>") is None

    def test_docx_magic_ok(self):
        assert file_utils.detect_type("a.docx", b"PK\x03\x04xxxx") == "docx"

    def test_docx_magic_mismatch_rejected(self):
        assert file_utils.detect_type("a.docx", b"\xd0\xcf\x11\xe0") is None  # 旧版 doc 的 OLE 头

    def test_txt_md_no_magic_needed(self):
        assert file_utils.detect_type("note.txt", b"") == "txt"
        assert file_utils.detect_type("note.MD", b"") == "md"

    def test_disallowed_extension(self):
        assert file_utils.detect_type("script.exe", b"MZ") is None
        assert file_utils.detect_type("photo.jpg", b"\xff\xd8") is None
        assert file_utils.detect_type("legacy.doc", b"\xd0\xcf\x11\xe0") is None  # 旧版 doc 不在白名单

    def test_ooxml_zip_magic_shared(self):
        # docx/xlsx/pptx 都是 OOXML zip 容器，共享 PK 头
        assert file_utils.detect_type("t.xlsx", b"PK\x03\x04...") == "xlsx"
        assert file_utils.detect_type("t.pptx", b"PK\x03\x04...") == "pptx"

    def test_xls_ole_magic(self):
        assert file_utils.detect_type("t.xls", b"\xd0\xcf\x11\xe0...") == "xls"
        # 扩展名 xls 但不是 OLE 头（比如改名的 xlsx）→ 拒绝
        assert file_utils.detect_type("t.xls", b"PK\x03\x04...") is None

    def test_csv_no_magic_needed(self):
        assert file_utils.detect_type("t.CSV", b"") == "csv"
