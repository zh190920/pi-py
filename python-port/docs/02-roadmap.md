# 02 · 移植路线图（12 课）

原则：**每一课都能独立运行、独立验证**，绝不留「先写 3000 行再调试」的坑。

## 里程碑

| 里程碑 | 课程 | 达成标志 |
|---|---|---|
| M1 地基 | 01–02 | 消息类型 + 事件流可单测 |
| M2 请求组装 | 03–05 | 能把 `AgentMessage[]` 组装成 provider 能吃的请求体 |
| **M3 离线跑通循环** | 06–08 | **用 faux provider 跑完 `prompt → assistant → toolCall → toolResult → 再请求 → 结束`，零网络** |
| M4 接真模型 | 09 | 用 OpenAI 兼容接口拿到真实流式回复 |
| M5 可用的 coding agent | 10–12 | 有 read/write/edit/bash 工具、会话落盘、print 模式 CLI |

**M3 是整个项目最关键的节点**：它证明循环逻辑移植正确。之后每一步都只是「换适配器」。

---

## 课程清单

### 第 1 课 · 消息与内容块 ✅
- 对应：`ai/types.ts`（消息部分）、`utils/text.ts`
- 产物：`pi_py/types.py`
- 关键点：dataclass 化、判别字段 `init=False`、`default_factory`、`undefined`/`None` 映射

### 第 2 课 · 事件流 ✅
- 对应：`utils/event-stream.ts`（135 行）
- 产物：`pi_py/event_stream.py`
- 关键点：`asyncio.Future` 复刻 Promise 队列、`_UNSET` 哨兵、`Math.round` 舍入差异、终止事件的投递顺序

### 第 3 课 · 转录层（system 账本）
- 对应：`utils/transcript.ts`（263 行，10 个函数）
- 产物：`pi_py/transcript.py`
- 要翻译：`createInitialSystemMessage`、`normalizeContext`、`getCurrentTools`、`getCurrentSystemMessage`、`getCurrentSystemPrompt`、`collapseSystemMessages`、`resolveTranscript`、`toToolDeclaration`、`declarationsEqual`、`getToolStateChanges`
- 关键点：**回放语义**。prompt 和工具不是字段，是历史消息的折叠结果；`toolsRemoved` 与 `toolsAdded` 的应用顺序（先删后加）决定了同名重定义的行为
- 验收：构造 3 条 system 消息（初始 + 改 section + 增删工具），断言回放出的 prompt 与工具表

### 第 4 课 · 参数校验与 token 估算
- 对应：`utils/validation.ts`（353）、`utils/estimate.ts`（117）
- 产物：`pi_py/validation.py`、`pi_py/estimate.py`
- 要翻译：`validateToolCall`、`validateToolArguments`、`normalizeOptionalNulls`、`coerceWithJsonSchema`、`coercePrimitiveByType`、`applySchemaObjectCoercion`、`applySchemaArrayCoercion`、`coerceWithUnionSchema`、`formatValidationPath`、`calculateContextTokens`、`estimateTextTokens`、`estimateMessageTokens`、`estimateContextTokens`
- 关键点：`typebox` 换成 `jsonschema`（校验）+ 自己写的 coercion（转换）；`WeakMap` 缓存换成 `functools.lru_cache`（按 schema JSON 串）
- 验收：喂 `{"path": 123, "limit": "5"}` 给 `{path:string, limit:integer}` schema，得到 `{"path":"123","limit":5}`；非法参数得到和 JS 同格式的错误文本

