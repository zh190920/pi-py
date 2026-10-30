# 00 · 这份 JS 代码库到底长什么样

在写第一行 Python 之前，先把整体结构钉死。否则你会在 240k 行里迷路。

## 1. 它是什么

Pi 是一个「agent harness」（智能体外壳）：把 **LLM 请求**、**工具执行**、**上下文组装**、**会话存储** 四件事粘在一起，并提供多种入口（终端交互、打印模式、JSON 模式、RPC、SDK）。

一句最直白的话：

> 用户输入一句话 → 组装成模型能懂的请求 → 拿到流式回复 → 如果回复里有工具调用就去执行 → 把执行结果塞回上下文 → 再请求一次 → …… → 直到模型不再要工具为止。

这个循环就是全部的核心。剩下的 90% 代码是：各种 provider 的协议适配、终端 UI、会话持久化、扩展系统。

## 2. monorepo 布局与体量

| 包 | 职责 | src 行数 | Python 移植优先级 |
|---|---|---|---|
| `packages/ai` | 统一多 provider LLM API（消息类型、流式协议、工具 schema 校验、模型目录） | 28,565 | **P0 必做** |
| `packages/agent` | Agent 运行时：循环、工具执行、事件、状态 | 2,541 | **P0 必做** |
| `packages/telemetry` | 遥测契约（无厂商依赖） | 1,572 | P3 可选 |
| `packages/env` | 环境/凭据解析 | 2,390 | P3 可选 |
| `packages/mcp` | MCP 协议客户端 | 3,287 | P2 |
| `packages/codemode` | 用脚本批量调度工具调用 | 3,037 | P3 |
| `packages/tui` | 终端 UI（差分渲染） | 19,882 | P4 不建议 |
| `packages/coding-agent` | 真正的 CLI 产品：会话、扩展、压缩、模式、内置工具 | 77,022 | P2 分模块 |
| `packages/chord` | 可热重载插件宿主 + 复制状态 + RPC | 43,566 | P4 不建议 |
| `packages/durable` | 持久化会话/任务运行时 | 33,317 | P4 不建议 |
| `packages/evals` | 评测脚手架 | 1,447 | P4 |

**结论**：所谓「完全转 Python」的可行内核是 **`ai` + `agent`，合计约 31k 行**，其中 `ai` 里约 300 行是生成文件（`models.generated.ts`）、约 900 行是模型目录数据（`providers/*.models.ts`，可脚本生成，不用手抄）。真正需要「一个函数一个函数翻译」的是 **≈ 8k 行核心 + 每个 provider 一个适配器（0.5k~1.7k 行）**。

## 3. 依赖方向（谁可以 import 谁）

```
                        ┌──────────────┐
                        │  telemetry   │  (契约，无向外依赖)
                        └──────┬───────┘
                               │
        ┌──────────────────────┴───────────┐
        │                                  │
   ┌────▼─────┐                      ┌─────▼──────┐
   │    ai    │  ← 最底层，纯库       │    env     │
   └────┬─────┘                      └─────┬──────┘
        │                                  │
   ┌────▼─────┐                            │
   │  agent   │  只依赖 ai + typebox        │
   └────┬─────┘                            │
        │                                  │
   ┌────▼──────────────────────────────────▼────┐
   │              coding-agent                   │ ← 产品层，什么都依赖
   │  (+ tui / mcp / codemode / chord / durable) │
   └─────────────────────────────────────────────┘
```

这个单向依赖是移植的关键：**先 `ai`，再 `agent`，最后才是产品层**。反过来做必然返工。

## 4. 核心四层（要翻译的 8k 行）

### 第 1 层：消息与内容（`packages/ai/src/types.ts`，916 行）

全部数据结构都在这里，是整个系统的「词汇表」：

- 内容块：`TextContent | ThinkingContent | ImageContent | ToolCall`
- 消息：`SystemMessage | UserMessage | AssistantMessage | ToolResultMessage`
- 计量：`Usage`（input/output/cacheRead/cacheWrite/totalTokens/cost）
- 模型：`Model`（api、provider、contextWindow、maxTokens、thinkingLevelMap…）
- 工具声明：`Tool`（name/description/parameters，parameters 是 JSON Schema）
- 事件：`AssistantMessageEvent`（start/text_delta/toolcall_delta/done/error…）

**这一层没有逻辑，只有形状。** 但它决定了后面所有代码的写法。第 1 课就翻译它。

### 第 2 层：基础设施（`packages/ai/src/utils/`）

