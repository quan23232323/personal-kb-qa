"""配置加载：读取 config.yaml，支持 ${ENV_VAR} 环境变量展开。"""
import os
import re
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _load_dotenv(path: Path | None = None) -> None:
    """加载 backend/.env 到环境变量（不存在则跳过；不覆盖已存在的变量）。

    支持 `KEY=value` 与 `KEY="value"` 形式，# 开头为注释。
    这样用户无需手动 export，密钥也保留在 gitignore 的 .env 中不入库。
    """
    env_file = Path(path) if path else BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _expand_env(value: Any) -> Any:
    """递归展开 ${ENV_VAR}，若环境变量不存在则保留原文。"""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class Config:
    def __init__(self, data: dict):
        self.data = data

    def get(self, path: str, default: Any = None) -> Any:
        """按点分路径取值，如 config.get('retrieval.top_k')。"""
        node: Any = self.data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def resolve_path(self, p: str) -> Path:
        """把相对路径解析为基于 backend/ 目录的绝对路径。"""
        path = Path(p)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path


def load_config(path: str | Path | None = None) -> Config:
    target = Path(path) if path else BASE_DIR / "config.yaml"
    with open(target, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(_expand_env(data))


# 全局单例：模块导入即加载一次（先加载 .env，再展开 ${...}）
_load_dotenv()
config = load_config()
