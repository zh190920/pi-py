# 第 2 课 · 事件流（EventStream）

**学完你会得到**：`pi_py/event_stream.py`——一个「生产者边 push、消费者 async for」的无锁队列，外加自动给助手消息打 `durationMs` 的子类。
**对应 JS**：`packages/ai/src/utils/event-stream.ts`（135 行，全项目性价比最高的 135 行）
**代码**：[`pi_py/event_stream.py`](../pi_py/event_stream.py) · **自测**：[`tests/test_lesson02.py`](../tests/test_lesson02.py)

---

## 0. 为什么需要它

LLM 回复是流式的：`streamFn` 被调用后**立刻**返回一个对象，然后后台不断往里塞 `text_delta`。调用方拿到对象就 `for await` 消费，还没到的事件就等着。

这就是「异步队列 + 终止信号 + 最终结果」三合一。JS 用 135 行 Promise 实现；Python 用 `asyncio.Future` 实现同样的语义。

它需要同时支持三种时序，缺一不可：

```
时序 A（生产快于消费）：push ×3  →  之后才 async for  →  立刻依次拿到 3 条
时序 B（消费快于生产）：先 async for 挂起  →  push  →  唤醒并拿到
时序 C（结束）        ：end()  →  挂起的消费者全部醒来 → 循环退出
```

---

## 1. `FifoQueue`：双栈队列

JS（`event-stream.ts:3`）：

```ts
class FifoQueue<T> {
	private incoming: T[] = [];
	private outgoing: T[] = [];
	get length() { return this.incoming.length + this.outgoing.length; }
	enqueue(value: T): void { this.incoming.push(value); }
	dequeue(): T | undefined {
		if (this.outgoing.length === 0) {
			while (this.incoming.length > 0) this.outgoing.push(this.incoming.pop()!);
		}
		return this.outgoing.pop();
	}
}
```

Python：

```python
class FifoQueue(Generic[T]):
    def __init__(self):
        self._incoming = deque()
        self._outgoing = deque()

    def __len__(self) -> int:
        return len(self._incoming) + len(self._outgoing)

    def enqueue(self, value: T) -> None:
        self._incoming.append(value)

    def dequeue(self) -> Optional[T]:
        if not self._outgoing:
            while self._incoming:
                self._outgoing.append(self._incoming.pop())
        return self._outgoing.pop() if self._outgoing else None
```

翻译要点：

- `get length()` → `__len__()`，于是 `len(q)` 可用。
- 数组 `push/pop` → `deque.append/pop`（两端都是 O(1)）。
- `T | undefined` → `Optional[T]`，空队列返回 `None`。

> **为什么不直接用 `collections.deque` 一个队列？** 可以，行为完全一样。保留双栈只是为了**和 JS 原实现一一对应**，方便你对照调试。第 1 课定过规矩：能原样就原样。

---

## 2. `EventStream` 的字段

JS（`event-stream.ts:26`）：

```ts
export class EventStream<T, R = T> implements AsyncIterable<T> {
	private queue = new FifoQueue<T>();
	private waiting = new FifoQueue<(value: IteratorResult<T>) => void>();
	protected done = false;
	private finalResultPromise: Promise<R>;
	private resolveFinalResult!: (result: R) => void;
	private isComplete: (event: T) => boolean;
	private extractResult: (event: T) => R;
```

Python：

```python
T = TypeVar("T"); R = TypeVar("R")
_UNSET = object()
_DONE = object()

class EventStream(Generic[T, R]):
    def __init__(self, is_complete: Callable[[T], bool], extract_result: Callable[[T], R]) -> None:
        self._queue: FifoQueue[T] = FifoQueue()
        self._waiting: Deque[asyncio.Future] = deque()
        self._done = False
        self._has_result = False
        self._final_result: Any = None
        self._result_waiters: List[asyncio.Future] = []
        self._is_complete = is_complete
        self._extract_result = extract_result
```

三处必须理解的差异：

| JS | Python | 为什么 |
|---|---|---|
| `waiting: FifoQueue<(result) => void>` 存 resolve 回调 | `_waiting: Deque[asyncio.Future]` 存 Future | Python 没有「手动 resolve 一个 Promise」的公开写法，Future 就是它的等价物 |
| 构造时 `new Promise(...)` 立刻建好最终结果 Promise | **懒创建**：先存 `_has_result/_final_result`，`result()` 被调用时才建 Future | 构造时可能还没有运行中的事件循环，`asyncio.Future()` 会拿不到 loop |
| `IteratorResult<T>` = `{value, done}` | 用 `_DONE` 哨兵对象 | 少一层对象分配，语义等价 |

