---
name: csl-microthreads
description: WSE-3 microthreads in CSL — the explicit concurrent-thread model for async DSD operations. Covers the microthread_id type and @get_ut_id constructor, how WSE-3 differs from WSE-2's implicit queue-based threading (WSE-2 deduces a microthread id from the highest-priority queue operand; WSE-3 requires/permits explicit .ut_id), the .ut_id field on DSD-op configs and @load_to_dsr, the dest > src0 > src1 priority hierarchy for inferring a default ut_id, the many-to-many queue↔microthread relationship that enables concurrent ops over the same queue, blocking/unblocking via @block/@unblock on microthread ids, and pointers to the WSE-3 dispatch builtins (@queue_flush, @set_empty_queue_handler, @set_control_task_table, @bind_rotating_tasks).
---

# Microthreads (WSE-3)

A *microthread* is a hardware-scheduled execution thread that drives an async DSD operation. When you write:

```csl
@fadds(out_dsd, a_dsd, b_dsd, .{ .async = true });
```

…the op detaches from the calling task and runs on a microthread until completion. On WSE-3, microthreads are first-class entities that you can name, schedule, block, and unblock. On WSE-2 they're implicit and identified by the queue they're using.

This skill is about the WSE-3 model. WSE-2's implicit-from-queue rule is covered in [SKILL-DSDS.md](SKILL-DSDS.md#input-output-queues--microthread-allocation).

## Why WSE-3 needs explicit microthreads

On WSE-2, a single async op consumes one microthread, and that microthread's identity equals the involved queue's id. Two ops sharing a queue id collide:

```csl
// WSE-2: both ops use microthread 0 -> compile error
@mov16(out_dsd, mem1_dsd, .{ .async = true });   // microthread 0 (output_queue 0)
@mov16(mem2_dsd, in_dsd,  .{ .async = true });   // microthread 0 (input_queue 0)
```

WSE-3 decouples microthread identity from queue id. The same queue can drive two concurrent microthreads; the same microthread can serve multiple queues. You name what you want:

```csl
// WSE-3: separate explicit microthread ids -> concurrent OK
const ut_out = @get_ut_id(0);
const ut_in  = @get_ut_id(1);

@mov16(out_dsd, mem1_dsd, .{ .async = true, .ut_id = ut_out });
@mov16(mem2_dsd, in_dsd,  .{ .async = true, .ut_id = ut_in });
```

## The `microthread_id` type and `@get_ut_id`

```csl
const ut0 = @get_ut_id(0);    // comptime-constructed microthread id
const ut1 = @get_ut_id(1);

// Or at runtime, from a u16:
var index: u16 = 2;
const ut_dynamic = @get_ut_id(index);    // accepted if `index` is `u16`
```

`@get_ut_id` accepts:

- a comptime expression of any unsigned integer type — validated against valid microthread ranges at compile time, **or**
- a runtime `u16` — accepted; range check is the caller's responsibility.

## Specifying microthread ids on ops

The `.ut_id` field appears on any async op options struct, and also on `@load_to_dsr` options:

```csl
@fadds(out_dsd, a_dsd, b_dsd, .{ .async = true, .ut_id = my_ut });

@load_to_dsr(my_dsr, my_dsd, .{ .async = true, .ut_id = my_ut, .activate = next });
```

## Implicit `ut_id` — the default-resolution rule

If you don't supply `.ut_id`, WSE-3 assigns one based on the operands' queue ids. The fabric operand with the **highest priority** in this order determines the microthread:

1. **Destination operand.** If the op writes to a `fabout_dsd`, its `output_queue` id becomes the microthread id.
2. **First source.** Otherwise, the first source's `input_queue` id (if it's a `fabin_dsd`).
3. **Second source.** Otherwise, the second source.

If no operand is a fabric DSD (all memory or FIFO), there's no implicit fabric-derived id; the op still runs on a microthread, but the compiler picks one.

```csl
const fab_in = @get_dsd(fabin_dsd, .{ .extent = N, .input_queue = @get_input_queue(3) });
@mov16(mem_dsd, fab_in, .{ .async = true });    // microthread id = 3 (from the source)
```

The point of `.ut_id` is to *override* this default when you want two ops with the same queue to use different microthreads, or two ops with different queues to share one.

## Many-to-many queue ↔ microthread

The relationship is fully decoupled on WSE-3:

| Pattern | Meaning |
|---|---|
| Two `.ut_id`s, same queue | Two concurrent async ops over the same fabric channel. Each independent. |
| One `.ut_id`, two queues | A microthread that pipelines two ops sequentially (e.g., read then write). |
| Default `.ut_id` for every op | Equivalent to WSE-2 behaviour. |

## Blocking and unblocking microthreads

`@block` and `@unblock` accept microthread ids:

```csl
comptime {
  @block(ut0);   // start as blocked — op detaches but doesn't run yet
}

task on_data() void {
  @unblock(ut0);
  @fadds(out_dsd, a_dsd, b_dsd, .{ .async = true, .ut_id = ut0 });
  // op runs immediately
}

task halt_microthread() void {
  @block(ut0);    // pause the microthread before its next op cycle
}
```

