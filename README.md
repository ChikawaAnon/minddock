# MindDock

**MindDock** —— 个人知识库中枢 + 工作区驾驶舱（零依赖本地 Web 应用）。

一个 Python 标准库即可运行的本地知识管理工具：

- **知识库**：Markdown 笔记增删改查、中文友好全文搜索、标签、`[[双向链接]]` 与反链面板、输入即弹出的双链自动补全、大纲导航、每日笔记、回收站、**版本历史**（自动留档可回滚）、力导向关系图谱
- **效率**：`Ctrl+P` 命令面板快速跳转、`Ctrl+K` 搜索、自动保存、重命名全库同步双链
- **驾驶舱**：只读聚合工作区 `projects/README.md` 项目登记表与 `docs/pitfall-log.md` 避坑日志，状态分布环图、近 30 天活跃度、标签分布
- **导出**：单篇笔记与整库均可导出为样式完整的**单文件离线 HTML**（内嵌搜索与双链跳转）
- **零依赖**：运行只需 Python 3.10+ 标准库，前端为原生 HTML/CSS/JS 单页应用，离线可用
- **数据自包含**：内置逼真演示数据开箱即用；配置可指向任意真实笔记目录与工作区（驾驶舱只读）
- **质量**：151 个自动化测试、深浅双主题、桌面/移动双布局

## 快速开始

```bash
git clone https://github.com/ChikawaAnon/minddock.git
cd minddock
python -m minddock            # 默认 127.0.0.1:8765，首次自动播种演示数据
```

或直接双击 `run.bat`。浏览器打开 <http://127.0.0.1:8765>。

完整用法见 **[docs/usage.md](docs/usage.md)**。

## 架构一览

```text
minddock/
├── util.py          编码安全读写、原子写、安全文件名
├── config.py        配置合并（CLI > config.json > 默认）与工作区探测
├── notes.py         NoteStore：frontmatter、增删改查、软删除、每日笔记、统计
├── search.py        搜索引擎：CJK 子串 + ASCII 整词 + 字段加权评分
├── links.py         [[双链]]/行内标签提取、反链索引、图谱构建
├── workspace.py     驾驶舱聚合器（projects 表格 + pitfall 日志解析，只读）
├── export_book.py   整库单文件 HTML 导出（内嵌 md.js 渲染器）
├── server.py        http.server JSON API + 静态资源（线程安全）
├── cli.py           serve / seed / check 命令行入口
├── seed.py          26 篇演示笔记 + 演示工作区夹具
└── static/          index.html + style.css + app.js + md.js（共享渲染器）
```

设计取舍与实现说明见 `docs/process.md`。

## 测试

```bash
python -m pytest tests/ -q     # 151 个用例
```

## 状态

已完成（2026-09-07 通宵迭代）。

## License

MIT