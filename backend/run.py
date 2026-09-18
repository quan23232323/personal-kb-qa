"""启动入口：python run.py [--reload]

- 读取 config.yaml 的 server.host/port（可用环境变量 BACKEND_PORT 覆盖端口）；
- 绑定前先检测端口占用，被占用时给出可操作的中文提示，
  而不是让 uvicorn 抛一屏英文绑定错误。
"""
import argparse
import socket
import subprocess
import sys

import uvicorn

from config import config


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

    host = config.get("server.host", "127.0.0.1")
    port = int(config.get("server.port", 8000))

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

    _warn_port_overlap(port)
    print(f"PersonalKB-QA 启动中：http://{host}:{port}  （/docs 查看接口文档）")
    uvicorn.run("main:app", host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