---

## 3. `push()`：先判完成，再投递

JS（`event-stream.ts:43`）：

```ts
push(event: T): void {
	if (this.done) return;
	if (this.isComplete(event)) {
		this.done = true;
		this.resolveFinalResult(this.extractResult(event));
	}
	const waiter = this.waiting.dequeue();
	if (waiter) waiter({ value: event, done: false });
	else this.queue.enqueue(event);
}
```

Python：

```python
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
```

注意顺序，这里有一个非常容易写错的地方：

> **先把 `done` 置 true、解析最终结果，然后仍然要把这个终止事件投递出去。**

如果你「看到 done 就 return」，消费者会永远收不到 `done` / `error` 事件本身——而 `Agent` 正是靠消费 `done` 事件来拿到完整回复的。

`_next_waiter()` 里跳过了已取消的 Future（`waiter.done()` 为真），因为消费者可能被 `asyncio.wait_for` 取消。

---

## 4. `end()`：结束并唤醒所有等待者

JS（`event-stream.ts:60`）：

```ts
end(result?: R): void {
	this.done = true;
	if (result !== undefined) this.resolveFinalResult(result);
	while (this.waiting.length > 0) {
		const waiter = this.waiting.dequeue()!;
		waiter({ value: undefined as any, done: true });
	}
}
```

Python：

```python
def end(self, result: Any = _UNSET) -> None:
    self._done = True
    if result is not _UNSET:
        self._resolve_final(result)
    while self._waiting:
        waiter = self._waiting.popleft()
        if not waiter.done():
            waiter.set_result(_DONE)
```

关键点：

- **参数默认值用 `_UNSET` 而不是 `None`**。JS 用「有没有传参」区分 `end()` 和 `end(undefined)`；Python 里 `None` 是合法值，必须用哨兵才能复刻这个区分。
- JS 的「不解析最终结果」意味着 `result()` 永远挂起。Python 保持一致（测试 `test_end_without_result_leaves_result_pending` 就是验证这个）。

---

## 5. 异步迭代：`[Symbol.asyncIterator]`

JS（`event-stream.ts:72`）：

```ts
async *[Symbol.asyncIterator](): AsyncIterator<T> {
	while (true) {
		if (this.queue.length > 0) yield this.queue.dequeue()!;
		else if (this.done) return;
		else {
			const result = await new Promise<IteratorResult<T>>((resolve) => this.waiting.enqueue(resolve));
			if (result.done) return;
			yield result.value;
		}
	}
}
```

Python：

```python
def __aiter__(self):
    return self._iterate()

async def _iterate(self):
    while True:
        if len(self._queue) > 0:
            yield self._queue.dequeue()
        elif self._done:
            return
        else:
            waiter = asyncio.get_event_loop().create_future()
            self._waiting.append(waiter)
            item = await waiter
            if item is _DONE:
                return
            yield item
```

分支顺序**不能换**：

1. 队列有货 → 先出货。否则「最后一个事件 push 完同时置 done」时，消费者会直接退出，丢掉终止事件。
2. 队列空 + done → 退出。
3. 否则挂起等人 push。

`async *` → `async def` + `yield`，`for await (const e of s)` → `async for e in s`。Python 里把 `__aiter__` 写成返回 async generator 的普通方法，是最省事的写法（也避免自己实现 `__anext__` 的状态机）。

---

## 6. `result()`

JS：

```ts
result(): Promise<R> { return this.finalResultPromise; }
```

Python：

```python
async def result(self) -> R:
    if self._has_result:
        return self._final_result
    waiter = asyncio.get_event_loop().create_future()
    self._result_waiters.append(waiter)
    return await waiter
```

差异说明：

- JS 返回的是**同一个 Promise 对象**，所以可以反复 `.then()`。
- Python 的 `result()` 是一个协程，每次调用都会新建一个 Future，但被 `_resolve_final` 统一 set。效果相同：**可以被反复 await**。
- `_resolve_final` 用 `_has_result` 做幂等，保证「先到先得」：`push(done)` 之后再 `end(other)` 不会改结果。

---

## 7. `AssistantMessageEventStream`：多出来的 12 行

JS（`event-stream.ts:97`）：

