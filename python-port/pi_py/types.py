"""消息与内容块类型层。

对应 JS: packages/ai/src/types.ts（消息部分）+ packages/ai/src/utils/text.ts。

设计约定（整个 Python 移植版通用）：
- JS 的 interface / 联合类型 → dataclass + typing.Union。
- 字段名 camelCase → snake_case；序列化到 provider 时再转回 camelCase。
- JS 里 `{ ...msg }` 的浅拷贝 → `copy_message()`（dataclasses.replace + 复制 content 列表）。
- JS 的 `undefined` 与 `null` 在 Python 里都表现为 `None`，靠「字段为 None 即视为未设置」复刻。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# 时间与 JSON
# ---------------------------------------------------------------------------

JsonValue = Any
"""对应 TS 的 JsonValue。Python 侧不做静态 JSON 约束，运行时靠规范自律。"""


def now_ms() -> int:
    """对应 JS 的 Date.now()：毫秒级 Unix 时间戳。"""
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# 内容块（content blocks）
# ---------------------------------------------------------------------------


@dataclass
class TextContent:
    """对应 TS 的 TextContent。"""

    text: str
    text_signature: Optional[str] = None
    type: str = field(default="text", init=False)
    """判别字段。JS 里它是普通属性；这里设成 init=False，防止被改成别的值。"""


@dataclass
class ThinkingContent:
    """对应 TS 的 ThinkingContent（推理模型的可读思考内容）。"""

    thinking: str
    thinking_signature: Optional[str] = None
    redacted: Optional[bool] = None
    type: str = field(default="thinking", init=False)


@dataclass
class ImageContent:
    """对应 TS 的 ImageContent。data 是 base64 编码的图片数据。"""

    data: str
    mime_type: str
    type: str = field(default="image", init=False)


@dataclass
class ToolCall:
    """对应 TS 的 ToolCall：模型发起的一次工具调用。

    arguments_error 非空表示模型吐出的参数不是合法 JSON 对象，此时 arguments 为 {}，
    交给 validation 层报错，而不是在这里抛异常。
    """

    id: str
    name: str
    arguments: Dict[str, Any]
    thought_signature: Optional[str] = None
    namespace: Optional[str] = None
    arguments_error: Optional[str] = None
    type: str = field(default="toolCall", init=False)


ContentBlock = Union[TextContent, ThinkingContent, ImageContent, ToolCall]
"""助手消息里可能出现的内容块。"""


# ---------------------------------------------------------------------------
# 用量与费用
# ---------------------------------------------------------------------------


@dataclass
class Cost:
    """对应 TS 的 Usage["cost"]。"""

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0
    total_from_provider: Optional[bool] = None
    """total 是 provider 实际计费值时 true；是目录估算时 false/None。"""


@dataclass
class Usage:
    """对应 TS 的 Usage。注意 output 已经包含 reasoning，不是并列关系。"""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: Cost = field(default_factory=Cost)
    cache_write_1h: Optional[int] = None
    reasoning: Optional[int] = None


def empty_usage() -> Usage:
    """对应 packages/agent/src/agent.ts 里的 EMPTY_USAGE 常量。

    JS 共享同一个常量对象；这里每次返回新对象，避免一处修改污染全局。
    """
    return Usage()


def calculate_context_tokens(usage: Usage) -> int:
    """对应 utils/estimate.ts 的 calculateContextTokens。"""
    return usage.total_tokens or (usage.input + usage.output + usage.cache_read + usage.cache_write)


# ---------------------------------------------------------------------------
# 工具声明
# ---------------------------------------------------------------------------


@dataclass
class ToolReference:
    """对应 TS 的 ToolReference：只按名字引用已声明的工具。"""

    name: str


@dataclass
class Tool:
    """对应 TS 的 Tool：发给模型的工具声明。

    parameters 是 JSON Schema（dict）。JS 侧用 typebox 生成，Python 侧直接手写 dict
    或由 pydantic 的 model_json_schema() 生成。
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    constrained_sampling: Optional[Any] = None


# ---------------------------------------------------------------------------
# 消息（messages）
# ---------------------------------------------------------------------------


@dataclass
class SystemMessage:
    """对应 TS 的 SystemMessage。

    system 消息是「账本」：首条消息承载 base prompt 和初始工具，
    之后的消息通过 sections / tools_added / tools_removed 做增量修改，
    按顺序回放（见第 3 课 get_current_system_message）得到当前状态。
    """

    content: Union[str, List[TextContent]]
    timestamp: int
    sections: Optional[Dict[str, Optional[str]]] = None
    """有序命名字段。值为 None 表示删除该 section。"""
    tools_added: Optional[List[Tool]] = None
    tools_removed: Optional[List[ToolReference]] = None
    role: str = field(default="system", init=False)


