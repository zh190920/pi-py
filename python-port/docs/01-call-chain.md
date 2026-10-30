# 01 · 逐函数调用链对照表

这张表是「一个函数一个函数翻译」的施工图。左列是 JS 的 `文件:行 → 函数`，右列是 Python 目标位置，最后一列是它在第几课出现。表中 50 个函数（A/B/C/D 四段）走完，就得到一条能真正跑通的 `prompt → 回复` 链路；E 段是产品层可选项。

图例：`⟶` 表示调用关系。

## A. 入口层（`packages/agent/src/agent.ts`）

| # | JS | 作用 | Python 目标 | 课 |
|---|---|---|---|---|
| A1 | `agent.ts:382` `prompt(input, images?)` | 对外唯一入口，重载 3 种入参 | `Agent.prompt()` | 07 |
| A2 | `agent.ts:422` `normalizePromptInput()` | 字符串 → `UserMessage{content:[text]} + images` | `Agent._normalize_prompt_input()` | 07 |
| A3 | `agent.ts:441` `runPromptMessages()` | 包一层生命周期后调用 `runAgentLoop` | `Agent._run_prompt_messages()` | 07 |
| A4 | `agent.ts:517` `runWithLifecycle()` | 建 `AbortController`、`activeRun`、置 `isStreaming` | `Agent._run_with_lifecycle()` | 07 |
| A5 | `agent.ts:469` `createContextSnapshot()` | 拷一份 `{messages, tools}` 给本轮回调 | `Agent._create_context_snapshot()` | 07 |
| A6 | `agent.ts:476` `createLoopConfig()` | 把 Agent 字段 + 队列 drain 闭包装成 `AgentLoopConfig` | `Agent._create_loop_config()` | 07 |
| A7 | `agent.ts:575` `processEvents(event)` | 归约 state，再按订阅顺序 await 监听器 | `Agent._process_events()` | 07 |
| A8 | `agent.ts:542` `handleRunFailure()` | 异常 → 伪造 error assistant 消息并走完事件 | `Agent._handle_run_failure()` | 07 |
| A9 | `agent.ts:149` `PendingMessageQueue` | steering/follow-up 队列，`all` / `one-at-a-time` | `PendingMessageQueue` | 07 |

## B. 循环层（`packages/agent/src/agent-loop.ts`）

| # | JS | 作用 | Python 目标 | 课 |
|---|---|---|---|---|
| B1 | `agent-loop.ts:47` `agentLoop()` | 建 `EventStream`，后台跑 `runAgentLoop`，用 `.then` 结束流 | `agent_loop()` | 06 |
| B2 | `agent-loop.ts:111` `runAgentLoop()` | 追加 prompt → `declareToolChanges` → 发 start 事件 → `runLoop` | `run_agent_loop()` | 06 |
| B3 | `agent-loop.ts:172` `runLoop()` | **双层循环本体**：内层跑 turn，外层等 follow-up | `run_loop()` | 06 |
| B4 | `agent-loop.ts:342` `declareToolChanges()` | 把工具集合差异写成 system 消息 | `declare_tool_changes()` | 05 |
| B5 | `agent-loop.ts:377` `withToolChanges()` | 复制 system 消息并替换工具字段（空列表省略字段） | `with_tool_changes()` | 05 |
| B6 | `agent-loop.ts:390` `streamAssistantResponse()` | transform → convert → normalize → 取 key → 消费流 → 发事件 | `stream_assistant_response()` | 06 |
| B7 | `agent-loop.ts:518` `executeToolCalls()` | 判断走串行还是并行 | `execute_tool_calls()` | 06 |
| B8 | `agent-loop.ts:540` `executeToolCallsSequential()` | 逐个「准备 → 执行 → 收尾 → 发事件」 | `execute_tool_calls_sequential()` | 06 |
| B9 | `agent-loop.ts:596` `executeToolCallsParallel()` | 先串行准备，再 `Promise.all` 并发执行，按源顺序产出结果消息 | `execute_tool_calls_parallel()` | 06 |
| B10 | `agent-loop.ts:718` `prepareToolCall()` | 找工具 → `prepareArguments` → `validateToolArguments` → `beforeToolCall` | `prepare_tool_call()` | 06 |
| B11 | `agent-loop.ts:831` `executePreparedToolCall()` | 计时执行 `tool.execute`，收集 update 回调 | `execute_prepared_tool_call()` | 06 |
| B12 | `agent-loop.ts:869` `finalizeExecutedToolCall()` | 应用 `afterToolCall` 字段级覆盖 | `finalize_executed_tool_call()` | 06 |
| B13 | `agent-loop.ts:700` `shouldTerminateToolBatch()` | 全部结果都 `terminate:true` 才提前结束 | `should_terminate_tool_batch()` | 06 |
| B14 | `agent-loop.ts:940` `createToolResultMessage()` | 工具结果 → `toolResult` 消息 | `create_tool_result_message()` | 06 |
| B15 | `agent-loop.ts:488` `failToolCallsFromTruncatedMessage()` | `stopReason:"length"` 时全部工具调用判失败 | `fail_tool_calls_from_truncated_message()` | 06 |

## C. 基础设施层（`packages/ai/src/utils/`）

