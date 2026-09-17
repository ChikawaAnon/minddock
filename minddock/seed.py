"""演示数据生成器：内置逼真的示例笔记库与演示工作区夹具。

笔记库为空时自动播种；演示工作区夹具供驾驶舱在无真实工作区时使用。
所有内容为原创示例，日期相对生成日回溯，保证活动图表真实好看。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from .util import atomic_write

# (笔记名, 标题, 标签, 距今天数, 正文)
DEMO_NOTES: list[tuple[str, str, list[str], int, str]] = [
    ("Python 装饰器入门", "Python 装饰器入门", ["python", "编程"], 28,
     "# 什么是装饰器\n\n装饰器本质上是一个接收函数并返回函数的高阶函数，是 [[函数式编程]] 思想在 Python 里的落地。\n\n## 最小示例\n\n```python\ndef timer(func):\n    def wrapper(*args, **kwargs):\n        import time\n        start = time.perf_counter()\n        result = func(*args, **kwargs)\n        print(f\"{func.__name__} 耗时 {time.perf_counter() - start:.3f}s\")\n        return result\n    return wrapper\n```\n\n## 要点\n\n- 用 `functools.wraps` 保留原函数元信息\n- 带参数的装饰器是三层嵌套\n- 类装饰器用 `__call__` 实现\n\n相关：[[Python 生成器与协程]]、[[设计模式：观察者]]\n"),
    ("Python 生成器与协程", "Python 生成器与协程", ["python", "编程"], 27,
     "# 生成器\n\n生成器用 `yield` 惰性产出数据，处理大文件时内存占用恒定。\n\n## 协程演化\n\n- `yield` → `yield from` → `async/await`\n- `asyncio` 事件循环本质是单线程协作式调度\n\n生成器表达式比列表表达式省内存：\n\n```python\ntotal = sum(x * x for x in range(10 ** 7))\n```\n\n参考 [[Python 装饰器入门]] 里的计时装饰器可以给协程做性能埋点。\n"),
    ("Git 工作流备忘", "Git 工作流备忘", ["工具", "git"], 25,
     "# 常用操作\n\n## 撤销类\n\n- 改最后一次提交信息：`git commit --amend`\n- 回到某次提交但保留改动：`git reset --soft HEAD~1`\n- 只想捡某个提交：`git cherry-pick <sha>`\n\n## 分支策略\n\n个人项目用主干开发 + 特性分支即可，不必套重型流程。\n\n小项目单人开发时，提交信息写清楚「为什么改」比「改了什么」更有价值——diff 本身已经说明了改了什么。\n"),
    ("正则表达式速查", "正则表达式速查", ["工具", "python"], 24,
     "# 正则速查\n\n| 需求 | 写法 |\n| --- | --- |\n| 中文 | `[\\u4e00-\\u9fff]` |\n| 整词 | `\\\\bword\\\\b` |\n| 非贪婪 | `.*?` |\n| 分组命名 | `(?P<name>...)` |\n\n## 贪婪与回溯\n\n`.*` 会吃掉尽量多字符导致意外匹配，解析 HTML 类嵌套结构时正则会指数回溯，该上解析器就上解析器。\n"),
    ("SQL 优化笔记", "SQL 优化笔记", ["数据库", "编程"], 22,
     "# 索引设计\n\n- 最左前缀原则：联合索引 `(a, b, c)` 只有从 a 开始连续命中才有效\n- 覆盖索引避免回表\n- `LIKE '%xx'` 无法走索引，`LIKE 'xx%'` 可以\n\n## 慢查询排查路径\n\n1. `EXPLAIN` 看执行计划\n2. 关注 type 是否全表扫描、rows 是否异常大\n3. 加索引或改写 SQL，而不是先想着加缓存\n"),
    ("Docker 基础", "Docker 基础", ["运维", "工具"], 20,
     "# 核心概念\n\n- 镜像：分层只读模板\n- 容器：镜像的运行实例\n- 数据卷：持久化数据，删除容器不丢\n\n## 常用命令\n\n```bash\ndocker compose up -d\ndocker logs -f <name>\ndocker system prune\n```\n\n镜像分层的意义：Dockerfile 每条指令一层，依赖安装放在拷贝代码之前，代码改动就不会打穿依赖缓存。\n"),
    ("HTTP 状态码备忘", "HTTP 状态码备忘", ["网络", "工具"], 19,
     "# 常用状态码\n\n- `200` 成功；`201` 已创建\n- `301/302` 永久/临时重定向\n- `400` 参数错误；`401` 未认证；`403` 无权限；`404` 不存在\n- `500` 服务端异常；`502` 网关拿到无效响应；`504` 网关超时\n\n排障口诀：4xx 先看自己发的请求，5xx 先看服务端日志。参考 [[WebSocket 入门]] 理解长连接场景下这些状态码何时出现。\n"),
    ("Markdown 语法速查", "Markdown 语法速查", ["工具", "写作"], 18,
     "# 语法\n\n## 任务列表\n\n- [x] 支持 GitHub 风格任务列表\n- [ ] 待办项\n\n## 表格与代码\n\n| 语法 | 效果 |\n| --- | --- |\n| `**粗体**` | **粗体** |\n| `` `代码` `` | `代码` |\n\n围栏代码块三个反引号开头，语言写在后面即可高亮。写 [[周报模板]] 时最常用表格和任务列表。\n"),
    ("设计模式：观察者", "设计模式：观察者", ["编程", "设计模式"], 16,
     "# 观察者模式\n\n一对多依赖：主题状态变化时自动通知所有观察者。\n\n## 适用场景\n\n- 事件总线 / 消息队列的雏形\n- GUI 回调\n- [[WebSocket 入门]] 里的订阅推送本质上就是网络化的观察者\n\n## Python 实现\n\n用 `list` 存回调 + `notify` 遍历即可，十几行代码，不必先上框架。\n"),
    ("WebSocket 入门", "WebSocket 入门", ["网络", "编程"], 15,
     "# 为什么需要 WebSocket\n\nHTTP 是请求-响应模型，服务端无法主动推送。WebSocket 一次握手后升级为全双工长连接。\n\n## 要点\n\n- 握手复用 101 状态码升级协议\n- 心跳保活，断线重连要退避\n- 与 [[HTTP 状态码备忘]] 中 101 的含义一致：Switching Protocols\n"),
    ("TypeScript 类型体操", "TypeScript 类型体操", ["前端", "编程"], 13,
     "# 常用工具类型\n\n- `Partial<T>` / `Required<T>` / `Pick<T, K>`\n- `ReturnType<F>` 提取函数返回值类型\n- 条件类型 + `infer` 推断\n\n## 心得\n\n类型体操写到能让编译器报错就够了，过度追求玄学类型只会让同事读不懂。业务代码里 `unknown` + 收窄比 `any` 安全得多。\n"),
    ("前端性能优化", "前端性能优化", ["前端", "编程"], 12,
     "# 指标\n\n- LCP：最大内容绘制，2.5s 内\n- INP：交互响应，200ms 内\n- CLS：累积布局偏移，0.1 以内\n\n## 手段\n\n1. 图片懒加载 + 现代格式\n2. 关键 CSS 内联，JS 异步加载\n3. 长列表虚拟滚动\n\n先测再改：没有 Performance 面板数据支撑的优化都是玄学。\n"),
    ("读书笔记：卡片笔记写作法", "读书笔记：卡片笔记写作法", ["读书", "知识管理"], 11,
     "# 核心观点\n\n笔记的价值不在收集而在连接。文献笔记用自己的话重写；永久笔记面向某个主题成文；卡片之间主动建立链接，让网络自己长出结构。\n\n## 实践\n\n- 每张卡片只写一个想法\n- 写新卡片时问：这和已有的哪张卡片有关？\n- 定期回看，把孤岛卡片合并或删除\n\n这正是本知识库用 [[知识管理方法论]] 做双向链接的理论来源，也呼应了 [[读书笔记：原子习惯]] 里的复利效应。\n"),
    ("读书笔记：原子习惯", "读书笔记：原子习惯", ["读书", "知识管理"], 10,
     "# 四定律\n\n1. 让提示显而易见\n2. 让渴望有吸引力\n3. 让行动简便易行\n4. 让奖励令人愉悦\n\n## 金句\n\n「你不会上升到自己目标的高度，只会跌到自己系统的水平。」\n\n与 [[读书笔记：卡片笔记写作法]] 的每日卡片写作正好互为系统与目标的关系。\n"),
    ("知识管理方法论", "知识管理方法论", ["知识管理", "方法论"], 9,
     "# 我的流程\n\n```text\n收集箱 → 每日笔记 → 整理成永久笔记 → 打标签 + 建双链\n```\n\n## 原则\n\n- 收集要快，整理要定期\n- 一切笔记最终要能被搜索找到，否则等于没记\n- 标签不超过两层：`领域/子题`\n\n工具上用 [[Markdown 语法速查]] 里的表格做模板，配合 [[周报模板]] 做每周回顾。\n"),
    ("GTD 时间管理", "GTD 时间管理", ["方法论", "效率"], 8,
     "# 五步\n\n收集 → 理清 → 组织 → 回顾 → 执行\n\n## 两分钟法则\n\n能两分钟做完的事立刻做，不要进任务清单。\n\n每周回顾是 GTD 成败的分水岭：清单不回顾就只是愿望列表。相关：[[知识管理方法论]]\n"),
    ("周报模板", "周报模板", ["模板", "写作"], 7,
     "# 本周完成\n\n- \n\n# 数据与进展\n\n| 事项 | 状态 | 备注 |\n| --- | --- | --- |\n|  |  |  |\n\n# 下周计划\n\n- [ ] \n\n# 风险与需要的支持\n\n- \n\n> 使用：复制本模板新建笔记，标题写周一起始日期。\n"),
    ("面试准备：电气八股清单", "面试准备：电气八股清单", ["求职", "电气"], 6,
     "# 电机与拖动\n\n- 三相异步电动机的转差率定义与计算\n- 变压器并列运行条件\n\n# 电力电子\n\n- Buck/Boost 占空比与输入输出关系\n- SPWM 原理\n\n# 自控\n\n- 一阶二阶系统时域指标\n- 稳定性判据：劳斯、奈奎斯特\n\n结合 [[平衡车项目记录]] 里的实物经验回答，比背书有说服力。\n"),
    ("平衡车项目记录", "平衡车项目记录", ["项目", "电气"], 5,
     "# 系统结构\n\n```text\nMPU6050 → 互补滤波/卡尔曼 → PID → PWM → 电机\n```\n\n## 调参记录\n\n- 先内环角度环后外环速度环\n- Kp 从小往上加直到轻微振荡，回退 30%\n\n## 踩坑\n\n- 陀螺仪零漂要用机械中值校准\n- 电池电压跌落会导致参数漂移，低压报警要有\n\n下一步想加 [[PLC 入门笔记]] 里提到的上位机监控思路，用串口把姿态数据画成实时曲线。\n"),
    ("PLC 入门笔记", "PLC 入门笔记", ["电气", "工业"], 4,
     "# 基础\n\n- 扫描周期三步：读输入 → 执行逻辑 → 写输出\n- 梯形图左右母线，触点串并联即逻辑与或\n\n# 选型\n\n点数预留 20% 余量；输出型式按负载选继电器/晶体管。\n\n工业现场和 [[平衡车项目记录]] 的嵌入式方案对比：PLC 胜在可靠与易维护，嵌入式胜在成本与灵活性。\n"),
    ("智能家居面板想法", "智能家居面板想法", ["想法", "硬件"], 3,
     "# 目标\n\n一块挂墙 e-ink 面板：天气、日程、待办、公交到站。\n\n## 方案\n\n- 主控 ESP32 + e-ink 4.2 寸\n- 数据源走家庭服务器聚合 JSON\n- 外壳 3D 打印磁吸\n\n供电与刷新率是 e-ink 的两大坑，先做原型验证再谈美观。属于 [[项目想法汇总]] 的一部分。\n"),
    ("项目想法汇总", "项目想法汇总", ["想法", "项目"], 2,
     "# 待孵化\n\n- [[智能家居面板想法]]：e-ink 挂墙面板\n- 命令行记账工具：CSV 导入 + 分类统计\n- 博客：把 [[读书笔记：卡片笔记写作法]] 的实践写成系列\n\n# 评估维度\n\n价值、成本、可维护性三者打分，总分高者优先。\n"),
    ("2026-09-01", "2026-09-01", ["每日笔记"], 6,
     "# 今日完成\n\n- 平衡车内环 PID 调参，能自稳 30 秒\n- 看完 [[PLC 入门笔记]] 扫描周期部分\n\n# 明日计划\n\n- 速度环参数\n\n# 随记\n\n调参要有耐心，一次只动一个参数。\n"),
    ("2026-09-02", "2026-09-02", ["每日笔记"], 5,
     "# 今日完成\n\n- 速度环加入微分抑制抖动\n- 投出 5 份简历\n\n# 明日计划\n\n- 整理 [[面试准备：电气八股清单]] 自控部分\n\n# 随记\n\n晚上跑步 5km，状态不错。\n"),
    ("2026-09-04", "2026-09-04", ["每日笔记"], 3,
     "# 今日完成\n\n- 写完自控八股 20 题\n- [[智能家居面板想法]] 画了系统框图\n\n# 明日计划\n\n- 模拟面试一次\n\n# 随记\n\n面试官更喜欢听「为什么这么选型」而不是名词堆砌。\n"),
    ("2026-09-06", "2026-09-06", ["每日笔记"], 1,
     "# 今日完成\n\n- 搭了本知识库，把散落的笔记收拢\n- [[读书笔记：卡片笔记写作法]] 读完第三章\n\n# 明日计划\n\n- 把每日笔记模板固化\n\n# 随记\n\n工具是手段，写下来才是目的。\n"),
]

DEMO_PROJECTS_ROWS = """| 序号 | 项目目录 | 说明 | 状态 |
| --- | --- | --- | --- |
| 001 | `Project-001-demo-setup` | 演示项目一：环境搭建与规范落地 | 已完成 |
| 002 | `Project-002-demo-agent` | 演示项目二：多模态 Agent 原型 | 已完成 |
| 003 | `Project-003-demo-migration` | 演示项目三：数据迁移指南 | 进行中 |
| 004 | `Project-004-demo-audit` | 演示项目四：整机体检报告 | 已完成 |
| 005 | `Project-005-demo-hub` | 演示项目五：信息聚合站 | 进行中 |
"""

DEMO_PITFALLS = """# 避坑日志（演示数据）

