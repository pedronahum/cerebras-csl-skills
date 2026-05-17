---
name: csl-tasks
description: CSL tasks — the event-driven execution model. Covers data tasks (wavelet-triggered), local tasks (@activate-triggered), and control tasks (control-wavelet-triggered). Task ID types (data_task_id, local_task_id, control_task_id). Binding (@bind_data_task, @bind_local_task, @bind_control_task), id construction (@get_data_task_id from color on WSE-2 / from input_queue on WSE-3, @get_local_task_id, @get_control_task_id), activation (@activate), blocking/unblocking (@block/@unblock), queue initialization on WSE-3 (@initialize_queue). Reserved task ID slots, completion via DSD op .activate/.unblock options, WSE-2 vs WSE-3 differences.
---

# Tasks: CSL's Event-Driven Execution Model

A PE has no implicit "main loop." All code runs inside **tasks** — functions bound to a *task ID* that the hardware fires when a triggering event occurs. There are three kinds of triggers, and therefore three kinds of tasks:

| Task kind | Trigger | Argument | Use case |
|---|---|---|---|
| **Data task** | A *data wavelet* arrives on a bound color (WSE-2) or input queue (WSE-3) | The wavelet payload | Stream processing — fire per-element as data arrives |
| **Local task** | `@activate(id)` is called, **or** a fabric DSD op completes with `.activate = task` | none | Run-to-completion work the PE schedules itself |
| **Control task** | A *control wavelet* arrives whose payload id matches | id + data section from the wavelet | Sentinel/end-of-stream signals, switch-table flips |

All three are declared with the `task` keyword (not `fn`):

```csl
task data_handler(payload: f32) void { ... }       // data task: arg = wavelet
task local_helper() void { ... }                   // local task: no args
task on_sentinel() void { ... }                    // control task: no args
```

Bindings (id ↔ function) are made at compile time inside a top-level `comptime { ... }` block. The hardware then dispatches events to the right function with no runtime overhead.

## Task ID types

Each task kind has its own ID type. They are *not* interchangeable.

```csl
const t_data:    data_task_id     = @get_data_task_id(color_or_queue);
const t_local:   local_task_id    = @get_local_task_id(N);     // N is a u16 slot
const t_control: control_task_id  = @get_control_task_id(N);   // N is a u16 (0..63)
```

### `@get_data_task_id` — WSE-2 vs WSE-3

The triggering source differs by architecture, and this drives most of the WSE-2/WSE-3 conditional code you'll see in real kernels:

```csl
// Inputs
const rx_color: color       = @get_color(12);              // (WSE-2)
const rx_iq:    input_queue = @get_input_queue(2);         // (WSE-3)

// Build the data_task_id from whichever the arch uses
const rx_task_id: data_task_id =
  if      (@is_arch("wse2")) @get_data_task_id(rx_color)
  else if (@is_arch("wse3")) @get_data_task_id(rx_iq);
```

On WSE-2 colors range 0..23 (24 colors) and the data-task ID equals the color number. On WSE-3 input queues range 0..7 and the data-task ID equals the queue number; the queue must additionally be associated with the relevant color via `@initialize_queue`.

### `@get_local_task_id(N)`

`N` is a `u16` slot in the shared local-task table. Available slots differ by arch:

| Arch | Available local task IDs |
|---|---|
| WSE-2 | 0..30 (avoid 29, 30 — teardown / timer) |
| WSE-3 | 8..30 (avoid 29, 30 — teardown / timer) |

### `@get_control_task_id(N)`

`N` is a `u16` in 0..63, on both WSE-2 and WSE-3. The same `N` is what a sender places in the control wavelet's id field.

## Binding: `@bind_*_task`

Inside `comptime { ... }`:

```csl
comptime {
  @bind_data_task(rx_task, rx_task_id);
  @bind_local_task(main_task, main_task_id);
  @bind_control_task(send_result, send_result_task_id);
}
```

A task ID can be bound at most once. Binding the same ID twice is a compile error.

## Activation, blocking, unblocking

```csl
@activate(local_task_id);    // schedule the local task to run (idempotent — already-pending stays pending once)
@block(task_id);             // mark task as blocked; events will queue but not fire the body
@unblock(task_id);           // clear the block; queued events can now fire
```

Tasks are **initially unblocked**. The hardware dispatches a task body when *all three* are true:
1. its triggering event has occurred (wavelet arrived / `@activate` called / control wavelet matched), and
2. the task ID is unblocked, and
3. (control tasks only) the receiving channel has been unblocked via `@unblock(color)` — *unless* a data task is also bound to that channel, in which case the channel is already unblocked.

`@block`/`@unblock` are useful for serialization: stop a data task from firing again until the previous invocation's async fabric send finishes — see the FIFO pattern below.

## DSD completion hooks: `.activate` / `.unblock`

