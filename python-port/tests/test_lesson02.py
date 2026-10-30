"""第 2 课自测：事件流。

运行：python tests/test_lesson02.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_py.event_stream import (  # noqa: E402
    AssistantMessageEventStream,
    EventStream,
    FifoQueue,
)
from pi_py.types import (  # noqa: E402
    AssistantMessage,
    StopReason,
    TextContent,
    empty_usage,
    now_ms,
)


def make_message(timestamp=None, duration_ms=None):
    return AssistantMessage(
        content=[TextContent("hi")],
        api="faux",
        provider="faux",
        model="faux-1",
        usage=empty_usage(),
        stop_reason=StopReason.STOP,
        timestamp=now_ms() if timestamp is None else timestamp,
        duration_ms=duration_ms,
    )


def test_fifo_queue_order():
    q = FifoQueue()
    for i in range(3):
        q.enqueue(i)
    assert len(q) == 3
    assert [q.dequeue(), q.dequeue(), q.dequeue()] == [0, 1, 2]
    assert q.dequeue() is None


def test_push_before_consume():
    async def main():
        stream = EventStream(lambda e: e == "stop", lambda e: "final")
        stream.push(1)
        stream.push(2)
        stream.push("stop")
        got = [e async for e in stream]
        assert got == [1, 2, "stop"]
        assert await stream.result() == "final"

    asyncio.run(main())


def test_consumer_waits_for_producer():
    async def main():
        stream = EventStream(lambda e: e == "stop", lambda e: "final")

        async def producer():
            await asyncio.sleep(0)
            stream.push("a")
            await asyncio.sleep(0)
            stream.push("stop")

        task = asyncio.ensure_future(producer())
        got = [e async for e in stream]
        await task
        assert got == ["a", "stop"]
        assert await stream.result() == "final"

    asyncio.run(main())


def test_end_without_result_leaves_result_pending():
    async def main():
        stream = EventStream(lambda e: e == "stop", lambda e: "final")
        stream.push("x")
        stream.end()
        assert [e async for e in stream] == ["x"]
        try:
            await asyncio.wait_for(stream.result(), timeout=0.01)
        except asyncio.TimeoutError:
            return
        raise AssertionError("result() 不应在 end() 无参时解析")

    asyncio.run(main())


def test_end_with_result():
    async def main():
        stream = EventStream(lambda e: e == "stop", lambda e: "from-event")
        stream.end("from-end")
        assert [e async for e in stream] == []
        assert await stream.result() == "from-end"

    asyncio.run(main())


def test_push_after_done_is_ignored():
    async def main():
        stream = EventStream(lambda e: e == "stop", lambda e: "final")
        stream.push("stop")
        stream.push("late")
        assert [e async for e in stream] == ["stop"]

    asyncio.run(main())


def test_assistant_stream_times_final_message():
    async def main():
        stream = AssistantMessageEventStream()
        message = make_message(timestamp=now_ms() + 10)
        stream.push({"type": "start", "partial": make_message(timestamp=now_ms() + 10)})
        stream.push({"type": "done", "reason": "stop", "message": message})
        events = [e async for e in stream]
        assert len(events) == 2
        assert message.duration_ms is not None
        assert message.duration_ms >= 0
        assert await stream.result() is message

    asyncio.run(main())


def test_assistant_stream_skips_forwarded_message():
    async def main():
        stream = AssistantMessageEventStream()
        # timestamp 早于流创建时刻：说明是别处产生、这里只转发
        message = make_message(timestamp=0)
        stream.push({"type": "done", "reason": "stop", "message": message})
        [e async for e in stream]
        assert message.duration_ms is None

    asyncio.run(main())


def test_assistant_stream_keeps_existing_duration():
    async def main():
        stream = AssistantMessageEventStream()
        message = make_message(timestamp=now_ms() + 10, duration_ms=42)
        stream.push({"type": "done", "reason": "stop", "message": message})
        [e async for e in stream]
        assert message.duration_ms == 42

    asyncio.run(main())


def test_assistant_stream_error_event_resolves_error_message():
    async def main():
        stream = AssistantMessageEventStream()
        message = make_message(timestamp=now_ms() + 10, duration_ms=None)
        message.stop_reason = StopReason.ERROR
        message.error_message = "boom"
        stream.push({"type": "error", "reason": "error", "error": message})
        [e async for e in stream]
        assert await stream.result() is message
        assert message.duration_ms is not None

    asyncio.run(main())


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
    print("\n第 2 课全部通过")
