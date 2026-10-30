# 第 1 课 · 消息与内容块类型层

**学完你会得到**：`pi_py/types.py`（可直接 `import`），以及一套贯穿全程的命名/拷贝规则。
**对应 JS**：`packages/ai/src/types.ts`（第 416–803 行：内容块、消息、工具声明）+ `packages/ai/src/utils/text.ts`
**代码**：[`pi_py/types.py`](../pi_py/types.py) · **自测**：[`tests/test_lesson01.py`](../tests/test_lesson01.py)

---

## 0. 先建立直觉：这一层是什么

后面所有函数都在搬运这 4 种东西：

```
Message
├── SystemMessage    { role:"system",     content, sections?, toolsAdded?, toolsRemoved? }
├── UserMessage      { role:"user",       content: string | (Text|Image)[] }
├── AssistantMessage { role:"assistant",  content: (Text|Thinking|ToolCall)[], usage, stopReason, ... }
└── ToolResultMessage{ role:"toolResult", toolCallId, toolName, content, isError }
```

这里的每一个字段都会被后面的循环读写，所以**字段名一个都不能改**（除了 camelCase → snake_case）。改错一个字段名，第 6 课调试时你会怀疑人生。

---

## 1. 四条翻译规则（全课程通用）

| # | JS | Python | 说明 |
|---|---|---|---|
| R1 | `interface X { a: string }` | `@dataclass class X: a: str` | JS 对象是可变引用，dataclass 实例也是 |
| R2 | `A \| B \| C` | `Union[A, B, C]` | 联合类型没有运行时意义，只是注解 |
| R3 | `cacheRead` | `cache_read` | 内部统一 snake_case，出网时再转回 |
| R4 | `undefined` / `null` | `None` | **这是最大的坑，见 §5** |

---

## 2. 类型逐个翻译

### 2.1 内容块：`TextContent`

JS（`types.ts:422`）：

```ts
export interface TextContent {
	type: "text";
	text: string;
	textSignature?: string;
}
```

Python（`types.py`）：

```python
@dataclass
class TextContent:
    text: str
    text_signature: Optional[str] = None
    type: str = field(default="text", init=False)
```

三处刻意的差异：

1. **判别字段放最后、`init=False`**。JS 里 `type` 是个普通属性，谁都能写成 `"image"`；Python 这样写之后，`TextContent(...)` 不可能构造出错误的 `type`。用属性读取时行为完全一致（`block.type == "text"`）。
2. **可选字段 `?` → `Optional[...] = None`**，必须给默认值，否则参数顺序会错。
3. 构造时`TextContent("hi")` 即可，对应 JS `{ type:"text", text:"hi" }`。

`ThinkingContent` / `ImageContent` / `ToolCall` 同理：

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]          # JS: JsonObject
    thought_signature: Optional[str] = None
    namespace: Optional[str] = None
    arguments_error: Optional[str] = None
    type: str = field(default="toolCall", init=False)
```

> `arguments_error` 的语义要记住：模型吐出的参数不是合法 JSON 时，`arguments` 置 `{}`，错误写在这里，**由第 4 课的校验层报错**，而不是在解析时抛异常。

### 2.2 计量：`Usage` / `Cost`

JS（`types.ts:459`）的 `cost` 是嵌套对象。Python 侧拆成一个独立的 dataclass，并用 `default_factory`：

```python
@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: Cost = field(default_factory=Cost)   # ← 不能写 = Cost()！
    cache_write_1h: Optional[int] = None
    reasoning: Optional[int] = None
```

**坑**：`field(default_factory=Cost)` 是必须的。写成 `cost: Cost = Cost()` 会让**所有实例共享同一个 Cost 对象**，一处改金额全部污染——这是 Python dataclass 最经典的错误。

配套函数：

```python
def calculate_context_tokens(usage) -> int:
    return usage.total_tokens or (usage.input + usage.output + usage.cache_read + usage.cache_write)
