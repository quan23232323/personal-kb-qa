"""文件处理工具：扩展名白名单、魔数校验、文件名清洗。"""
import re
from pathlib import Path

ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx", "xlsx", "xls", "csv", "pptx"}

# 每种类型对应的文件头魔数（txt/md/csv 无可靠魔数，跳过）
# docx/xlsx/pptx 均为 OOXML zip 容器，共享 PK 头；xls 为旧版 OLE 复合文档
MAGIC_BYTES = {
    "pdf": [b"%PDF"],
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
    "xls": [b"\xd0\xcf\x11\xe0"],
}


def sanitize_filename(filename: str) -> str:
    """取 basename、剥离路径穿越、过滤非法字符。"""
    name = Path(filename).name
    # 保留中文/字母/数字/下划线/连字符/点
    name = re.sub(r"[^\w.\-一-鿿]+", "_", name)
    name = name.strip("._")
    if not name:
        name = "upload"
    return name


def detect_type(filename: str, head: bytes) -> str | None:
    """根据扩展名 + 文件头魔数判断类型；不匹配返回 None。"""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        return None
    magic = MAGIC_BYTES.get(ext)
    if magic:
        return ext if any(head.startswith(m) for m in magic) else None
    return ext
