"""第 2 课演示：手工推一个假的流式回复，看事件按顺序到达。

运行：python examples/02_event_stream_demo.py

它模拟的就是 provider 适配器内部做的事（第 9 课会换成真实 HTTP 流）：
  1. 先 push start，带一个空的 partial 消息；
  2. 每来一段文本，就修改同一个 partial 对象，再 push text_delta；
  3. 最后 push done，附带完整消息。

注意 partial 是「同一个对象的实时引用」，不是快照——这是 JS 原实现的约定，
消费者每次拿到的是「到目前为止的完整内容」。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_py.event_stream import AssistantMessageEventStream  # noqa: E402
from pi_py.types import (  # noqa: E402
    AssistantMessage,
    StopReason,
    TextContent,
    empty_usage,
    now_ms,
)

CHUNKS = ["你", "好", "，我", "是 Pi。"]


def make_partial() -> AssistantMessage:
    return AssistantMessage(
        content=[],
        api="demo",
        provider="demo",
        model="demo-1",
        usage=empty_usage(),
        stop_reason=StopReason.PENDING,
        timestamp=now_ms(),
    )


async def fake_provider(stream: AssistantMessageEventStream) -> None:
    partial = make_partial()
    stream.push({"type": "start", "partial": partial})

    for chunk in CHUNKS:
        # 往同一个 partial 里追加文本块
        if not partial.content:
            partial.content.append(TextContent(""))
        partial.content[0].text += chunk
        stream.push(
            {
                "type": "text_delta",
                "contentIndex": 0,
                "delta": chunk,
                "partial": partial,
            }
        )
        await asyncio.sleep(0.02)

    final = make_partial()
    final.content = [TextContent("".join(CHUNKS))]
    final.stop_reason = StopReason.STOP
    stream.push({"type": "done", "reason": "stop", "message": final})


async def main() -> None:
    stream = AssistantMessageEventStream()
    producer = asyncio.ensure_future(fake_provider(stream))

    async for event in stream:
        kind = event["type"]
        if kind == "start":
            print("[start] 流已建立")
        elif kind == "text_delta":
            print(f"[text_delta] {event['delta']!r}  ->  当前累计: {event['partial'].content[0].text}")
        elif kind == "done":
            print(f"[done] 最终文本: {event['message'].content[0].text}")
            print(f"[done] 本次耗时: {event['message'].duration_ms} ms")

    await producer
    final_message = await stream.result()
    print(f"[result] stop_reason={final_message.stop_reason}, blocks={len(final_message.content)}")


if __name__ == "__main__":
    asyncio.run(main())