Async DSD operations can hand the baton off to a task on completion, fusing the "I finished" signal into the same hardware event the next task is waiting for:

```csl
// When the async copy finishes, fire `next` as a local task
@mov16(dst, src, .{ .async = true, .activate = next });

// When the async send finishes, unblock `me` so the next data wavelet can fire it again
@fmovs(out, src, .{ .async = true, .unblock = me });
```

This is the *idiomatic* way to chain pipeline stages. Polling completion from inside a task wastes cycles; `.activate`/`.unblock` lets the scheduler do the wakeup for you.

## WSE-3 queue initialization

On WSE-3 every input/output queue you use must be explicitly bound to the color it carries:

```csl
comptime {
  if (@is_arch("wse3")) {
    @initialize_queue(rx_iq, .{ .color = rx_color });
  }
}
```

For output queues that connect to memcpy:

```csl
@initialize_queue(d2h_oq, .{ .color = @get_color(@bitcast(u16, sys_mod.MEMCPYD2H_1)) });
```

WSE-2 derives queue↔color binding from the color stored in the `fabin_dsd` / `fabout_dsd`, so no separate `@initialize_queue` call is needed there.

## Reserved task IDs (do not bind!)

The memcpy infrastructure and the runtime reserve several slots. Conflicting bindings *compile* but produce silent runtime breakage.

### WSE-2

- **Data tasks (colors)**: IDs 21, 22, 23, 27, 28, 30 reserved by memcpy. IDs 29, 31 reserved by runtime. Colors 24, 25, 26 are not routable but can be used for system purposes.
- **Local tasks**: IDs 29 (teardown) and 30 (timer) reserved.
- **Free range for user data tasks**: colors 0–20 and 24–26 (24–26 routable only via the special non-fabric path).

### WSE-3

- **Data tasks (input queues)**: queues 0 and 1 reserved by memcpy. Queues 2–7 free.
- **Local tasks**: IDs 0–7 reserved (data-task space). IDs 21–23, 27–28, 30 reserved by memcpy. IDs 29, 31 reserved by runtime. **Free range: 8–20, 24–26, 32+**.
- **Control tasks**: 0..63 on both arches; runtime does not reserve a fixed range, but adopt a convention (e.g., high IDs for sentinels) to avoid collisions across modules.

The bundled tutorials' header comments contain authoritative reservation maps for the local-task ID table; check `topic-05-sentinels/pe_program.csl` lines 1–28 for the current canonical version when in doubt.

## Patterns

### Pattern 1 — Receive wavelets into a buffer (data task, WSE-2/3 portable)

From `topic-06-switches/recv.csl`:

```csl
param memcpy_params;
param rx_color: color;

const rx_iq: input_queue = @get_input_queue(2);
const rx_task_id: data_task_id =
  if      (@is_arch("wse2")) @get_data_task_id(rx_color)
  else if (@is_arch("wse3")) @get_data_task_id(rx_iq);

var result = @zeros([1]u32);

task rx_task(data: u32) void {
  result[0] = data;
}

comptime {
  @bind_data_task(rx_task, rx_task_id);
  if (@is_arch("wse3")) @initialize_queue(rx_iq, .{ .color = rx_color });
}
```

### Pattern 2 — Local task as entry point

A common idiom: `comptime { @activate(main_task_id); }` schedules a local task to run once at startup; the body kicks off the real work.

```csl
const main_task_id: local_task_id = @get_local_task_id(8);

task main_task() void {
  // do initial setup, kick off pipelines, etc.
}

comptime {
  @bind_local_task(main_task, main_task_id);
  @activate(main_task_id);
}
```

### Pattern 3 — Self-throttling data task (block until async send completes)

From `topic-09-fifos/buffer.csl`. The data task receives a wavelet, kicks off an async send out to memcpy, **blocks itself** so a second incoming wavelet doesn't trample the in-flight send, and unblocks when the send completes:

```csl
const process_task_id: data_task_id =
  if (@is_arch("wse2")) @get_data_task_id(loopback_color)
  else                  @get_data_task_id(loopback_iq);

var elem = @zeros([1]f32);
const elem_dsd = @get_dsd(mem1d_dsd, .{ .tensor_access = |i|{1} -> elem[0] });

task process_task(element: f32) void {
  @block(process_task_id);                                  // halt further dispatch
  elem[0] = element * element * element;
  @fmovs(out_dsd, elem_dsd, .{
    .async = true,
    .unblock = process_task,                                // clear the block on completion
  });
}
```

### Pattern 4 — Control task for end-of-stream sentinels

From `topic-05-sentinels/pe_program.csl`. A control wavelet whose payload id matches `sentinel` fires `send_result`, which writes an accumulator to memcpy:

