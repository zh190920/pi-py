"""第 1 课自测：消息与内容块。

运行：python tests/test_lesson01.py
不依赖 pytest，直接用 assert。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_py.types import (  # noqa: E402
    AssistantMessage,
    StopReason,
    SystemMessage,
    TextContent,
    Tool,
    ToolCall,
    ToolReference,
    ToolResultMessage,
    UserMessage,
    calculate_context_tokens,
    content_text,
    copy_message,
    empty_usage,
    get_system_message_text,
    now_ms,
    unknown_model,
)


def test_discriminators_are_fixed():
    assert TextContent("hi").type == "text"
    assert UserMessage("hi", 0).role == "user"
    assert ToolCall("id1", "read", {}).type == "toolCall"
    # role/type 是 init=False，赋值会走普通属性写入，但构造时不可能写错
    msg = SystemMessage("p", 0)
    assert msg.role == "system"


def test_content_text_joins_text_blocks_only():
    assert content_text("plain") == "plain"
    blocks = [TextContent("a"), ToolCall("id", "t", {}), TextContent("b")]
    assert content_text(blocks) == "a\nb"
    assert content_text(blocks, separator=" | ") == "a | b"


def test_get_system_message_text_appends_sections_and_skips_null():
    msg = SystemMessage(
        content=[TextContent("base prompt")],
        timestamp=0,
        sections={"tools": "tool docs", "removed": None},
    )
    assert get_system_message_text(msg) == "base prompt\n\ntool docs"


def test_get_system_message_text_skips_empty_parts():
    msg = SystemMessage(content="", timestamp=0, sections={"a": ""})
    assert get_system_message_text(msg) == ""


def test_copy_message_is_shallow_like_spread():
    original = AssistantMessage(
        content=[TextContent("hello")],
        api="anthropic-messages",
        provider="anthropic",
        model="claude",
        usage=empty_usage(),
        stop_reason=StopReason.STOP,
        timestamp=now_ms(),
    )
    clone = copy_message(original)
    assert clone is not original
    assert clone.content is not original.content
    # 元素本身仍共享引用，这正是 JS 浅拷贝 { ...msg } 的行为
    assert clone.content[0] is original.content[0]

    clone.content.append(TextContent("more"))
    assert len(original.content) == 1


def test_empty_usage_is_independent():
    a = empty_usage()
    b = empty_usage()
    a.cost.input = 9.9
    assert b.cost.input == 0.0


def test_calculate_context_tokens_falls_back_to_sum():
    usage = empty_usage()
    usage.input, usage.output, usage.cache_read, usage.cache_write = 10, 5, 3, 2
    assert calculate_context_tokens(usage) == 20
    usage.total_tokens = 99
    assert calculate_context_tokens(usage) == 99


def test_unknown_model_shape():
    model = unknown_model()
    assert (model.api, model.provider, model.id) == ("unknown", "unknown", "unknown")
    assert model.context_window == 0


def test_tool_result_carries_error_flag():
    result = ToolResultMessage(
        tool_call_id="call_1",
        tool_name="read",
        content=[TextContent("boom")],
        is_error=True,
        timestamp=now_ms(),
        details={},
    )
    assert result.role == "toolResult"
    assert result.is_error is True


def test_system_message_tool_deltas():
    tool = Tool(name="read", description="read a file", parameters={"type": "object"})
    msg = SystemMessage(
        content="",
        timestamp=1,
        tools_added=[tool],
        tools_removed=[ToolReference("old_tool")],
    )
    assert msg.tools_added[0].name == "read"
    assert msg.tools_removed[0].name == "old_tool"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    if failures:
        print(f"\n{failures} 个用例失败")
        sys.exit(1)
    print("\n第 1 课全部通过")