| 文件 | 作用 | 为什么必须有 |
|---|---|---|
| `event-stream.ts` (135) | `EventStream<T,R>` 异步队列 + `AssistantMessageEventStream` | 整个系统靠「边生成边消费」运转，这是心脏 |
| `transcript.ts` (263) | system 消息回放、工具声明 diff、`normalizeContext` | 决定「模型这次看到什么 prompt / 什么工具」 |
| `text.ts` | `contentText` / `getSystemMessageText` | 把块数组还原成字符串 |
| `validation.ts` (353) | 工具参数 JSON Schema 校验 + 类型强制转换 | 模型给的参数经常是 `"5"` 而不是 `5` |
| `streaming-json.ts` (559) | 流式 JSON 参数增量解析 | 工具调用参数是一个字符一个字符吐出来的 |
| `estimate.ts` (117) | token 估算 | 决定一次请求还能塞多少 |
| `retry.ts` (275) | 重试与退避 | provider 限流 |

### 第 3 层：Agent 循环（`packages/agent/src/`）

| 文件 | 行数 | 作用 |
|---|---|---|
| `types.ts` | 539 | AgentMessage / AgentTool / AgentEvent / AgentLoopConfig / 各钩子 |
| `agent-loop.ts` | 959 | **纯函数式循环**：`runAgentLoop` → `runLoop` → 流式响应 → 执行工具 → 再循环 |
| `agent.ts` | 623 | **有状态外壳**：持有 transcript、事件订阅、steering/follow-up 队列、abort |
| `stream-fn.ts` | 20 | 可替换的「默认 stream 函数」 |
| `proxy.ts` | 395 | 把 LLM 调用转发到自家服务器的变体 |

这是整个项目最值得读的 1.5k 行。**循环本身不碰网络、不碰 UI**，只做调度：它把「怎么请求模型」抽象成 `StreamFn` 参数，把「发事件」抽象成 `emit` 参数。

### 第 4 层：provider 适配器（`packages/ai/src/api/*.ts`）

每个文件把统一消息格式翻译成某家 API 的形状，再把对方的流式响应翻译回统一的 `AssistantMessageEvent`：

| 适配器 | 行数 | 协议 |
|---|---|---|
| `openai-completions.ts` | 1,728 | OpenAI Chat Completions（SSE） |
| `anthropic-messages.ts` | 1,687 | Anthropic Messages API（SSE） |
| `bedrock-converse-stream.ts` | 1,461 | AWS Bedrock Converse（SigV4 + SSE） |
| `mistral-conversations.ts` | 924 | Mistral |
| `openai-responses.ts` | 453 | OpenAI Responses API |
| `google-generative-ai.ts` | 466 | Gemini |
| `pi-messages.ts` | 465 | 自家 RPC 协议 |
| `providers/faux.ts` | 732 | **假 provider，专供测试，零网络** |

移植顺序建议：先 `faux`（离线可测），再 `openai-completions`（协议最简单、兼容面最广，DeepSeek/通义/Kimi/本地 llama.cpp 都能用），最后再考虑 Anthropic / Gemini。

## 5. 输入到输出的完整链路（10 步）