```csl
param sentinel: u16;
const send_result_task_id: control_task_id = @get_control_task_id(sentinel);

var result = @zeros([1]f32);
const result_dsd = @get_dsd(mem1d_dsd, .{ .tensor_access = |i|{1} -> result[i] });

task main_task(data: f32) void {            // data task: accumulate every wavelet
  result[0] += data;
}

task send_result() void {                   // control task: fires once on sentinel
  @fmovs(out_dsd, result_dsd, .{ .async = true });
}

comptime {
  @bind_data_task(main_task, main_task_id);
  @bind_control_task(send_result, send_result_task_id);
}
```

The sender side emits the control wavelet via `@get_dsd(fabout_dsd, .{ .extent = 1, .control = true, .fabric_color = ... })` — see [SKILL-DSDS.md](SKILL-DSDS.md) and [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)*.

### Pattern 5 — Pipelined FIFO with two activated tasks

From `topic-09-fifos/buffer.csl`. A local task drives two async ops in sequence: first fill a FIFO from a `fabin_dsd`, then drain the FIFO into a `fabout_dsd`. The scheduler interleaves them based on FIFO occupancy:

```csl
const main_task_id: local_task_id = @get_local_task_id(8);

var fifo_buffer = @zeros([1024]f32);
const fifo = @allocate_fifo(fifo_buffer);

task main_task() void {
  @fadds(fifo, in_dsd, ten_dsd, .{ .async = true });        // fabric -> FIFO
  @fnegs(loopback_dsd, fifo,    .{ .async = true });        // FIFO -> fabric
}

comptime {
  @bind_local_task(main_task, main_task_id);
  @activate(main_task_id);
}
```

## Multi-task dispatch / WSE-3 advanced

`@bind_rotating_tasks`, `@set_control_task_table`, `@set_empty_queue_handler` — these are advanced WSE-3 builtins for multi-binding and queue-edge handlers. See [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) *(planned)* once written. Brief mention here so you know the names exist when you grep the upstream docs:

- `@bind_rotating_tasks(task_list, ids)` — bind a set of tasks that rotate through ids in turn (WSE-3).
- `@set_control_task_table(table)` — install a runtime-mutable control-task table.
- `@set_empty_queue_handler(iq, task)` — fire `task` when input queue `iq` empties.

## Execution semantics

- **Run to completion.** A task body executes to its closing brace before the next task is dispatched. There is no preemption.
- **Tasks cannot return values.** They are `void`.
- **Multiple events for the same task queue up.** If a data task is blocked and three wavelets arrive, all three fire when it unblocks (one after another, each receiving its own payload).
- **`@activate` is idempotent in one direction.** Calling `@activate` while a local task is already pending doesn't queue an extra invocation — the task still fires exactly once. Use a counter variable if you want to count events.
- **Async DSD ops are themselves microthreads, not tasks.** They run concurrently with the task that launched them, but the task body finishes immediately after the launch. The op's completion is what fires `.activate` / `.unblock` follow-ups.

## Gotchas

- **`@bind_*_task` outside `comptime { }` is a compile error.** Same for `@activate` of a startup task.
- **Don't `@bind_data_task` to a reserved memcpy queue/color.** Compiles, then memcpy stops working.
- **WSE-3 forgets to `@initialize_queue` → no wavelets arrive.** The compile succeeds; the simulator silently never fires your data task. Always pair `@get_input_queue` with `@initialize_queue` under `if (@is_arch("wse3"))`.
- **A data task's argument is the **single** wavelet payload, decomposed.** A `task f(a: u16, b: u16) void` consumes one 32-bit wavelet and splits it. Don't expect two wavelets.
- **Don't manually `@unblock` a control-task channel that also has a data task bound** — it'll already be unblocked, and double-unblocking is undefined.
- **Local-task ID 29 and 30 are reserved on both arches** (teardown / timer). The compiler does not always warn about this.
- **A blocked task ID accumulates events.** If you `@block` and never `@unblock`, those wavelets sit in the input queue forever and eventually fill it (queue-full handler fires on WSE-3, deadlock on WSE-2).
- **Activating a local task that hasn't been bound is a runtime no-op, not a compile error.** Spelling-error your `@bind_local_task` line and you'll get silent inaction; the only sign is that your kernel never makes progress.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry-point.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `.async`, `.activate`, `.unblock` op options; FIFO DSDs.
- [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) *(planned)* — WSE-3 explicit microthread IDs, rotating tasks, queue-empty handlers.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)* — control wavelets, switch tables, control_task_id senders.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) *(planned)* — memcpy's reserved task IDs/queues and how to coexist.
- Tutorials grounded in real task usage: bundled `topic-05-sentinels`, `topic-06-switches`, `topic-07-switches-entrypt`, `topic-09-fifos`, and the gemv-09-streaming benchmark.
- Upstream docs: <https://sdk.cerebras.net/csl/language/task-ids>