```

对应 `utils/estimate.ts` 的 `calculateContextTokens`。注意 `or` 复刻了 JS 的 `||`：`total_tokens == 0` 时回退到求和。

### 2.3 消息

```python
@dataclass
class SystemMessage:
    content: Union[str, List[TextContent]]
    timestamp: int
    sections: Optional[Dict[str, Optional[str]]] = None
    tools_added: Optional[List[Tool]] = None
    tools_removed: Optional[List[ToolReference]] = None
    role: str = field(default="system", init=False)
```

`sections: Dict[str, Optional[str]]` 里的 `None` 表示「删除这个 section」，对应 JS 的 `Record<string, string | null>`。**这里正是 R4 的反例**：JS 用 `null` 表意，不是「未设置」，所以 Python 侧用 `None` 表达「删除」，用「键不存在」表达「未设置」。

`AssistantMessage` 是最胖的一个，逐个字段对过去：

| JS | Python | 备注 |
|---|---|---|
| `content` | `content` | `(Text|Thinking|ToolCall)[]` |
| `api` / `provider` / `model` | 同名 snake | 跨模型重放时要用它们判断「是不是同一个模型」（第 5 课） |
| `usage` | `usage` | |
| `stopReason` | `stop_reason` | 用 `StopReason` 常量类 |
| `timestamp` | `timestamp` | 毫秒 |
| `durationMs?` | `duration_ms` | 由第 2 课的事件流写入 |
| `errorMessage?` | `error_message` | `stop_reason in ("error","aborted")` 时必填 |

`stopReason` 在 TS 里是字符串字面量联合，Python 用常量类承载：

```python
class StopReason:
    PENDING = "pending"; STOP = "stop"; LENGTH = "length"
    TOOL_USE = "toolUse"; ERROR = "error"; ABORTED = "aborted"; DEFERRED = "deferred"
```

> 为什么不用 `enum.Enum`？因为后面要直接把这些字符串塞进 JSON 和 provider 请求体，`str` 常量最省事，且和 JS 的值一模一样（`"toolUse"` 这种大小写也别改）。

### 2.4 工具声明

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]      # JSON Schema
    constrained_sampling: Optional[Any] = None
```

JS 侧 `parameters` 的类型是 typebox 的 `TSchema`（带 symbol 元数据的对象）。Python 侧退化成普通 JSON Schema dict——**这是整个移植里唯一一处「类型降级」**，代价是 `validation.ts` 里那些依赖 typebox 内部结构的判断要重写（第 4 课处理）。

### 2.5 模型

只保留循环真正用到的字段（`id/name/api/provider/base_url/reasoning/input/cost/context_window/max_tokens` + thinking 相关）。`DEFAULT_MODEL` 常量改成工厂函数：

```python
def unknown_model() -> Model:
    return Model(id="unknown", name="unknown", api="unknown", provider="unknown")
```

原因和 `Cost` 一样：JS 的常量对象可能被共享，Python 里别共享可变对象。

### 2.6 文本工具：`contentText`

JS（`utils/text.ts:4`）：

```ts
export function contentText(content: string | readonly Content[], separator = "\n"): string {
	if (typeof content === "string") return content;
	return content.filter((block) => block.type === "text").map((block) => block.text).join(separator);
}
```

Python：

```python
def content_text(content, separator="\n") -> str:
    if isinstance(content, str):
        return content
    return separator.join(block.text for block in content if isinstance(block, TextContent))
```

两点：

- `content.filter(b => b.type === "text")` → `isinstance(block, TextContent)`。**用类型判断而不是 `block.type == "text"`**，因为前者还能让类型检查器收窄类型。
- `Array.join` 和 `str.join` 语义一致（空数组都是 `""`）。

### 2.7 文本工具：`getSystemMessageText`

JS（`utils/text.ts:14`）：

```ts
export function getSystemMessageText(message: SystemMessage): string {
	const parts = [contentText(message.content)];
	for (const text of Object.values(message.sections ?? {})) {
		if (text !== null) parts.push(text);
	}
	return parts.filter((part) => part.length > 0).join("\n\n");
}
```

Python：