```
① 用户输入 "帮我看看 package.json"
      │
② Agent.prompt(input)                         agent.ts:382
      │  normalizePromptInput → UserMessage{role:"user", content:[{type:"text"}]}
③ runWithLifecycle                            agent.ts:517
      │  建 AbortController、activeRun promise、isStreaming=true
④ runAgentLoop(prompts, context, config, emit, signal, streamFn)   agent-loop.ts:111
      │  declareToolChanges()：把「工具集合变化」写进 system 消息
      │  emit agent_start / turn_start / message_start / message_end
⑤ runLoop(...)                                agent-loop.ts:172
      │  ┌─────────────────────────────────────────────┐
      │  │ 内层循环：还有工具调用 或 还有排队消息        │
      │  │                                              │
      │  │  prepareRequest() 可选钩子                    │
      │  │        ↓                                     │
      │  │  streamAssistantResponse()  agent-loop.ts:390│
      │  │    transformContext()  → 裁剪旧消息           │
      │  │    convertToLlm()      → 过滤 UI 专用消息     │
      │  │    normalizeContext()  → 折叠成 TranscriptCtx │
      │  │    getApiKey()         → 动态取 key           │
      │  │    streamFn(model, ctx, opts)                 │
      │  │        ↓                                     │
      │  │  ┌── provider 适配器 ──────────────────────┐  │
      │  │  │ streamSimple() → buildBaseOptions()     │  │
      │  │  │   → transformMessages() 归一化历史      │  │
      │  │  │   → 构造请求体 → HTTP/SSE               │  │
      │  │  │   → 逐事件 push 进 AssistantMessageEventStream │
      │  │  └─────────────────────────────────────────┘  │
      │  │        ↓                                     │
      │  │  边消费边 emit message_update                 │
      │  │  收到 done/error → 得到完整 AssistantMessage   │
      │  │        ↓                                     │
      │  │  stopReason == "error"/"aborted" ? 直接结束   │
      │  │        ↓                                     │
      │  │  executeToolCalls()  agent-loop.ts:518        │
      │  │    prepareToolCall()：找工具 / 校验参数 / beforeToolCall
      │  │    executePreparedToolCall()：tool.execute()  │
      │  │    finalizeExecutedToolCall()：afterToolCall  │
      │  │    → ToolResultMessage 追加进上下文            │
      │  │        ↓                                     │
      │  │  finishTurn() → turn_end                      │
      │  │  getSteeringMessages() → 有就继续             │
      │  └─────────────────────────────────────────────┘
      │  外层：getFollowUpMessages() → 有就继续，否则退出
⑥ emit agent_end
⑦ Agent.processEvents() 更新 state、通知订阅者
⑧ finishRun()：isStreaming=false、resolve activeRun
⑨ 调用方 await agent.waitForIdle() 返回
⑩ 输出：Agent.state.messages 里新增的 assistant / toolResult 消息
```

## 6. 五个必须记住的约定

1. **一切皆消息**。工具结果也是消息（`role:"toolResult"`），不是回调返回值。上下文就是 `AgentMessage[]`，追加即可。
2. **system 消息是「账本」**。prompt 和工具声明不是独立字段，而是写在 system 消息里；后来的 system 消息通过 `content` / `sections` / `toolsAdded` / `toolsRemoved` 做增量修改，**按顺序回放**得到当前状态。
3. **流式协议是单向的 6 种事件**：`start` → (`text_*` | `thinking_*` | `toolcall_*`) → `done` | `error`。`partial` 是同一个对象的实时引用，不是快照。
4. **失败不抛异常，编码进消息**。请求失败要产出一个 `stopReason:"error"` 的 assistant 消息，而不是 throw。
5. **循环与 IO 解耦**。`runLoop` 只依赖 `emit` 和 `streamFn` 两个注入的函数，因此可以脱离网络和 UI 单测。

## 7. 不建议移植的部分（先划掉）

| 部分 | 原因 |
|---|---|
| `packages/tui` | 2 万行终端差分渲染，Python 生态应换 Textual/Rich，逐行翻译没有收益 |
| `packages/chord` | 4.3 万行热重载/复制状态，属于另一个产品方向 |
| `packages/durable` | 3.3 万行 Cloudflare Workers 持久化运行时，平台强绑定 |
| `coding-agent/extensions/*` | 依赖 jiti / quickjs-wasi 动态加载 TS，Python 应改为 importlib 插件 |
| OAuth 全家桶（`auth/oauth/*`） | 十几套登录流程，按需翻译即可 |
| `models.generated.ts` | 生成产物，Python 侧应改成「从 JSON 目录加载」 |

## 8. 移植时最容易踩的 6 个坑

1. **`undefined` ≠ `null`**。JS 里 `hasTools = tools !== undefined` 和 `value === null` 语义不同；Python 只有 `None`，必须靠「字段缺省 = 不参与比较」来复刻。
2. **对象是引用，spread 是浅拷贝**。`context.messages[last] = partialMessage` 这种原地替换，Python 用 `list[i] = x` 即可；`{...msg}` 用 `dataclasses.replace` + 复制 content 列表。
3. **异步迭代器**。`for await (const e of stream)` → `async for e in stream`，但队列/唤醒机制要自己用 `asyncio.Future` 实现。
4. **AbortSignal**。Python 没有内建等价物，需要一个自己的 `AbortSignal`（`asyncio.Event` + 回调列表），并在每个 await 边界检查。
5. **JSON Schema 校验**。`typebox` 在 Python 侧对应 `jsonschema` + 手写强制转换（见 `validation.ts`，那 353 行里一半是 coercion）。
6. **命名风格**。建议：**Python 内部用 snake_case，序列化到 provider 时再转回 camelCase**；一次性在边界处转换，不要两边混用。

---

下一步：读 [01-call-chain.md](01-call-chain.md) 拿到逐函数对照表，然后从 [第 1 课](../lessons/01-message-types.md) 开始动手。
