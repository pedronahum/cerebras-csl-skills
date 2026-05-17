---
name: csl-libraries
description: Survey of CSL's bundled standard library — every angle-bracket-importable module that ships inside the SDK SIF. Covers complex, control, data_utils, debug, directions, dsd_ops, empty, layout, malloc, math, random, simprint, string, tile_config (and its submodules color_config / control_transform / exceptions / filters / input_queue_status / main_thread_priority / output_queue_status / switch_config / task_priority / teardown), time, timer, types, kernels (FFT, tally, collectives), collectives_2d, plus the WSE-3-only message_passing library. For each library: purpose, the key types/functions/constants it exposes, and an idiomatic call.
---

# CSL Standard Libraries

Every library is imported via the angle-bracket form:

```csl
const lib = @import_module("<library_name>");
const cfg = @import_module("<library_name>", .{ /* params */ });
```

These libraries live inside the SDK SIF — they're not on the host filesystem and cannot be edited. To override their behaviour, wrap them in a user module that re-exposes the parts you want.

This file is a survey: purpose, exports, a one-line idiomatic use. For semantics of the underlying builtins each library wraps, see [SKILL-BUILTINS.md](SKILL-BUILTINS.md).

## Quick index

| Library | One-line |
|---|---|
| [`<complex>`](#complex) | Complex-number type and arithmetic. |
| [`<control>`](#control) | Encode control wavelets (control-task activation, switch advance/reset, teardown). |
| [`<data_utils>`](#data_utils) | `lo16` / `hi16` / `lo32` / `hi32` bit extraction. |
| [`<debug>`](#debug) | Tag-based value tracing into a host-readable buffer. |
| [`<directions>`](#directions) | Compass-direction utilities (rotate, flip). |
| [`<dsd_ops>`](#dsd_ops) | Type-aware wrappers over `@mov`, `@add`, `@fmac`, etc. |
| [`<empty>`](#empty) | Placeholder for conditional imports. |
| [`<layout>`](#layout) | Runtime PE coordinates `get_x_coord()` / `get_y_coord()`. |
| [`<malloc>`](#malloc) | Arena allocator over a static buffer. |
| [`<math>`](#math) | Math constants, predicates, transcendentals (runtime only). |
| [`<random>`](#random) | PRNG with uniform and normal distributions. |
| [`<simprint>`](#simprint) | `printf`-style printing into the simulator log. |
| [`<string>`](#string) | Comptime string formatting (`fmt("foo_{d}", .{i})`). |
| [`<tile_config>`](#tile_config) | Hardware-register access; submodules for color, exception, filter, queue-status, priority, switch, teardown configuration. |
| [`<time>`](#time) | Hardware timestamp counter (48-bit). |
| [`<timer>`](#timer) | Multi-timer with elapsed-time. |
| [`<types>`](#types) | Comptime type introspection predicates. |
| [`<kernels/fft/...>`](#kernels-fft) | 3D FFT kernel across a rectangle. |
| [`<kernels/tally/...>`](#kernels-tally) | Two-phase tally for multi-PE progress coordination. |
| [`<collectives_2d/...>`](#collectives_2d) | MPI-like collectives: broadcast, scatter, gather, reduce. |
| [`<message_passing>`](#message_passing) (WSE-3) | Message-passing primitives. |

## `<complex>` <a id="complex"></a>

Complex-number type generic over its real-field type, plus pre-instantiated f16/f32 versions and standard arithmetic.

```csl
const cmp = @import_module("<complex>");
var c1 = cmp.get_complex_32(1.0, 2.0);             // 1+2i (f32)
var c2 = cmp.add_complex(c1, c1);                  // 2+4i
var c3 = cmp.multiply_complex(c1, c1);             // -3+4i
```

Key exports: `complex(comptime T: type) type`, `complex_32`, `complex_64`, `get_complex`, `add_complex`, `subtract_complex`, `multiply_complex`.

## `<control>` <a id="control"></a>

Helpers to construct control-wavelet *payloads* for a `fabout_dsd` with `.control = true`. Use when you need to trigger control tasks on a downstream PE or flip routing switches.

```csl
const ctrl = @import_module("<control>");
const wlt = ctrl.encode_control_task_payload(target_task_id);
@mov32(out_ctrl_dsd, ...);
```

Key exports: `MAX_CMDS = 8`, `opcode` enum (`NOP`, `SWITCH_ADV`, `SWITCH_RST`, `TEARDOWN`), `encode_control_task_payload`, `encode_single_payload`, `encode_payload` (multi-cmd).

## `<data_utils>` <a id="data_utils"></a>

Tiny helpers for splitting wide integers into halves.

```csl
const du = @import_module("<data_utils>");
const lo: u16 = du.lo16(@as(u32, 0xdeadbeef));   // 0xbeef
const hi: u16 = du.hi16(@as(u32, 0xdeadbeef));   // 0xdead
```

Exports: `lo16`, `hi16`, `lo32`, `hi32`.

## `<debug>` <a id="debug"></a>

Captures values into an in-PE ring buffer that the host can dump after a run. Useful when `<simprint>` is too noisy or the program runs on real hardware.

```csl
const trace = @import_module("<debug>", .{
  .key = "session1",
  .buffer_size = 128,
});

trace.trace_timestamp();
trace.trace_i16(my_value);
trace.trace_string("checkpoint A");
```

Exports: `trace_bool`, `trace_u8`/`u16`/`u32`, `trace_i8`/`i16`/`i32`, `trace_f16`/`f32`, `trace_string(comptime s)`, `trace(x)` (generic), `trace_timestamp()`.

## `<directions>` <a id="directions"></a>

Manipulate `direction`-typed values (NORTH/SOUTH/EAST/WEST). Useful in route declarations and any per-PE code that adapts to the PE's neighbourhood.

```csl
const dirs = @import_module("<directions>");
const next = dirs.rotate_clockwise(my_dir);
```

Exports: `rotate_clockwise`, `rotate_counterclockwise`, `flip_vertical`, `flip_horizontal`, `flip`.

## `<dsd_ops>` <a id="dsd_ops"></a>

Type-aware wrappers around the raw `@mov`/`@add`/`@fmac` family. Resolves the right width/precision builtin based on a `comptime T: type` argument.

```csl
const ops = @import_module("<dsd_ops>");
ops.mov(f32, dst_dsd, src_dsd, .{});
ops.fmac(f32, acc_dsd, a_dsd, b_dsd, .{ .async = true });
```

Exports: `mov`, `convert`, `add`, `sub`, `mul`, `fmac`, `neg`, `abs`, `norm`, `scale`, `max`.

When to use: writing generic kernels parameterized by element type. When the type is fixed (`f32` only), the raw `@fmacs` etc. are equally clear and one indirection shorter.

## `<empty>` <a id="empty"></a>

A library that does nothing. Used as a conditional-import placeholder so the import statement always parses but optionally compiles to no code:

```csl
const optional = @import_module(
  if (use_feature) "./feature.csl" else "<empty>"
);
```

## `<layout>` <a id="layout"></a>

Runtime accessors for the PE's own grid coordinates within the rectangle.

```csl
const layout_mod = @import_module("<layout>");
const x = layout_mod.get_x_coord();
const y = layout_mod.get_y_coord();
```

Exports: `get_x_coord() u16`, `get_y_coord() u16`.

Used in code that needs to specialize per-PE behaviour without compile-time parameterization (e.g., "right-edge PE outputs to host, others forward east").

## `<malloc>` <a id="malloc"></a>

Arena allocator over a parameter-sized buffer. No `free` per allocation — only `free()` of the whole arena.

```csl
const mem = @import_module("<malloc>", .{ .buffer_num_words = 1024 });
var p: *f32 = mem.malloc(f32, 16);          // 16 contiguous f32s
if (!mem.has_enough_space(f32, 32)) { /* handle */ }
mem.free();                                  // reset arena
```

Exports: `malloc(comptime T, num_values)`, `malloc_i16`/`f32`/etc., `has_enough_space`, `free`.

## `<math>` <a id="math"></a>

Constants, predicates, and transcendentals.

```csl
const math = @import_module("<math>");
const r = math.sqrt(dx*dx + dy*dy);          // runtime
if (math.isFinite(r)) { /* ... */ }
const two_pi = 2.0 * math.PI;
```

Exports:

- **Constants:** `PI`, `E`.
- **Predicates / sign:** `abs`, `max`, `min`, `sign`.
- **FP queries:** `ceil`, `floor`, `isNaN`, `isInf`, `isFinite`.
- **Transcendentals (runtime only):** `sin`, `cos`, `exp`, `log`, `pow`, `sqrt`. Type-suffixed variants `_f16`/`_f32` available for non-generic use.

The transcendentals don't run at comptime — pre-compute constants the obvious way (`const sqrt_2: f32 = 1.41421356;`) if you need the value at compile time.

## `<random>` <a id="random"></a>

Higher-level PRNG than the raw `@random16` builtin.

```csl
const rng = @import_module("<random>");
rng.set_global_prng_seed(42);
const u = rng.random_f32(0.0, 1.0);           // uniform
const g = rng.random_normal_f32();             // Box-Muller Gaussian
```

Exports: `set_global_prng_seed`, `random_f16`/`random_f32` (uniform), `random_pow_u32(pow)` (uniform in `[0, 2^pow)`), `random_normal_f32`.

## `<simprint>` <a id="simprint"></a>

Print to the simulator log. Only meaningful in simulation (real-hardware runs ignore these calls or convert them to no-ops, depending on build config). The compile log line `[INFO] Using SIF: ...` doesn't include simprint output — look in `sim.log`.

```csl
const sp = @import_module("<simprint>");
sp.print_string("starting\n");
sp.fmt("M={d} N={d} dt={f}\n", .{ M, N, dt });
sp.fmt_with_coords("checkpoint at ({d},{d})\n", .{});
```

Format specifiers: `{d}` decimal, `{X}` hex, `{b}` binary, `{f}` float. Param `.enable = false` disables all output at compile time (good for debug/release toggles).

Exports: `print_string`, `print_u16_decimal`/`hex`/`binary`, `print_f16`, `print_f32`, `fmt`, `fmt_with_coords`.

## `<string>` <a id="string"></a>

Compile-time string helpers — primarily formatting.

```csl
const str = @import_module("<string>");
const tag = str.fmt("tile_{d}", .{ 5 });   // → "tile_5", a comptime_string
```

Exports: `comptime_int_to_string`, `fmt(comptime fstr, args)`.

Use this when generating unique symbol names per PE (`@export_symbol(ptr, str.fmt("channel_{d}", .{x}))`) or building diagnostic strings at compile time.

## `<tile_config>` <a id="tile_config"></a>

Comprehensive hardware-register access. Don't use the raw `@get_config` / `@set_config` builtins when this library has a typed wrapper.

```csl
const tcfg = @import_module("<tile_config>");
tcfg.task_priority.set_task_priority(my_task_id);
tcfg.filters.set_counter(filter_id, initial_value);
const status = tcfg.input_queue_status.get();
```

### Submodules

| Submodule | Purpose |
|---|---|
| `color_config` | Per-color routing & I/O direction (`set_io_direction`, `toggle_io_direction`, `clear_io_direction`, `reset_routes`). |
| `control_transform` | XOR mask for control-wavelet indices (`set_mask`). |
| `exceptions` | FP/SW exception unmasking. Constants: `FP_DIV_BY_0`, `FP_OVERFLOW`, `FP_UNDERFLOW`, `SW_EXCEPTION`. Fn: `set_exception_mask`. |
| `filters` | Counter-filter configuration: `set_counter`, `set_max_counter`, `set_active_limit`. WSE-3 adds `set_counter_and_state`, `get_counter_value`, `set_state`. |
| `input_queue_status` | Inspect queue fill: `get()` → `{ empty, full }` bitmasks; `is_full`, `is_empty`, `all_full`, `all_empty`. |
| `main_thread_priority` | `level` enum (`MEDIUM_LOW`, `MEDIUM`, `MEDIUM_HIGH`, `HIGH`); `update_main_thread_priority(level)`. |
| `output_queue_status` | Same API as `input_queue_status`. |
| `switch_config` | Pop mode, switch position, RX/TX. Enums: `pop_mode`, `switch_status`, `switch_pos`, `switch_select`. Fns: `set_pop_mode`, `clear_current_position`, `set_switch_pos`, `set_rxtx_switch_pos` (WSE-3+), `set_current_switch_position`. |
| `task_priority` | Per-task priority: `level` enum (`LOW`, `HIGH`); `update_task_priority`, `set_task_priority`, `clear_task_priority`. |
| `teardown` | `get_task_id()` (reserved teardown task id), `get_pending()`, `is_pending`, `exit`. |

Top-level exports: `addresses`, `reg_type`, `target_name`, `word_size`, `FIFO_MIN_ALIGNMENT`, `get_fabric_coord(dimension)`.

This library is the closest thing CSL has to assembly: configuring hardware features that have no language-level expression. Reach for it when standard DSD/task patterns don't cover what you need.

## `<time>` <a id="time"></a>

Hardware 48-bit timestamp counter, exposed as a `[3]u16` triple. Use for cycle-accurate measurement in simulator and real-hardware runs.

```csl
const time = @import_module("<time>");
var t0: [3]u16 = undefined;
var t1: [3]u16 = undefined;
time.enable_tsc();
time.get_timestamp(&t0);
// ... work ...
time.get_timestamp(&t1);
// Difference computed host-side via cerebras.sdk.sdk_utils.calculate_cycles
```

Exports: `enable_tsc`, `disable_tsc`, `get_timestamp(result: *[3]u16)`, `reset_tsc_counter`, `get_perf_cntr(result, id)` (HW counters 0/1).

## `<timer>` <a id="timer"></a>

Multiple software timers riding on top of the timestamp counter, with elapsed-time helpers.

```csl
const timer = @import_module("<timer>", .{ .timerCount = 4 });
var elapsed: timer.timerType = undefined;
timer.start(0);
// ... work ...
timer.stop(0);
timer.elapsed(0, &elapsed);
```

Exports: `timerType = [3]u16`, `start(timerId)`, `stop(timerId)`, `elapsed(timerId, result)`. Param `.timerCount` controls how many concurrent timers.

## `<types>` <a id="types"></a>

Comptime type introspection.

```csl
const types = @import_module("<types>");
@comptime_assert(types.is_numeric(T));
const bytes = types.byte_size_of(MyStruct);
```

Exports:

- **Predicates:** `is_unsigned_int`, `is_signed_int`, `is_float16`, `is_float`, `is_enabled_float` (current `--fp16-format`), `is_signed`, `is_numeric`, `is_dsd`, `is_dsr`, `has_dsd_type`, `has_dsr_type`.
- **Size / align:** `word_size_of`, `byte_size_of`, `bit_size_of`, `min_byte_align_of`, `min_word_align_of`, `bits_type_of`.

## `<kernels/fft/...>` <a id="kernels-fft"></a>

Pre-built 3D FFT kernel that handles its own layout, routing, and inter-PE communication. Imported into your top-level `layout.csl` like any other module — it then drops itself into a rectangular region you specify.

```csl
const fft = @import_module("<kernels/fft/fft3d_layout>");
layout {
  fft.FFT_kernel(/* x0 */ 0, /* y0 */ 0, /* width */ 8, /* N */ 64, f32);
}
```

Best used as a known-good reference for "how to package a multi-PE kernel that an outside layout can drop in".

## `<kernels/tally/...>` <a id="kernels-tally"></a>

Two-phase tally for "have all N PEs reached this point yet?" coordination. Layout-side params: `kernel_height`, `kernel_width`, `phase2_tally`, `colors`, `output_color`. PE-side params: `tally_params`, `input_queues`, `output_queues`. PE-side `fn signal_completion()` is what you call once your work is done.

```csl
// PE side
const tally = @import_module("<kernels/tally/pe>", tally_params);
// ... work ...
tally.signal_completion();
```

## `<collectives_2d/...>` <a id="collectives_2d"></a>

MPI-flavoured collectives over a 2D PE grid. Two halves — layout module sets up routes/colors; PE module provides the runtime ops.

Layout params: `x_colors`, `x_entrypoints`, `y_colors`, `y_entrypoints`.
PE params: `dim_params`, `queues`, `dest_dsr_ids`, `src0_dsr_ids`, `src1_dsr_ids`.

```csl
const coll = @import_module("<collectives_2d/pe>", coll_params);

fn work() void {
  coll.init();
  coll.broadcast(/* root */ 0, &buf, count, on_done);
  // coll.scatter, coll.gather, coll.reduce_fadds, ...
}
```

PE-side exports: `init`, `broadcast(root, buf, count, cb)`, `scatter(root, send_buf, recv_buf, count, cb)`, `gather(root, send_buf, recv_buf, count, cb)`, `reduce_fadds(root, send_buf, recv_buf, count, cb)`. The `cb` is a task to fire when the collective completes — usually the next-stage local task.

## `<message_passing>` (WSE-3 only) <a id="message_passing"></a>

WSE-3 message-passing primitives. The PE-to-PE channel API is richer than what's available on WSE-2 via fabric colors alone. See the upstream docs for the per-builtin reference once you're targeting WSE-3 message passing — at minimum the library exposes send/receive primitives over named channels.

```csl
// Gate with @is_arch — building this on WSE-2 won't parse
const mp = if (@is_arch("wse3")) @import_module("<message_passing>") else null;
```

## Combining libraries — common stacks

| Goal | Imports |
|---|---|
| Plain compute + host I/O | `<memcpy/get_params>` + `<memcpy/memcpy>`. |
| Per-PE specialisation | + `<layout>` (`get_x_coord` / `get_y_coord`). |
| Debug printing | + `<simprint>` (sim only) or `<debug>` (sim + real). |
| Cycle measurements | + `<time>` and `<timer>`. |
| Generic kernels over types | + `<types>` (introspection) and `<dsd_ops>` (typed ops). |
| Multi-PE collective | + `<collectives_2d/...>` (rather than rolling your own routes). |
| Random init | + `<random>`. |
| Hardware-feature tweaking | + `<tile_config>` and submodules. |

## Gotchas

- **Math transcendentals are runtime-only.** `comptime math.sqrt(2.0)` is a compile error; precompute as a `const f32 = 1.41421356;`.
- **`<simprint>` output only appears in simulation.** On real hardware, the print is at best a no-op. Don't rely on it as a logging mechanism for production.
- **`<malloc>`'s arena cannot free individual allocations.** Plan your malloc/free as a phased lifecycle (build a working set, use it, free the whole arena).
- **`<debug>` requires a `.key`** (and consistent `.buffer_size` across importers) for the host to find the buffer to dump.
- **`<message_passing>` is WSE-3 only.** Guard with `@is_arch("wse3")`.
- **`<tile_config>` submodules are accessed as fields** of the imported module: `cfg.task_priority.set_task_priority(...)`. They're not individually importable.
- **`<empty>` doesn't accept parameters** — passing a params struct is an error.
- **Library angle-bracket names are immutable.** No `CSL_IMPORT_PATH` override possible; if you need a different impl, wrap in a user module.
- **Each `@import_module("<lib>", .{params})` call gives a fresh module value.** Two imports of `<malloc>` with the same `.buffer_num_words` are *different* arenas. Import once at the top of the file and reuse.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry.
- [SKILL-MODULES.md](SKILL-MODULES.md) — the `@import_module` semantics these libraries plug into.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md) — the raw builtins that some libraries (`<dsd_ops>`, `<tile_config>`) wrap.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `<dsd_ops>` lifts DSD-op builtins.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — the `<memcpy/*>` libraries that connect PE code to host scripts.
- [SKILL-TASKS.md](SKILL-TASKS.md) — `<control>` for emitting control-wavelet payloads to trigger control tasks.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)* — `<directions>` and the routing primitives `<tile_config>.color_config` configures.
- Upstream docs: <https://sdk.cerebras.net/csl/language/libraries>