| # | JS | 作用 | Python 目标 | 课 |
|---|---|---|---|---|
| C1 | `types.ts` 全文 | 消息/内容块/Usage/Model/Tool | `pi_py/types.py` | 01 |
| C2 | `event-stream.ts:3` `FifoQueue` | 双栈队列 | `FifoQueue` | 02 |
| C3 | `event-stream.ts:43` `EventStream.push` | 完成判定 + 唤醒等待者/入队 | `EventStream.push()` | 02 |
| C4 | `event-stream.ts:72` `[Symbol.asyncIterator]` | 异步迭代 | `EventStream.__aiter__` | 02 |
| C5 | `event-stream.ts:97` `AssistantMessageEventStream` | 额外给最终消息打 `durationMs` | `AssistantMessageEventStream` | 02 |
| C6 | `text.ts:4` `contentText` | 块数组 → 纯文本 | `content_text()` | 01 |
| C7 | `text.ts:14` `getSystemMessageText` | content + sections 拼 prompt | `get_system_message_text()` | 01 |
| C8 | `transcript.ts:10` `createInitialSystemMessage` | 组装首条 system 消息 | `create_initial_system_message()` | 03 |
| C9 | `transcript.ts:30` `normalizeContext` | `Context` → `TranscriptContext` | `normalize_context()` | 03 |
| C10 | `transcript.ts:58` `getCurrentTools` | 回放所有 `toolsAdded/Removed` 得当前工具表 | `get_current_tools()` | 03 |
| C11 | `transcript.ts:73` `getCurrentSystemMessage` | 回放 content + sections + tools | `get_current_system_message()` | 03 |
| C12 | `transcript.ts:123` `toToolDeclaration` | 剥掉可执行字段，只留声明 | `to_tool_declaration()` | 03 |
| C13 | `transcript.ts:150` `getToolStateChanges` | 两份工具表求差集 | `get_tool_state_changes()` | 03 |
| C14 | `validation.ts:317` `validateToolArguments` | 归一化 null → 强制转换 → 校验 → 报错文本 | `validate_tool_arguments()` | 04 |
| C15 | `validation.ts:194` `coerceWithJsonSchema` | `"5"`→`5`、`1`→`true` 等 | `coerce_with_json_schema()` | 04 |
| C16 | `estimate.ts:47` `estimateTextTokens` | 字符数 / 3.5 | `estimate_text_tokens()` | 04 |

## D. Provider 层（`packages/ai/src/`）

| # | JS | 作用 | Python 目标 | 课 |
|---|---|---|---|---|
| D1 | `models.ts:1028` `createModels()` | provider 注册表 + 模型查询 | `Models` | 08 |
| D2 | `models.ts` `streamSimple()` | 按 `model.api` 派发到具体适配器 | `Models.stream_simple()` | 08 |
| D3 | `api/simple-options.ts:36` `buildBaseOptions()` | 把 `SimpleStreamOptions` 归一成 `StreamOptions` | `build_base_options()` | 05 |
| D4 | `api/simple-options.ts:18` `clampMaxTokensToContext()` | `maxTokens` 不超过上下文剩余空间 | `clamp_max_tokens_to_context()` | 05 |
| D5 | `api/simple-options.ts:93` `adjustMaxTokensForThinking()` | 思考预算与回答预算分配 | `adjust_max_tokens_for_thinking()` | 05 |
| D6 | `api/transform-messages.ts:91` `transformMessages()` | 跨模型重放清洗：丢别家 thinking、补孤儿 toolResult | `transform_messages()` | 05 |
| D7 | `api/openai-completions.ts:310` `stream()` | 构造请求体、发 HTTP、解析 SSE、push 事件 | `openai_completions_stream()` | 09 |
| D8 | `api/openai-completions.ts:718` `streamSimple()` | 归一 options 后调 `stream` | `openai_completions_stream_simple()` | 09 |
| D9 | `utils/streaming-json.ts` `ToolCallArgumentsStream` | 增量 JSON 参数解析 | `ToolCallArgumentsStream` | 09 |
| D10 | `providers/faux.ts` | 假 provider，零网络，可脚本化回复 | `FauxProvider` | 08 |

## E. 应用层（第 11–12 课，按需）

| # | JS | 作用 | 课 |
|---|---|---|---|
| E1 | `coding-agent/src/core/agent-session.ts` (4.5k) | 会话：分支、压缩、模型切换 | 11 |
| E2 | `coding-agent/src/core/tools/*` | read/write/edit/bash/grep 等内置工具 | 10 |
| E3 | `coding-agent/src/core/system-prompt.ts` | 系统提示词组装 | 11 |
| E4 | `coding-agent/src/main.ts` | CLI 入口、模式选择 | 12 |

## 三条贯穿全程的翻译规则

1. **函数名**: `camelCase` → `snake_case`，语义不变，不合并、不拆分。
2. **参数顺序**: 原样保留；JS 的可选参数 → Python 关键字参数（默认 `None`）。
3. **返回值**: JS 里「返回 `undefined` 表示不修改」的钩子，Python 统一返回 `None`；「返回 `void` 的异步钩子」用 `await` 直接调用。

## 状态机速查：一次 prompt 会发哪些事件

```
agent_start
  turn_start
    message_start(user)      → message_end(user)
    message_start(assistant) → message_update × N → message_end(assistant)
    [每个工具调用]
      tool_execution_start
      tool_execution_update × N
      tool_execution_end
      message_start(toolResult) → message_end(toolResult)
  turn_end
  ┌ 还有工具调用/排队消息 → 再来一个 turn_start … turn_end
  └ 否则
agent_end(messages)
```

记住这个序列，第 6 课的循环就是「按顺序把这些事件吐出来」。