```ts
export class AssistantMessageEventStream extends EventStream<AssistantMessageEvent, AssistantMessage> {
	readonly #startedAt = Date.now();
	readonly #startedAtMonotonic = performance.now();

	override push(event) {
		if (event.type === "done") this.#time(event.message);
		else if (event.type === "error") this.#time(event.error);
		super.push(event);
	}

	override end(result?) {
		if (result !== undefined) this.#time(result);
		super.end(result);
	}

	#time(message) {
		if (this.done || message.durationMs !== undefined || message.timestamp < this.startedAt) return;
		message.durationMs = Math.max(0, Math.round(performance.now() - this.startedAtMonotonic));
	}
}
```

Python：

```python
class AssistantMessageEventStream(EventStream):
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
        if result is None:
            result = _UNSET
        if result is not _UNSET:
            self._time(result)
        super().end(result)

    def _time(self, message) -> None:
        if self._done or message.duration_ms is not None or message.timestamp < self._started_at:
            return
        elapsed_ms = (time.perf_counter() - self._started_at_monotonic) * 1000.0
        message.duration_ms = max(0, _round_half_up(elapsed_ms))
```

逐个细节：

1. **`Date.now()` → `now_ms()`，`performance.now()` → `time.perf_counter()`**。前者是墙钟（用于和 `message.timestamp` 比较），后者是单调时钟（用于算耗时）。两个不能混用：系统时间被校准跳变时，墙钟差可能为负。
2. **`Math.round` → `_round_half_up`**。Python 的 `round()` 是银行家舍入（`round(2.5) == 2`），JS 是四舍五入（`Math.round(2.5) == 3`）。`int(x + 0.5)` 在正数区间等价，但负数会错，所以用 `math.floor(x + 0.5)`。
3. **`message.durationMs !== undefined` → `message.duration_ms is not None`**：已有耗时就不再覆盖。
4. **`message.timestamp < this.startedAt`**：这条消息是在本流创建之前产生的（比如稍后取回的 deferred 结果，或者被转发的响应），不属于本次流，不打时间。
5. **`this.done` 的判断时机**：`push` 里先 `_time` 再 `super.push`，所以 `_time` 执行时 `_done` 还是 `False`。如果先调 `super.push`，终止事件会把 `_done` 置真，`_time` 就直接 return 了——**顺序反了功能就悄悄失效**，这是本课最隐蔽的坑。

---

## 8. 事件用 dict，消息用 dataclass —— 为什么

本课的事件是普通 dict：

```python
{"type": "text_delta", "contentIndex": 0, "delta": "Hel", "partial": message}
```

而第 1 课的消息是 dataclass。判断标准：

| 用 dict | 用 dataclass |
|---|---|
| 纯数据传输、要序列化（事件会被 proxy/JSON 模式直接写盘） | 需要身份、需要被原地修改（`context.messages[i] = partial`） |
| 字段随 provider 变化 | 字段稳定、被大量代码按属性读取 |

对应关系：`event.type` → `event["type"]`，`event.partial` → `event["partial"]`。第 6 课你会看到 `switch (event.type)` 变成 `if/elif event["type"] == ...`。

> 注意字段名**保持 camelCase**（`contentIndex`、`toolCall`）。因为事件结构会被 `proxy.ts` 直接 `JSON.stringify` 发给服务端，改名就要在边界处做双向映射，得不偿失。这是一处与「内部统一 snake_case」规则的例外，写在这里备案。

---

## 9. 运行自测

```bash
cd python-port
python tests/test_lesson02.py
```

10 个用例覆盖：队列顺序、生产先于消费、消费先于生产、`end()` 无果、`end()` 带果、push-after-done 丢弃、耗时写入、转发消息不打时间、已有耗时保留、error 事件解析。

---

## 10. 动手练习

1. 给 `EventStream` 加 `close()`：结束流并**拒绝**所有等待中的 `result()`（`Future.set_exception`）。想想为什么上游没有这个需求。
2. 用 `EventStream` 写一个 `countdown(n)`：后台任务每秒 push 一个数字，最后 push 一个 `{"type":"done"}`。用它验证时序 B。
3. 思考题：如果一个消费者在 `async for` 中途 `break`，那些还在 `_waiting` 里的 Future 会怎样？生产者继续 `push` 会出问题吗？（提示：`_next_waiter` 的 `waiter.done()` 检查）

---

下一课：[03 · 转录层](03-transcript.md) — system 消息账本、工具声明 diff、`normalizeContext`。这三件事决定「模型这次到底看到什么」。