@dataclass
class UserMessage:
    """对应 TS 的 UserMessage。"""

    content: Union[str, List[Union[TextContent, ImageContent]]]
    timestamp: int
    role: str = field(default="user", init=False)


@dataclass
class AssistantMessage:
    """对应 TS 的 AssistantMessage。

    stop_reason 取值为 StopReason 中的常量；error/aborted 时 error_message 必须填。
    """

    content: List[ContentBlock]
    api: str
    provider: str
    model: str
    usage: Usage
    stop_reason: str
    timestamp: int
    response_model: Optional[str] = None
    response_id: Optional[str] = None
    provider_thinking_level: Optional[str] = None
    thinking_level: Optional[str] = None
    diagnostics: Optional[List[Any]] = None
    deferred: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    raw_stop_reason: Optional[str] = None
    end_turn: Optional[bool] = None
    duration_ms: Optional[int] = None
    role: str = field(default="assistant", init=False)


@dataclass
class ToolResultMessage:
    """对应 TS 的 ToolResultMessage。工具结果是一种消息，会进入上下文。"""

    tool_call_id: str
    tool_name: str
    content: List[Union[TextContent, ImageContent]]
    is_error: bool
    timestamp: int
    details: Optional[JsonValue] = None
    usage: Optional[Usage] = None
    nested_calls: Optional[Dict[str, Any]] = None
    duration_ms: Optional[int] = None
    role: str = field(default="toolResult", init=False)


Message = Union[SystemMessage, UserMessage, AssistantMessage, ToolResultMessage]
"""对应 TS 的 Message 联合类型。"""


# ---------------------------------------------------------------------------
# 停止原因（对应 TS 的 StopReason 字面量联合）
# ---------------------------------------------------------------------------


class StopReason:
    """用常量类代替 TS 的字符串字面量联合。"""

    PENDING = "pending"
    STOP = "stop"
    LENGTH = "length"
    TOOL_USE = "toolUse"
    ERROR = "error"
    ABORTED = "aborted"
    DEFERRED = "deferred"


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------


@dataclass
class Model:
    """对应 TS 的 Model。只保留 agent 循环真正用到的字段。"""

    id: str
    name: str
    api: str
    provider: str
    base_url: str = ""
    reasoning: bool = False
    input: List[str] = field(default_factory=list)
    cost: Cost = field(default_factory=Cost)
    context_window: int = 0
    max_tokens: int = 0
    headers: Optional[Dict[str, str]] = None
    thinking_level_map: Optional[Dict[str, Optional[str]]] = None
    sampling_params: Optional[Dict[str, Any]] = None
    sampling_params_by_thinking_level: Optional[Dict[str, Dict[str, Any]]] = None


def unknown_model() -> Model:
    """对应 packages/agent/src/agent.ts 的 DEFAULT_MODEL。

    Agent 在用户没给模型时用它兜底，保证循环永远有一个结构完整的 model。
    """
    return Model(id="unknown", name="unknown", api="unknown", provider="unknown")


# ---------------------------------------------------------------------------
# 文本工具（对应 utils/text.ts）
# ---------------------------------------------------------------------------


def content_text(content: Union[str, List[ContentBlock]], separator: str = "\n") -> str:
    """从消息 content 里抽取并拼接所有 text 块。

    JS 原实现：
        if (typeof content === "string") return content;
        return content.filter(b => b.type === "text").map(b => b.text).join(separator);
    """
    if isinstance(content, str):
        return content
    return separator.join(block.text for block in content if isinstance(block, TextContent))


def get_system_message_text(message: SystemMessage) -> str:
    """把 system 消息渲染成完整 prompt：content 在前，sections 依次在后。

    空串会被过滤，非空片段用两个换行连接。
    """
    parts: List[str] = [content_text(message.content)]
    for value in (message.sections or {}).values():
        # None 表示该 section 被删除，不参与渲染
        if value is not None:
            parts.append(value)
    return "\n\n".join(part for part in parts if len(part) > 0)


# ---------------------------------------------------------------------------
# 拷贝工具
# ---------------------------------------------------------------------------


def copy_message(message: Message) -> Message:
    """对应 JS 的 `{ ...message }`。

    dataclasses.replace 生成浅拷贝；content 列表再复制一层，
    避免调用方 push 到副本的 content 里污染原消息。
    """
    clone = replace(message)
    if isinstance(getattr(clone, "content", None), list):
        clone.content = list(clone.content)  # type: ignore[union-attr]
    return clone


def message_role(message: Any) -> str:
    """读取消息的 role，兼容自定义消息类型（dict 形式的扩展消息）。"""
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))