## 记录标准

- 记录：重复出现的错误、方向性错误、影响数据/安全/架构的问题
- 不记录：一次性小错、已彻底解决且无复用价值的细节

## 当前有效教训

1. **中文与编码**：读取或写入中文文件时显式使用 UTF-8；Windows 下的脚本注意 BOM 与 GBK 回退。
2. **大文本写入**：优先直接写文件，避免多层引号和转义。
3. **任务收尾**：产出型任务完成并验证后再结束；中断后下一轮续做，不重新开始。

## 2026-08-29：演示坑一：环境变量覆盖配置文件

- 任务：演示聚合器读取配置。
- 坑：环境变量优先级高于配置文件，调试时改配置不生效。
- 解决：统一在启动日志打印最终生效配置。
- 教训：多层配置必须显式声明优先级并在日志中可观测。

## 2026-08-30：演示坑二：管道输入的编码陷阱

- 任务：演示 CLI 支持管道输入。
- 坑：Windows 中文环境管道 stdin 默认按 GBK 解码，中文变乱码。
- 解决：入口对 stdin/stdout/stderr 统一 reconfigure 为 UTF-8。
- 教训：既交互又可管道驱动的 CLI，验收必须走一遍管道输入。
"""


def _paths_from_days(days: int) -> tuple[int, int]:
    """把「距今天数」换算成 mtime 时间戳，让列表排序与活动图自然分布。"""
    base = datetime.now() - timedelta(days=days)
    return int(base.timestamp()), int((base + timedelta(hours=2)).timestamp())


def seed_notes(data_dir: str | Path) -> int:
    """向 data_dir 播种演示笔记，返回写入数量；目录非空时跳过。"""
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    existing = list(root.glob("*.md"))
    if existing:
        return 0
    from .notes import serialize_note

    count = 0
    for name, title, tags, days, body in DEMO_NOTES:
        created_ts, updated_ts = _paths_from_days(days)
        created = datetime.fromtimestamp(created_ts).replace(microsecond=0).isoformat()
        updated = datetime.fromtimestamp(updated_ts).replace(microsecond=0).isoformat()
        fm = {"title": title, "tags": tags, "created": created, "updated": updated}
        path = root / f"{name}.md"
        atomic_write(path, serialize_note(fm, body))
        os.utime(path, (created_ts, updated_ts))
        count += 1
    return count


def seed_workspace_fixture(root: str | Path) -> Path:
    """生成演示工作区夹具（projects/README.md + docs/pitfall-log.md）。"""
    root = Path(root)
    atomic_write(root / "projects" / "README.md", DEMO_PROJECTS_ROWS)
    atomic_write(root / "docs" / "pitfall-log.md", DEMO_PITFALLS)
    return root


def seed_all(data_dir: str | Path, fixture_dir: str | Path) -> None:
    seed_notes(data_dir)
    seed_workspace_fixture(fixture_dir)
