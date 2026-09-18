"""pytest 公共配置：把 backend 目录加入 sys.path，保证 `import config` 等可用。"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
