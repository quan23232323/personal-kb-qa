"""启动入口：python run.py [--reload]

- 监听地址解析优先级：云平台注入的 PORT（PaaS 约定，同时改为监听 0.0.0.0）
  → BACKEND_PORT → config.yaml 的 server.host/port；
- 启动前做一次依赖与应用导入自检，把「缺依赖」这类问题在前台报清楚；
- 绑定前先检测端口占用，被占用时给出可操作的中文提示，
  而不是让 uvicorn 抛一屏英文绑定错误。
"""
import argparse
import importlib
import os
import socket
import subprocess
import sys
import traceback

import uvicorn

from config import config

# 运行时必需模块，用于启动自检。
# 只列「真正会被导入」的：aiofiles 虽在 requirements.txt 里，但全项目无任何引用，
# 列进来只会制造假警报（部署时已实测踩到过）。
_REQUIRED_MODULES = [
    "fastapi",
    "uvicorn",
    "starlette",
    "pydantic",
    "yaml",
    "sse_starlette",
    "openai",
    "httpx",
    "multipart",
    "chromadb",
    "rank_bm25",
]


def preflight() -> bool:
    """导入自检：把「缺依赖 / 应用导入失败」变成一段可读的结论。

    云平台通常只回传日志尾部，因此结论必须放在最后一行打印。
    """
    missing: list[str] = []
    for mod in _REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            missing.append("%s (%s: %s)" % (mod, type(exc).__name__, exc))

    ok = True
    detail = ""
    tb = ""
    try:
        importlib.import_module("main")
    except Exception as exc:
        ok = False
        detail = "%s: %s" % (type(exc).__name__, exc)
        tb = traceback.format_exc(limit=10)

    print("[自检] Python %s" % sys.version.split()[0], file=sys.stderr)
    print("[自检] 缺失依赖: %s" % (", ".join(missing) if missing else "无"), file=sys.stderr)
    print("[自检] 应用导入: %s" % ("成功" if ok else "失败"), file=sys.stderr)
    if not ok:
        print(tb, file=sys.stderr)
    print("[自检结论] %s" % ("一切正常" if ok and not missing else (detail or "缺少依赖 " + ", ".join(missing))), file=sys.stderr)
    return ok and not missing


def resolve_bind() -> tuple[str, int, bool]:
    """返回 (host, port, 是否为云部署模式)。

    云部署（Heroku / Render / Railway / 各类容器平台）统一注入 `PORT` 环境变量，
    并要求服务监听 0.0.0.0 才能被反向代理访问。检测到 `PORT` 即切换为该约定，
    本地开发仍走 config.yaml，行为不变。
    """
    host = config.get("server.host", "127.0.0.1")
    port = int(config.get("server.port", 8000))

    env_port = os.environ.get("PORT")
    cloud = env_port is not None
    if env_port is None:
        env_port = os.environ.get("BACKEND_PORT")

    if env_port:
        try:
            port = int(str(env_port).strip())
        except ValueError:
            print(f"[警告] 环境变量中的端口 {env_port!r} 不是整数，改用 {port}", file=sys.stderr)

    if cloud:
        # 平台通常还允许用 HOST 覆盖，默认 0.0.0.0（必须对所有网卡可见）
        host = os.environ.get("HOST") or "0.0.0.0"
    elif os.environ.get("HOST"):
        host = os.environ["HOST"]

    return host, port, cloud


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _netstat_lines(port: int) -> list[str]:
    """找出监听该端口的所有 netstat 行（Windows），失败返回空列表。"""
    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=10)
    except Exception:
        return []
    # netstat 输出是系统 OEM 编码（中文系统为 GBK），按 utf-8 严格解码会崩；
    # 这里只解析 ASCII 列（地址/端口/状态/PID），errors=replace 即可
    out = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    needle = f":{port} "
    return [
        ln.strip()
        for ln in out.splitlines()
        if needle in ln and "LISTENING" in ln.upper()
    ][:6]


def _warn_port_overlap(port: int) -> None:
    """绑定成功但端口上还有其他监听者（如 Docker 的 0.0.0.0/[::] 通配转发）时提醒。

    Windows 下绑定 127.0.0.1 能与通配监听共存，IPv4 回环流量通常到本服务；
    但 `localhost` 可能解析为 ::1 而落到其他程序（如容器服务），造成「打开的
    不是本系统」的困惑，故明确提示而非直接报错。
    """
    others = [ln for ln in _netstat_lines(port) if not ln.startswith("127.0.0.1:")]
    if not others:
        return
    print(f"[警告] 端口 {port} 上还有其他程序在监听（本服务绑定的是 127.0.0.1）：", file=sys.stderr)
    for ln in others:
        print(f"    {ln}", file=sys.stderr)
    print(
        "  说明：用 http://127.0.0.1:%d 访问的是本服务；但 localhost 可能被解析为\n"
        "  IPv6 (::1) 而打开上面的其他程序（例如 Docker 容器里的服务）。\n"
        "  如遇「页面不是本系统」，建议换端口：set BACKEND_PORT=8001 后重新启动。\n"
        % port,
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="PersonalKB-QA 后端启动入口")
    parser.add_argument("--reload", action="store_true", help="代码变更自动重载（开发用）")
    args = parser.parse_args()

    host, port, cloud = resolve_bind()

    # 自检放在端口检查之前：缺依赖时给出的是根因，而不是误导性的端口错误
    if not preflight():
        sys.exit(1)

    if not _port_available(host, port):
        print(f"[错误] 端口 {port} 已被占用，无法在 {host}:{port} 启动服务。\n", file=sys.stderr)
        listeners = _netstat_lines(port)
        if listeners:
            print("占用该端口的进程（netstat 输出，最后一列是 PID）：")
            for ln in listeners:
                print(f"    {ln}", file=sys.stderr)
            print(file=sys.stderr)
        print(
            "解决方法（任选其一）：\n"
            f"  1) 停止占用端口的程序（例如本服务已在运行，或 Docker 容器映射了 {port}）；\n"
            f"  2) 换端口启动：CMD 执行 set BACKEND_PORT=8001 后重新运行本脚本；\n"
            f"  3) 或修改 backend/config.yaml 的 server.port。",
            file=sys.stderr,
        )
        sys.exit(1)

    if not cloud:
        # netstat 为 Windows 专有命令，云环境（Linux 容器）无需也不适用
        _warn_port_overlap(port)
        print(f"PersonalKB-QA 启动中：http://{host}:{port}  （/docs 查看接口文档）")
    else:
        print(f"PersonalKB-QA 云部署模式启动：0.0.0.0:{port}（PORT 由平台注入）")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=args.reload,
        # 云部署经反向代理转发：信任 X-Forwarded-* 才能拿到真实访客 IP
        # （演示模式的按 IP 限额依赖它；另有全站硬上限兜底，不惧伪造头）
        proxy_headers=cloud,
        forwarded_allow_ips="*" if cloud else None,
    )


if __name__ == "__main__":
    main()