This is the explicit equivalent of throttling via task-level `@block`/`@unblock` — control happens at the *thread* level, not at the *task* level.

## WSE-3 dispatch builtins (related)

These are documented in [SKILL-BUILTINS.md](SKILL-BUILTINS.md#wse-3-only-builtins), but live in the same conceptual area:

| Builtin | One-line |
|---|---|
| `@queue_flush(queue_id)` | Fire teardown when the queue next reaches empty. Runtime-only. |
| `@set_empty_queue_handler(fn, queue_id)` | Run `fn` when `queue_id` flushes empty after `@queue_flush`. Caller must reset the flush-status register. |
| `@set_control_task_table(.{ .instructions = N, .stride = S })` | Decouple control tasks from the shared task table. `N` ∈ {2,4,8} (default 4); `S` ∈ 1..7 (default 1). At most once per `comptime` block. |
| `@bind_rotating_tasks(main, alt, task_id, .{ .limit = L, .init = I? })` | Bind a data-task / control-task pair that rotate. At most two concurrent rotation pairs. |

`@bind_rotating_tasks` is the most distinctive: it lets a single task id alternate between a data task and a control task on each invocation, controlled by a hardware counter (`limit` is the cycle period).

## Patterns

### Two concurrent ops over the same color

```csl
const ut0 = @get_ut_id(0);
const ut1 = @get_ut_id(1);

// Both write to the same output_queue / fabric_color, but on different microthreads:
@mov16(out_dsd, src1_dsd, .{ .async = true, .ut_id = ut0 });
@mov16(out_dsd, src2_dsd, .{ .async = true, .ut_id = ut1 });
```

### Microthread-level throttle

```csl
const ut_slow = @get_ut_id(2);

comptime { @block(ut_slow); }   // start blocked

task gate_open() void {
  @unblock(ut_slow);            // allow the slow microthread to make progress
}
task gate_close() void {
  @block(ut_slow);              // pause it again
}

task work() void {
  @fadds(big_out, big_a, big_b, .{ .async = true, .ut_id = ut_slow });
}
```

### Cross-arch portability

```csl
const op_opts = if (@is_arch("wse3"))
  .{ .async = true, .ut_id = @get_ut_id(0) }
else
  .{ .async = true };                            // WSE-2 infers from queue id

@mov16(dst_dsd, src_dsd, op_opts);
```

Or branch the whole op:

```csl
if (@is_arch("wse3")) {
  @mov16(dst, src, .{ .async = true, .ut_id = ut0 });
} else {
  @mov16(dst, src, .{ .async = true });
}
```

## Resource limits

Microthread slot count is hardware-fixed. The exact count is documented per arch in the upstream reference — typical kernels use a handful. The compiler errors if you exceed available slots.

If you write a kernel with many concurrent ops, prefer reusing microthread ids across non-overlapping time windows (block until safe, then reuse) rather than allocating new ones.

## Gotchas

- **`@get_ut_id` accepts comptime *or* runtime u16.** A comptime int gets range-checked; a runtime value doesn't. If your `index` is `i16`, you'll need an `@as(u16, index)`.
- **`.ut_id` overrides the queue-derived default.** Two ops sharing `.ut_id` serialize, even if their queues differ — exactly the inverse of the WSE-2 collision rule.
- **`@block`/`@unblock` work on both *task* ids and *microthread* ids.** The semantics differ: blocking a task gates dispatch; blocking a microthread gates op execution. Same builtin, different identity types.
- **WSE-3 ops without `.ut_id` still consume a microthread.** They just use the implicit id. So even an arch-agnostic codebase has the same concurrency model on WSE-3 — `.ut_id` only matters when you need finer control.
- **`@queue_flush` is runtime-only.** Calling it from `comptime { }` is an error.
- **`@set_empty_queue_handler` requires the user to clear the flush-status register manually** inside the handler. Forgetting this re-fires the handler immediately.
- **`@set_control_task_table` can be called at most once per `comptime` block.** Multiple invocations require multiple top-level `comptime { }` blocks (which concatenate).
- **`@bind_rotating_tasks` permits at most two concurrent rotation pairs per PE.** Exceeding this is a compile error.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `.async` options and the WSE-2 implicit-microthread rule.
- [SKILL-TASKS.md](SKILL-TASKS.md) — `@block` / `@unblock` on *task* ids (distinct from microthread ids).
- [SKILL-DSRS.md](SKILL-DSRS.md) — `.ut_id` on `@load_to_dsr`.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md#wse-3-only-builtins) — `@get_ut_id`, `@queue_flush`, `@set_empty_queue_handler`, `@set_control_task_table`, `@bind_rotating_tasks`.
- Bundled tutorial: `topic-15-wse3-microthreads/`.
- Upstream docs: <https://sdk.cerebras.net/csl/language/microthreads_wse3>
