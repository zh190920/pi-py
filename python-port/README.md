# python-port · 把 Pi（JS）逐函数翻译成 Python

这个文件夹是 `packages/ai` + `packages/agent` 的 Python 移植工作区。目标：**函数、参数、控制流一一对应**，不重构、不「顺手优化」。

## 目录

```
python-port/
├── docs/
│   ├── 00-architecture.md   JS 代码库完整梳理（包、分层、调用链、坑）
│   ├── 01-call-chain.md     50 个核心函数的逐函数对照表 + 事件状态机
│   └── 02-roadmap.md        12 课路线图 + 偏差登记表
├── lessons/
│   ├── 01-message-types.md  第 1 课：消息与内容块
│   └── 02-event-stream.md   第 2 课：事件流
├── pi_py/                   Python 包（边学边长）
│   ├── types.py
│   └── event_stream.py
├── examples/
│   └── 02_event_stream_demo.py   手工推一个流式回复，看事件顺序
└── tests/                   每课一个自测脚本，不依赖 pytest
    ├── test_lesson01.py
    └── test_lesson02.py
```

## 怎么用

按顺序读 `docs/00` → `docs/01` → `docs/02`，然后从 `lessons/01` 开始，每课：

```bash
cd python-port
python tests/test_lesson01.py
python tests/test_lesson02.py
PYTHONIOENCODING=utf-8 python examples/02_event_stream_demo.py
```

要求 Python ≥ 3.8（当前环境 3.8.8 已验证通过）。暂不引入第三方依赖；第 4 课起需要 `jsonschema`，第 9 课起需要 `httpx`。

## 进度

| 课 | 主题 | 对应 JS | 状态 |
|---|---|---|---|
| 00 | 架构梳理 | 全仓库 | ✅ |
| 01 | 消息与内容块 | `ai/types.ts`、`utils/text.ts` | ✅ |
| 02 | 事件流 | `utils/event-stream.ts` | ✅ |
| 03 | 转录层（system 账本） | `utils/transcript.ts` | 待做 |
| 04 | 参数校验 + token 估算 | `utils/validation.ts`、`utils/estimate.ts` | 待做 |
| 05 | provider 公共层 | `api/simple-options.ts`、`api/transform-messages.ts` | 待做 |
| 06 | Agent 循环 | `agent/agent-loop.ts` | 待做 |
| 07 | Agent 外壳 | `agent/agent.ts` | 待做 |
| 08 | 模型注册表 + faux provider | `models.ts`、`providers/faux.ts` | 待做 |
| 09 | OpenAI 兼容适配器 | `api/openai-completions.ts` | 待做 |
| 10 | 工具层 | `coding-agent/src/core/tools/*` | 待做 |
| 11 | 会话与压缩 | `core/agent-session.ts`、`core/compaction/*` | 待做 |
| 12 | CLI 入口 | `coding-agent/src/main.ts` | 待做 |

## 三条铁律

1. **一个函数一个函数翻**，翻完立刻跑测试，不留「半成品大文件」。
2. **有意偏离必须登记**（`docs/02-roadmap.md` 的偏差登记表），否则三个月后没人说得清为什么不一样。
3. **命名**：Python 内部 `snake_case`；出网（provider 请求体、事件 JSON）保持 `camelCase`，只在边界转换。

## 范围说明

「完全转 Python」在工程上分两层：

- **内核（必做）**：`ai` 的消息/流/校验/转录 + `agent` 的循环与外壳 ≈ 8k 行。做完就能跑 agent。
- **产品层（可选）**：`coding-agent` 的 77k 行里，真正需要的是工具、会话、压缩、CLI 入口；`tui`（20k）和 `chord`/`durable`（77k）建议换成 Python 生态里更合适的方案，而不是逐行翻译。

为什么这样切，见 [docs/00-architecture.md](docs/00-architecture.md) 第 2、7 节。
