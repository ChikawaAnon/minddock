"""配置管理：内置默认值 < 项目根 config.json < 调用方覆盖参数。

项目根通过本文件位置向上推导，避免对工作目录的依赖。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "host": "127.0.0.1",
    "port": 8765,
    # 笔记库目录：None 表示用默认 data/notes（相对项目根）
    "data_dir": None,
    # 工作区根目录（驾驶舱只读）：None 表示自动探测
    "workspace_root": None,
    "open_browser": True,
    # 应用内登录鉴权（公网部署用）：两项都配置才启用；缺省不启用（本机/测试行为不变）
    "auth_salt": None,
    "password_sha256": None,
}

CONFIG_FILE = PROJECT_ROOT / "config.json"


def detect_workspace_root() -> Path | None:
    """自动探测工作区根：要求存在 projects/README.md 标志文件。"""
    candidates = [PROJECT_ROOT.parent.parent, Path.cwd()]
    for c in candidates:
        if (c / "projects" / "README.md").exists():
            return c
    return None


def load_config(**overrides) -> dict:
    """合并配置并解析为绝对路径。覆盖优先级：CLI 参数 > config.json > 默认。"""
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
        except (json.JSONDecodeError, OSError):
            pass  # 配置文件损坏时静默回退默认值，保证服务可启动
    for k, v in overrides.items():
        if v is not None and k in DEFAULTS:  # 未知键一律不进配置
            cfg[k] = v

    data_dir = Path(cfg["data_dir"]) if cfg["data_dir"] else PROJECT_ROOT / "data" / "notes"
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    cfg["data_dir"] = str(data_dir)

    ws = cfg.get("workspace_root")
    if ws:
        ws_path = Path(ws)
        if not ws_path.is_absolute():
            ws_path = PROJECT_ROOT / ws_path
    else:
        ws_path = detect_workspace_root()
    cfg["workspace_root"] = str(ws_path) if ws_path else None
    return cfg