### 第 5 课 · provider 公共层
- 对应：`api/simple-options.ts`（109）、`api/transform-messages.ts`（256）、`utils/text.ts` 剩余部分
- 产物：`pi_py/simple_options.py`、`pi_py/transform_messages.py`
- 要翻译：`buildBaseOptions`、`clampMaxTokensToContext`、`resolveSamplingParams`、`adjustMaxTokensForThinking`、`thinkingBudgetForLevel`、`transformMessages`、`downgradeUnsupportedImages`、`splitErrorToolResultImages`、`replaceImagesWithPlaceholder`
- 关键点：`transformMessages` 的两遍扫描——第一遍清洗内容块（丢别家 thinking / 去 thoughtSignature / 归一 toolCallId），第二遍给孤儿 toolCall 补「No result provided」；不这样做，切模型后历史会让 API 直接 400
- 验收：构造「assistant 有 2 个 toolCall，但只有 1 个 toolResult」的历史，断言补出 1 条 error 结果

### 第 6 课 · Agent 循环（核心）
- 对应：`agent/agent-loop.ts`（959 行，15 个函数）
- 产物：`pi_py/agent_loop.py`
- 顺序：`agent_loop` → `run_agent_loop` → `run_loop` → `stream_assistant_response` → `declare_tool_changes` → `execute_tool_calls*` → `prepare/execute/finalize_tool_call` → 小工具函数
- 关键点：
  - 内层循环条件 `hasMoreToolCalls || pendingMessages.length > 0`，外层处理 follow-up
  - `message.stopReason === "length"` 时**所有**工具调用判失败（参数可能被截断）
  - 串行 vs 并行：并行只并发**执行**，准备阶段仍串行，且结果消息按源顺序产出
  - `afterToolCall` 的字段级覆盖：给了 `content` 却没给 `structuredContent` 时，structuredContent 必须丢弃
- 验收：注入假的 `stream_fn`（直接返回预置事件序列）和假工具，断言事件顺序与 JS 一致（见 `docs/01-call-chain.md` 的状态机速查）

### 第 7 课 · Agent 外壳
- 对应：`agent/agent.ts`（623 行）
- 产物：`pi_py/agent.py`
- 要翻译：`Agent`（构造、`subscribe`、`prompt`、`continue`、`abort`、`waitForIdle`、`reset`、`steer`/`followUp`、`_run_with_lifecycle`、`_process_events`、`_handle_run_failure`）、`PendingMessageQueue`
- 关键点：`AbortController` → 自建 `AbortSignal`；`activeRun.promise` → `asyncio.Future`；`processEvents` 里必须先归约 state 再 await 监听器（否则 UI 读到旧状态）
- 验收：两个订阅者，断言收到的事件序列、`state.isStreaming` 的变化、`abort()` 后 `stopReason == "aborted"`

### 第 8 课 · 模型注册表 + faux provider（离线跑通！）
- 对应：`models.ts`（`createModels`/`createProvider`/`calculateCost`/`clampThinkingLevel`）、`providers/faux.ts`（732）
- 产物：`pi_py/models.py`、`pi_py/providers/faux.py`、`examples/01_end_to_end_faux.py`
- 关键点：faux provider 就是「按脚本吐事件」，用它把 M3 打通；此时整条链路不需要任何 API key
- 验收：一条命令跑出完整对话，包含一次工具调用

### 第 9 课 · OpenAI 兼容适配器
- 对应：`api/openai-completions.ts`（1728）、`utils/streaming-json.ts`（559）
- 产物：`pi_py/api/openai_completions.py`、`pi_py/streaming_json.py`
- 要翻译：`streamSimple` → `stream` → `convertMessages` → 请求体构造 → SSE 解析 → 事件翻译；`ToolCallArgumentsStream` 增量 JSON
- 关键点：SSE 用 `httpx` 的 `aiter_lines()`；`partial` 必须**原地更新同一个对象**再 push，否则 UI 拿不到增量；DeepSeek/Kimi/通义/本地 llama.cpp 都走这条路径
- 验收：真实模型跑通一次带工具调用的对话

