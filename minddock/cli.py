"""命令行入口：serve（默认）/ seed / check。

Windows 中文环境下 stdio 三件套统一 reconfigure 为 UTF-8，
保证交互与管道驱动时输出不乱码。
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .config import PROJECT_ROOT, load_config
from .notes import NoteStore
from .seed import seed_notes, seed_workspace_fixture
from .server import MindDockServer
from .workspace import WorkspaceReader


def setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, OSError):
            pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def build_app(args) -> tuple[MindDockServer, dict]:
    cfg = load_config(
        data_dir=getattr(args, "data_dir", None),
        workspace_root=getattr(args, "workspace", None),
        host=getattr(args, "host", None),
    )
    data_dir = Path(cfg["data_dir"])
    seeded = seed_notes(data_dir)
    # 驾驶舱：真实工作区不可用时回退到项目内演示夹具
    fixture = PROJECT_ROOT / "data" / "demo-workspace"
    ws_root = cfg["workspace_root"]
    if not ws_root or not Path(ws_root).exists():
        seed_workspace_fixture(fixture)
        ws_root = str(fixture)
        cfg["workspace_root"] = ws_root
        cfg["workspace_is_demo"] = True
    store = NoteStore(data_dir)
    store.ensure_dirs()
    workspace = WorkspaceReader(ws_root)
    port = int(args.port) if getattr(args, "port", None) else int(cfg["port"])
    server = None
    last_err = None
    for p in range(port, port + 10):
        try:
            cfg["port"] = p  # 横幅打印实际绑定端口
            server = MindDockServer((cfg["host"], p), store, workspace, cfg)
            break
        except OSError as e:
            last_err = e
    if server is None:
        raise SystemExit(f"端口 {port}-{port + 9} 均被占用：{last_err}")
    return server, {"seeded": seeded, "cfg": cfg}


def cmd_serve(args) -> int:
    server, info = build_app(args)
    cfg = info["cfg"]
    url = f"http://{cfg['host']}:{cfg['port']}"
    print(f"MindDock v{__version__}")
    print(f"  笔记库   {cfg['data_dir']}" + ("（已播种演示数据）" if info["seeded"] else ""))
    print(f"  驾驶舱   {cfg['workspace_root']}" + ("（演示夹具）" if cfg.get("workspace_is_demo") else "（只读）"))
    print(f"  地址     {url}")
    if cfg.get("open_browser", True) and not getattr(args, "no_browser", False):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print("Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


def cmd_seed(args) -> int:
    cfg = load_config(data_dir=getattr(args, "data_dir", None))
    n = seed_notes(cfg["data_dir"])
    fixture = PROJECT_ROOT / "data" / "demo-workspace"
    seed_workspace_fixture(fixture)
    print(f"播种完成：{n} 篇演示笔记 → {cfg['data_dir']}；演示工作区 → {fixture}")
    return 0


def cmd_export(args) -> int:
    """整库导出为单文件离线 HTML（不依赖运行中的服务）。"""
    from .export_book import build_book_html, load_md_js, referenced_images
    from .attachments import collect_images

    cfg = load_config(data_dir=getattr(args, "data_dir", None))
    store = NoteStore(cfg["data_dir"])
    store.ensure_dirs()
    items = []
    for lite in store.list_notes():
        full = store.get(lite["name"])
        items.append(
            {
                "name": full["name"],
                "title": full["title"],
                "tags": full["tags"],
                "updated": full["updated"],
                "content": full["content"],
                "missing": full["missing"],
                "incoming": full["incoming"],
            }
        )
    atts = collect_images(Path(cfg["data_dir"]), referenced_images(items))
    out = Path(args.output) if args.output else PROJECT_ROOT / "output" / "minddock-book.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    html = build_book_html(items, load_md_js(), attachments=atts)
    out.write_text(html, encoding="utf-8")
    print(f"已导出 {len(items)} 篇笔记 → {out}")
    return 0


def cmd_check(args) -> int:
    cfg = load_config(
        data_dir=getattr(args, "data_dir", None),
        workspace_root=getattr(args, "workspace", None),
    )
    store = NoteStore(cfg["data_dir"])
    store.ensure_dirs()
    st = store.stats()
    ws = WorkspaceReader(cfg["workspace_root"]).overview()
    print(f"MindDock v{__version__} 自检")
    print(f"  数据目录   {cfg['data_dir']}（{st['total']} 篇笔记，{st['words']} 字）")
    print(f"  工作区     {cfg['workspace_root']}")
    print(f"  项目       {ws['stats']['project_total']} 个（完成 {ws['stats']['done']} / 进行 {ws['stats']['active']}）")
    print(f"  避坑教训   {ws['stats']['lesson_count']} 条")
    problems = []
    if not ws["available"]:
        problems.append(ws["error"])
    for p in problems:
        print(f"  [警告] {p}")
    print("自检通过" if not problems else "自检完成（存在警告）")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_stdio()
    parser = argparse.ArgumentParser(prog="minddock", description="MindDock 个人知识库 + 工作区驾驶舱")
    parser.add_argument("--version", action="version", version=f"MindDock {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add_common(p, with_port=True):
        p.add_argument("--data-dir", help="笔记库目录（默认 data/notes）")
        if with_port:
            p.add_argument("--port", type=int, help="服务端口（默认 8765，占用时自动顺延）")
        p.add_argument("--workspace", help="工作区根目录（驾驶舱只读来源）")

    p_serve = sub.add_parser("serve", help="启动服务（默认命令）")
    add_common(p_serve)
    p_serve.add_argument("--host", help="监听地址（默认 127.0.0.1）")
    p_serve.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p_serve.set_defaults(func=cmd_serve, port=None, host=None)

    p_seed = sub.add_parser("seed", help="播种演示数据（仅当笔记库为空）")
    p_seed.add_argument("--data-dir", help="笔记库目录")
    p_seed.set_defaults(func=cmd_seed)

    p_check = sub.add_parser("check", help="自检配置与数据")
    add_common(p_check, with_port=False)
    p_check.set_defaults(func=cmd_check)

    p_export = sub.add_parser("export", help="整库导出为单文件离线 HTML")
    p_export.add_argument("--data-dir", help="笔记库目录")
    p_export.add_argument("--output", help="输出文件路径（默认 output/minddock-book.html）")
    p_export.set_defaults(func=cmd_export, output=None)

    args = parser.parse_args(argv)
    if args.command is None:
        # 允许 `python -m minddock --port 9000` 这类省略 serve 的写法
        raw = sys.argv[1:] if argv is None else argv
        args = parser.parse_args(["serve"] + raw)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
