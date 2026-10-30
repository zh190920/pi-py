"""事件流：把「生产者边生成边 push」和「消费者 async for」解耦。

对应 JS: packages/ai/src/utils/event-stream.ts。

JS 用 Promise + 自定义等待队列实现；Python 用 asyncio.Future。
语义必须完全一致：
- push() 在流结束后静默丢弃（不报错）。
- 判断某事件是「终止事件」：先置 done、解析最终结果，然后该事件仍然会被投递。
- end() 可以不传结果（此时 result() 永远挂起，和 JS 一致）。
- __aiter__ 在队列有货时先出货，再看 done，避免丢掉最后一条事件。
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Any, AsyncIterator, Callable, Deque, Generic, List, Optional, TypeVar

from .types import AssistantMessage, now_ms

T = TypeVar("T")
R = TypeVar("R")

_UNSET = object()
"""占位符：区分「没传参数」与「传了 None」。对应 JS 的 arguments.length / undefined。"""

_DONE = object()
"""等待者收到它表示流已结束。"""


class FifoQueue(Generic[T]):
    """对应 JS 的 FifoQueue：入队进 incoming，出队时把 incoming 倒进 outgoing。"""

    def __init__(self) -> None:
        self._incoming: Deque[T] = deque()
        self._outgoing: Deque[T] = deque()

    def __len__(self) -> int:
        return len(self._incoming) + len(self._outgoing)

    def enqueue(self, value: T) -> None:
        self._incoming.append(value)

    def dequeue(self) -> Optional[T]:
        if not self._outgoing:
            while self._incoming:
                self._outgoing.append(self._incoming.pop())
        return self._outgoing.pop() if self._outgoing else None


def _round_half_up(value: float) -> int:
    """对应 JS 的 Math.round：.5 一律向上。Python 的 round() 是银行家舍入，不能用。"""
    return int(math.floor(value + 0.5))


class EventStream(Generic[T, R]):
    """对应 JS 的 EventStream<T, R>。

    is_complete(event) 判断终止事件；extract_result(event) 从终止事件里取最终结果。
    """

    def __init__(self, is_complete: Callable[[T], bool], extract_result: Callable[[T], R]) -> None:
        self._queue: FifoQueue[T] = FifoQueue()
        self._waiting: Deque[asyncio.Future] = deque()
        self._done = False
        self._has_result = False
        self._final_result: Any = None
        self._result_waiters: List[asyncio.Future] = []
        self._is_complete = is_complete
        self._extract_result = extract_result

    @property
    def done(self) -> bool:
        return self._done

    # -- 生产者侧 ---------------------------------------------------------

    def push(self, event: T) -> None:
        if self._done:
            return

        if self._is_complete(event):
            self._done = True
            self._resolve_final(self._extract_result(event))

        waiter = self._next_waiter()
        if waiter is not None:
            waiter.set_result(event)
        else:
            self._queue.enqueue(event)

    def end(self, result: Any = _UNSET) -> None:
        self._done = True
        if result is not _UNSET:
            self._resolve_final(result)
        # 唤醒所有等待者，告诉它们「没有更多事件了」
        while self._waiting:
            waiter = self._waiting.popleft()
            if not waiter.done():
                waiter.set_result(_DONE)

    # -- 消费者侧 ---------------------------------------------------------

    def __aiter__(self) -> AsyncIterator[T]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[T]:
        while True:
            if len(self._queue) > 0:
                yield self._queue.dequeue()
            elif self._done:
                return
            else:
                waiter: asyncio.Future = asyncio.get_event_loop().create_future()
                self._waiting.append(waiter)
                item = await waiter
                if item is _DONE:
                    return
                yield item

    async def result(self) -> R:
        """等待最终结果。可以重复 await；已出结果时立即返回。"""
        if self._has_result:
            return self._final_result
        waiter: asyncio.Future = asyncio.get_event_loop().create_future()
        self._result_waiters.append(waiter)
        return await waiter

    # -- 内部 -------------------------------------------------------------

    def _resolve_final(self, result: Any) -> None:
        if self._has_result:
            return
        self._has_result = True
        self._final_result = result
        for waiter in self._result_waiters:
            if not waiter.done():
                waiter.set_result(result)
        self._result_waiters.clear()

    def _next_waiter(self) -> Optional[asyncio.Future]:
        while self._waiting:
            waiter = self._waiting.popleft()
            if not waiter.done():
                return waiter
        return None


# ---------------------------------------------------------------------------
# 助手消息事件流
# ---------------------------------------------------------------------------


def _is_final_event(event: dict) -> bool:
    return event.get("type") in ("done", "error")


def _extract_final_result(event: dict) -> AssistantMessage:
    if event.get("type") == "done":
        return event["message"]
    if event.get("type") == "error":
        return event["error"]
    raise ValueError("Unexpected event type for final result")


class AssistantMessageEventStream(EventStream):
    """对应 JS 的 AssistantMessageEventStream。

    在 EventStream 基础上多一件事：给「本次流产出的最终消息」补 duration_ms。
    从流创建时刻开始计时；如果消息自带 duration_ms，或它的 timestamp 早于流创建时刻
    （说明是别处产生、这里只是转发，比如稍后取回的 deferred 结果），则不打时间。
    """

    def __init__(self) -> None:
        super().__init__(_is_final_event, _extract_final_result)
        self._started_at = now_ms()
        self._started_at_monotonic = time.perf_counter()

    def push(self, event: dict) -> None:
        if event.get("type") == "done":
            self._time(event["message"])
        elif event.get("type") == "error":
            self._time(event["error"])
        super().push(event)

    def end(self, result: Any = _UNSET) -> None:
        # JS 里 end(undefined) 只结束流、不解析结果；Python 的 None 等价于 undefined
        if result is None:
            result = _UNSET
        if result is not _UNSET:
            self._time(result)
        super().end(result)

    def _time(self, message: AssistantMessage) -> None:
        # 注意顺序：此处 _done 仍是 False（终止事件尚未入队），与 JS 一致
        if self._done or message.duration_ms is not None or message.timestamp < self._started_at:
            return
        elapsed_ms = (time.perf_counter() - self._started_at_monotonic) * 1000.0
        message.duration_ms = max(0, _round_half_up(elapsed_ms))


def create_assistant_message_event_stream() -> AssistantMessageEventStream:
    """对应 JS 的 createAssistantMessageEventStream()，供扩展/适配器构造流。"""
    return AssistantMessageEventStream()