### 第 10 课 · 工具层
- 对应：`coding-agent/src/core/tools/*`
- 产物：`pi_py/tools/{read,write,edit,bash,grep,glob}.py` + 工具注册表
- 关键点：工具 = `AgentTool`（name/description/parameters/execute/label），`execute` 返回 `AgentToolResult{content, details, isError}`；用 pydantic 模型生成 `parameters` 的 JSON Schema，避免手写
- 验收：让模型读一个文件、改一行、再跑一次测试

### 第 11 课 · 会话与上下文管理
- 对应：`coding-agent/src/core/agent-session.ts`（4.5k，**只挑主线**）、`core/compaction/compaction.ts`
- 产物：`pi_py/session.py`（JSONL 追加、分支、恢复）、`pi_py/compaction.py`（超限时摘要）
- 关键点：会话是「树」不是「线性历史」；`parentId` 决定当前分支；压缩只是插入一条 summary 消息，原始记录不删
- 验收：跑一轮 → 落盘 → 进程重启 → 续聊，模型能看到历史

### 第 12 课 · CLI 入口
- 对应：`coding-agent/src/main.ts`、`modes/print`
- 产物：`pi_py/cli.py`（`print` 模式 + `json` 模式）
- 关键点：print 模式只输出最终文本；json 模式把 Agent 事件逐行写成 JSONL（`AgentEvent` 已是 dict，直接 `json.dumps`）
- 验收：`python -m pi_py "读一下 pyproject.toml"` 输出答案

---

## 偏差登记表（有意不同，必须记录）

移植不是逐字符抄写，下面这些是**已知的、有理由的偏离**，新增偏离请追加：

| # | 位置 | JS | Python | 理由 |
|---|---|---|---|---|
| D1 | `types.copy_message` | `{...msg}` 连 content 列表都共享 | 额外复制一层 content 列表 | 隔离监听器副作用，成本可忽略 |
| D2 | `types.empty_usage` | 共享 `EMPTY_USAGE` 常量 | 每次新建 | Python 无可信不可变对象 |
| D3 | `event_stream` | 构造时创建最终结果 Promise | 懒创建 Future | 构造时可能无运行中的事件循环 |
| D4 | 事件字段命名 | camelCase | 保持 camelCase（例外） | 事件直接参与 JSON 序列化 |
| D5 | `types.Tool.parameters` | typebox `TSchema` | 普通 JSON Schema dict | typebox 无 Python 等价物 |
| D6 | `AssistantMessageEventStream._time` | `Math.round` | `floor(x+0.5)` | Python `round()` 是银行家舍入 |

---

## 每课的工作流（照做就不会乱）

1. **读 JS 原文**：用 `docs/01-call-chain.md` 找到行号，通读整个函数（不要看片段）。
2. **先写测试的输入与期望**：从 JS 的 `.test.ts` 里抄用例（`packages/*/test/`）。
3. **逐函数翻译**：一次一个函数，翻完立刻跑测试。
4. **记录偏差**：任何非语法级改动，写进上面的登记表。
5. **回读**：翻完一课，把该文件从头读一遍，确认「陌生人能读懂」。

## 需要同步翻译的测试（重要）

JS 侧的测试是免费的正确性来源，别浪费：

| Python 模块 | 对应的 JS 测试（已确认存在） |
|---|---|
| `event_stream.py` | `packages/ai/test/event-stream.test.ts` |
| `transcript.py` | `packages/ai/test/transcript-tool-changes.test.ts` |
| `validation.py` | `packages/ai/test/validation.test.ts` |
| `transform_messages.py` | `packages/ai/test/transform-messages-*.test.ts` |
| `estimate.py` | `packages/ai/test/context-estimate.test.ts` |
| `agent_loop.py` | `packages/agent/test/agent-loop.test.ts` |
| `agent.py` | `packages/agent/test/agent.test.ts` |
| `openai_completions.py` | `packages/ai/test/openai-completions-*.test.ts` |

先 `ls packages/ai/test` 看一眼有哪些，再决定抄哪些用例。