```python
def get_system_message_text(message: SystemMessage) -> str:
    parts = [content_text(message.content)]
    for value in (message.sections or {}).values():
        if value is not None:          # 对应 text !== null
            parts.append(value)
    return "\n\n".join(part for part in parts if len(part) > 0)
```

`message.sections ?? {}` → `message.sections or {}`。
`text !== null` → `value is not None`（**不要写 `if value:`**，空串在 JS 里是通过的，只是后面被 length 过滤）。

---

## 3. 浅拷贝：`{ ...msg }` → `copy_message()`

JS 循环里到处是 `message: { ...partialMessage }`，目的是给监听器一个**不会随后续更新而变**的顶层对象。Python 对应写法：

```python
def copy_message(message):
    clone = replace(message)                       # 复制所有字段（浅）
    if isinstance(getattr(clone, "content", None), list):
        clone.content = list(clone.content)        # content 数组也复制一层
    return clone
```

为什么要把 `content` 再复制一层：`dataclasses.replace` 只复制字段引用，`clone.content` 和 `original.content` 还是同一个 list；而 JS 的 `[...]` 数组在 spread 里传递时也是同一个引用——**这里其实 JS 也是共享的**。

严格说 JS 的 `{...msg}` 连 content 列表都共享。那为什么这里要复制？

因为后面 `streamAssistantResponse` 里出现了两种操作：
- `context.messages[last] = partialMessage`（替换，不复制）
- `emit({ message: { ...partialMessage } })`（复制顶层，给监听器）

监听器如果去 `message.content.push(...)` 会污染上下文。JS 侧约定监听器不改，Python 侧**顺手把 content 也复制一层**，成本极低（列表长度通常个位数），换来更强的隔离。这是一处**有意偏离**，写在这里备案。

测试 `test_copy_message_is_shallow_like_spread` 同时断言了两件事：列表不共享、元素共享。

---

## 4. `Message` 联合与 `role`

```python
Message = Union[SystemMessage, UserMessage, AssistantMessage, ToolResultMessage]
```

JS 里 `message.role === "assistant"` 到处出现。Python 有两种写法：

```python
if message.role == "assistant":        # 所有消息都有 role 字段，简单
if isinstance(message, AssistantMessage):  # 能收窄类型，推荐
```

提供 `message_role(message)` 是为了兼容「自定义消息」（`AgentMessage` 就是 `Message | 自定义类型`，第 7 课会用到，可能是 dict）。

---

## 5. 本课最大的坑：`undefined` vs `null` vs `None`

JS 里两者不同：

```ts
type X = { a?: string | null };
// a 有三种状态：不存在(undefined) / null / "值"
```

Python 只有 `None`，一种值承担两种语义。三条应对规则：

1. **「未设置」用「字段默认 None」表示**，判断用 `is None`。
2. **「显式删除」用业务约定表示**，比如 `sections[name] = None`。
3. 需要区分时，用 **哨兵对象**：

```python
_UNSET = object()          # 第 2 课的 EventStream.end(result=_UNSET) 就用了这招
```

以后看到 `_UNSET`，就知道那里在复刻 `arguments.length === 0`。

---

## 6. 运行自测

```bash
cd python-port
python tests/test_lesson01.py
```

期望：10 个 `PASS` + `第 1 课全部通过`。

---

## 7. 动手练习（做完再进第 2 课）

1. 给 `Model` 补上 `type: Optional[str]`（对应 JS 的 `type?: "chat"`），并说明为什么它必须是 `Optional`。
2. 写 `message_preview(message) -> str`：assistant 消息只输出前 80 字符的文本，toolResult 输出 `"[tool] name: 文本"`。（第 7 课的事件日志会用到）
3. 思考题：`ToolResultMessage.content` 里能放图片。那么 `content_text()` 对一条只含图片的 toolResult 返回什么？这个结果会被谁使用？（提示：`estimate.ts` 和 provider 的降级逻辑）

---

下一课：[02 · 事件流](02-event-stream.md) — 把 JS 的 `Promise` 队列改写成 `asyncio.Future`，这是整个项目最像「心脏」的 135 行。
