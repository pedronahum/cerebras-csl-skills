---
name: csl-builtins
description: Reference catalogue of every CSL builtin (@-prefixed function). Organised by category — type & comptime, comptime utilities, strings, array introspection, struct, DSD construction & mutation, DSD ops (integer/bitwise/shift/popcnt and the full f16/f32 arithmetic family), task & event management, task ID creation, colors & queues, configuration & layout (@set_rectangle / @set_tile_code / @set_color_config / @get_config), random, ranges, generics, higher-order (@map), RPC / symbol exports, and the WSE-3-only set (@get_ut_id, @queue_flush, @set_control_task_table, @set_empty_queue_handler, @bind_rotating_tasks). For builtins with their own deep-dive skill (DSDs, tasks, comptime, modules), this file lists the one-liner; follow the cross-reference for the full treatment.
---

# CSL Builtins — Reference Catalogue

Every CSL builtin is `@`-prefixed and resolved at compile time. This file is the *catalogue*; the dense semantics for the major builtin families live in dedicated skills:

| Family | Deep dive |
|---|---|
| DSDs (`@get_dsd`, `@set_dsd_*`, `@increment_dsd_offset`, `@allocate_fifo`, ...) | [SKILL-DSDS.md](SKILL-DSDS.md) |
| Tasks (`@bind_*_task`, `@get_*_task_id`, `@activate`, `@block`, `@unblock`) | [SKILL-TASKS.md](SKILL-TASKS.md) |
| Comptime (`@comptime_assert`, `@comptime_print`, `@is_comptime`) | [SKILL-COMPTIME.md](SKILL-COMPTIME.md) |
| Modules (`@import_module`) | [SKILL-MODULES.md](SKILL-MODULES.md) |
| Symbol exports (`@export_name`, `@export_symbol`) | [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) |

Use this file when you want the one-line reference for a specific builtin or need to discover what's available in a category. Signatures use `T` for arbitrary types, `dsd` for any DSD value, `numeric` for any numeric type.

## Type & comptime

| Builtin | Signature | Purpose |
|---|---|---|
| `@as` | `@as(T, value)` → `T` | Coerce value to the named type. Compile error if narrowing/unsafe. |
| `@bitcast` | `@bitcast(T, value)` → `T` | Reinterpret the same bits as a different (same-size) type. |
| `@ptrcast` | `@ptrcast(*T, ptr)` → `*T` | Cast a pointer to a different pointee type. |
| `@type_of` | `@type_of(value)` → `type` | The compile-time type of an expression. Common in generic signatures: `fn(x: anytype, y: @type_of(x)) ...`. |
| `@is_same_type` | `@is_same_type(T1, T2)` → `bool` | Equality on types. |
| `@is_comptime` | `@is_comptime(expr)` → `bool` | True if `expr` is comptime-known. |
| `@is_arch` | `@is_arch("wse2")` / `@is_arch("wse3")` → `bool` | Comptime arch check; the standard branch-by-arch idiom. |
| `@fp16` | `@fp16()` → `type` | The selected runtime FP16 format (f16, cb16, or bf16, controlled by `--fp16-format`). |

```csl
const T: type = if (@is_arch("wse3")) f32 else f16;
const v = @as(f32, @bitcast(u32, raw));
```

## Comptime utilities

| Builtin | Signature | Purpose |
|---|---|---|
| `@comptime_assert` | `@comptime_assert(cond)` | Fail compilation if `cond` is false. |
| `@comptime_assert` | `@comptime_assert(cond, "msg")` | …with a custom message. |
| `@comptime_print` | `@comptime_print(v1, v2, ...)` | Print to the compile log. Invaluable for debugging comptime logic. |
| `@assert` | `@assert(cond)` | Runtime assert. In simulation: aborts. On real hardware: behaviour depends on build config. |

```csl
comptime @comptime_assert(M > 0 and M % 4 == 0, "M must be a positive multiple of 4");
comptime @comptime_print(M, N, M*N);
```

## Strings

| Builtin | Signature | Purpose |
|---|---|---|
| `@strlen` | `@strlen(comptime_string)` → `u32` | Byte length; counts embedded NULs. |
| `@strcat` | `@strcat(s1, s2, ...)` → `comptime_string` | Concatenate strings at compile time. |
| `@get_array` | `@get_array(comptime_string)` → `[N]u8` | String to byte array (runtime-readable). |
| `@get_string_from_byte` | `@get_string_from_byte(b: u8)` → `comptime_string` | Single byte to string. |

```csl
const name = @strcat("channel_", @as_string(idx));
const bytes: [@strlen("hello")]u8 = @get_array("hello");
```

## Array introspection

| Builtin | Signature | Purpose |
|---|---|---|
| `@dimensions` | `@dimensions(array_type)` → tuple | Sizes of all dimensions. |
| `@element_count` | `@element_count(array_type)` → `u32` | Total count. |
| `@element_type` | `@element_type(array_type)` → `type` | Base element type. |
| `@rank` | `@rank(array_type)` → `u16` | Number of dimensions. |
| `@constants` | `@constants(array_type, value)` → array | Array filled with `value`. |
| `@zeros` | `@zeros(array_type)` → array | Array filled with `0`. |
| `@range` | `@range(T, end)` / `@range(T, start, end)` / `@range(T, start, step, end)` | Iterable used in `for` loops. |
| `@range_start` / `@range_stop` / `@range_step` | unary on a range value | Extract a range's fields. |

```csl
const M = @element_count([M*N]f32);   // M*N at comptime
var y = @zeros([M]f32);
var x = @constants([N]f32, 1.0);
for (@range(i16, M)) |i| { /* ... */ }
```

## Struct introspection

| Builtin | Signature | Purpose |
|---|---|---|
| `@field` | `@field(s, "name")` → value | Access field by string name (handy in generic code). |
| `@has_field` | `@has_field(s_or_T, "name")` → `bool` | Existence check. |

## DSD construction & mutation

See [SKILL-DSDS.md](SKILL-DSDS.md) for full semantics.

| Builtin | One-line |
|---|---|
| `@get_dsd(kind, .{...})` | Build a DSD. `kind` ∈ `mem1d_dsd`, `mem4d_dsd`, `circbuf_dsd`, `fabin_dsd`, `fabout_dsd`. |
| `@allocate_fifo(buffer, opts?)` | Allocate an on-chip FIFO. |
| `@get_dsr(dsr_type)` | Allocate a DSR/XDSR. See [SKILL-DSRS.md](SKILL-DSRS.md) *(planned)*. |
| `@load_to_dsr(dsr, dsd)` | Load a DSD into a DSR. |
| `@set_dsd_base_addr(dsd, ptr_or_array)` | New base address. |
| `@set_dsd_length(dsd, u16)` | New element/wavelet count. (`mem4d_dsd` excluded.) |
| `@set_dsd_stride(dsd, i8)` | New stride. (`mem1d_dsd` only.) |
| `@increment_dsd_offset(dsd, offset, elem_type)` | Shift base by N elements of `elem_type`. |
| `@set_fifo_read_length(fifo, u16)` | Pre-pop FIFO read count. |
| `@set_fifo_write_length(fifo, u16)` | Pre-push FIFO write count. |

## DSD operations — integer & bitwise

All ops take DSD operands; element-count must match. Suffix denotes width.

### 16-bit
| Builtin | Form | Purpose |
|---|---|---|
| `@mov16` | `(dst, src)` | Move. |
| `@add16` | `(dst, a, b)` | Add. |
| `@sub16` | `(dst, a, b)` | Subtract. |
| `@mul16` | `(dst, a, b)` | Multiply (low 16 bits). |
| `@and16` | `(dst, a, b)` | Bitwise AND. |
| `@or16` | `(dst, a, b)` | Bitwise OR. |
| `@xor16` | `(dst, a, b)` | Bitwise XOR. |
| `@sll16` | `(dst, src, shift)` | Left shift. |
| `@slr16` | `(dst, src, shift)` | Logical right shift. |
| `@sar16` | `(dst, src, shift)` | Arithmetic right shift. |

### 32-bit
| Builtin | Form |
|---|---|
| `@mov32` | `(dst, src)` |
| `@add32` | `(dst, a, b)` |
| `@sub32` | `(dst, a, b)` |

### Bit-counting
| Builtin | Form | Purpose |
|---|---|---|
| `@popcnt` | `(dst, src)` | Population count. |
| `@clz` | `(dst, src)` | Count leading zeros. |
| `@ctz` | `(dst, src)` | Count trailing zeros. |

## DSD operations — floating point

### f16 (suffix `h`)
| Builtin | Form | Purpose |
|---|---|---|
| `@fmovh` | `(dst, src)` | Move. |
| `@faddh` | `(dst, a, b)` | Add. |
| `@fsubh` | `(dst, a, b)` | Subtract. |
| `@fmulh` | `(dst, a, b)` | Multiply. |
| `@fmach` | `(dst_acc, a, b)` | Fused multiply-add: `dst += a*b`. |
| `@fnegh` | `(dst, src)` | Negate. |
| `@fabsh` | `(dst, src)` | Absolute value. |
| `@fmaxh` | `(dst, a, b)` | Max. |
| `@fscaleh` | `(dst, src, exp)` | `src * 2^exp`. |
| `@fnormh` | `(dst, src)` | Normalize. |

### f32 (suffix `s`)
| Builtin | Form |
|---|---|
| `@fmovs` | `(dst, src)` |
| `@fadds` | `(dst, a, b)` |
| `@fsubs` | `(dst, a, b)` |
| `@fmuls` | `(dst, a, b)` |
| `@fmacs` | `(dst, a, b)` (`dst += a*b`) |
| `@fnegs` | `(dst, src)` |
| `@fabss` | `(dst, src)` |
| `@fmaxs` | `(dst, a, b)` |
| `@fscales` | `(dst, src, exp)` |
| `@fnorms` | `(dst, src)` |

### Mixed precision
| Builtin | Form | Purpose |
|---|---|---|
| `@faddhs` | `(dst, a, b)` | Add f16 operands, write f32. |
| `@fmachs` | `(dst, a, b)` | FMA: accumulate f16*f16 into f32. |
| `@fh2s` | `(dst, src)` | f16 → f32 element-wise convert. |
| `@fs2h` | `(dst, src)` | f32 → f16. |
| `@fh2xp16` | `(dst, src)` | f16 → extended-precision. |
| `@fs2xp16` | `(dst, src)` | f32 → extended-precision. |
| `@xp162fh` | `(dst, src)` | Extended → f16. |
| `@xp162fs` | `(dst, src)` | Extended → f32. |

### Specialty
| Builtin | Form | Purpose |
|---|---|---|
| `@dfilt` | `(dsd, coeff_dsd)` | Digital filter (DSP primitive). |

All ops can take an options struct for `.async`, `.activate`, `.unblock`, `.on_control`, `.priority` (WSE-2). See [SKILL-DSDS.md](SKILL-DSDS.md).

## Tasks & events

See [SKILL-TASKS.md](SKILL-TASKS.md).

| Builtin | Form | Purpose |
|---|---|---|
| `@bind_data_task` | `(task, data_task_id)` | Bind task to wavelet trigger. |
| `@bind_local_task` | `(task, local_task_id)` | Bind task to `@activate`/DSD-completion trigger. |
| `@bind_control_task` | `(task, control_task_id)` | Bind task to control-wavelet trigger. |
| `@activate` | `(local_task_id)` | Schedule a local task. |
| `@block` | `(task_id)` | Block dispatch. |
| `@unblock` | `(task_id)` | Allow dispatch. |
| `@set_teardown_handler` | `(task)` | Register a function to run during teardown. |

## Task ID constructors

| Builtin | Form |
|---|---|
| `@get_local_task_id` | `(u16_slot)` |
| `@get_data_task_id` | `(color)` on WSE-2 / `(input_queue)` on WSE-3 |
| `@get_control_task_id` | `(u16)` 0..63 |

## Colors & queues

| Builtin | Form | Purpose |
|---|---|---|
| `@get_color` | `(u16)` → `color` | Construct a color from an id. |
| `@get_filter_id` | `(color)` → `u16` | Filter id associated with a color. |
| `@get_input_queue` | `(u16)` → `input_queue` | WSE-3 input queue id. |
| `@get_output_queue` | `(u16)` → `output_queue` | WSE-3 output queue id. |
| `@initialize_queue` | `(queue, .{ .color = c, ... })` | WSE-3: bind queue to color. Required before use. |

## Configuration & layout

Used inside `layout { ... }` blocks and `comptime { ... }` blocks.

| Builtin | Form | Purpose |
|---|---|---|
| `@set_rectangle` | `(width, height)` | Reserve the PE grid region for this kernel. Must appear in `layout {}`. |
| `@get_rectangle` | `()` → struct | Read back the grid info (from inside a PE program). |
| `@set_tile_code` | `(x, y, "file.csl", .{ params })` | Bind code + parameters to a specific PE coordinate. |
| `@set_color_config` | `(x, y, color, .{ config })` | Configure routing for a color on the named tile. |
| `@set_local_color_config` | `(color, .{ config })` | Same but on the calling PE. |
| `@get_config` / `@get_config_unchecked` | `(addr)` → word | Read a configuration register (`_unchecked` skips bounds checks). |
| `@set_config` / `@set_config_unchecked` | `(addr, value)` | Write a configuration register. |

```csl
layout {
  @set_rectangle(4, 1);
  for (@range(i16, 4)) |x| {
    @set_tile_code(x, 0, "pe_program.csl", .{ .memcpy_params = mc.get_params(x) });
  }
}
```

## Random numbers

| Builtin | Form | Purpose |
|---|---|---|
| `@random16` | `()` → `u16` | One 16-bit PRNG sample. |
| `@set_active_prng` | `(u8)` | Select which PRNG state to use (multiple state slots exist). |

## Higher-order operations

| Builtin | Form | Purpose |
|---|---|---|
| `@map` | `@map(fn, in_dsd_a, in_dsd_b, ..., out_dsd)` | Apply `fn` element-wise across DSDs. |

`@map` is the polymorphic alternative to writing `@fadds`/`@fmuls` chains by hand — useful when the operation is a user function rather than one of the built-in vector ops.

## Symbol exports & RPC

See [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md).

| Builtin | Form | Purpose |
|---|---|---|
| `@export_name` | `("name", type, mutability)` | In `layout {}`: declare a host-visible symbol. |
| `@export_symbol` | `(value, "name")` / `(fn)` | In `comptime {}`: bind a PE variable/function to the declared name. |
| `@get_symbol_id` | `("name")` → `u32` | Numeric id of an exported symbol. |
| `@get_symbol_value` | `("name")` → value | Pull back an exported value (rare; usually for cross-module reach). |
| `@get_tensor_ptr` | `("name")` → pointer | Pointer to an exported tensor. |
| `@has_exported_tensors` | `()` → `bool` | Reflection. |
| `@get_xdsr` | `()` → `xdsr` | Extended DSR for RPC operations. |
| `@rpc` | `(id, args...)` → result | Invoke a registered RPC. |
| `@export` | `(ptr, .{ ... })` | Lower-level export with options. |

## Generic / type utilities

| Builtin | Form | Purpose |
|---|---|---|
| `@get_int` | `(value)` → integer | Extract the underlying integer of a wrapped type (e.g., a color id). |
| `@type_of` | `(value)` → `type` | (Listed again here for cross-reference.) |

## Misc

| Builtin | Form | Purpose |
|---|---|---|
| `@assert` | `(cond)` | Runtime assert. |
| `@map` | (see above) | Element-wise apply. |

## WSE-3-only builtins

Compile with `--arch=wse3`. Guard with `if (@is_arch("wse3")) { ... }` if your code must also build for WSE-2.

| Builtin | Form | Purpose |
|---|---|---|
| `@get_ut_id` | `(u16)` → microthread id | Construct a microthread id explicitly (no implicit-by-queue rule on WSE-3). |
| `@queue_flush` | `(queue_id)` | Schedule the teardown task to fire when `queue_id` next becomes empty. Runtime-only. |
| `@set_control_task_table` | `()` or `(.{ .instructions = N, .stride = S })` | Decouple control tasks from the shared task table. `N` ∈ {2,4,8} (default 4); `S` ∈ 1..7 (default 1). At most once per `comptime` block. |
| `@set_empty_queue_handler` | `(fn, queue_id)` | Run `fn` when `queue_id` empties (use after `@queue_flush`). Caller must reset the queue-flush status register. |
| `@bind_rotating_tasks` | `(main, alt, task_id, .{ .limit = L, .init = I? })` | Bind a data-task / control-task pair that rotate. At most two concurrent rotation pairs per PE. |

See [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) *(planned)* for the WSE-3 microthread/queue interactions.

## Idiomatic usage snippets

### Branch by arch

```csl
const dst = @get_dsd(fabout_dsd, if (@is_arch("wse3")) .{
  .extent = N, .output_queue = oq,
} else .{
  .extent = N, .fabric_color = c, .output_queue = oq,
});
```

### Comptime config sanity check

```csl
comptime {
  @comptime_assert(N > 0,                 "N must be positive");
  @comptime_assert(N % 4 == 0,            "N must be a multiple of 4");
  @comptime_assert(@element_count(A) == M*N, "A wrong size");
}
```

### Polymorphic copy

```csl
fn copy(comptime T: type, size: u16, src: *const T, dst: *T) void {
  // body uses @element_count, @rank, etc., to dispatch per shape
}
```

### Reset accumulator across an op chain

```csl
const out = @get_dsd(fabout_dsd, .{
  .extent = N, .fabric_color = oc,
  .zero = .{ .first_source = true },
});
@fmuls(out, a_dsd, b_dsd);    // dst is reset to 0 each completion
```

### Element-wise apply

```csl
fn add_one(a: f32) f32 { return a + 1.0; }
@map(add_one, in_dsd, out_dsd);
```

## Gotchas

- **`@as` vs `@bitcast`.** `@as` is semantic coercion (type-aware); `@bitcast` is a raw bit reinterpretation. Don't substitute one for the other — `@as(u32, 1.5_f32)` truncates; `@bitcast(u32, 1.5_f32)` gives you the IEEE bit pattern.
- **`@ptrcast(*T, ptr)`** — the type comes first. Swap and the diagnostic is misleading.
- **`@constants(type, val)` is *not* the constant-folding builtin.** It's the array-fill constructor. The constant-folding is automatic in comptime.
- **`@range` argument order:** `(T, end)`, `(T, start, end)`, `(T, start, step, end)`. Step is in the *middle*, not at the end of the three-arg form.
- **`@map` cares about the order of DSD args.** Inputs first (positional), output last. The user fn's argument count must match the input-DSD count.
- **`@initialize_queue` is comptime-only**, but the queue/color values it operates on can be runtime parameters supplied at compile time. It only sets up the binding — it doesn't allocate hardware at runtime.
- **`@set_config`/`@get_config` are footguns.** Configuration registers can affect routing, scheduling, and FP behaviour in ways the compiler can't track. Use library wrappers (`<tile_config>`) when one exists.
- **`@assert` does *not* generate a no-op in release builds**, depending on build mode. For unconditional invariants, use `@comptime_assert` if the condition is comptime-knowable.
- **Symbol-id builtins return `u32` and are only useful at runtime within the same compilation unit.** Don't expect `@get_symbol_id("foo")` to match the host's view of `runner.get_id('foo')` — those are different namespaces.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-DSDS.md](SKILL-DSDS.md) — every DSD-related builtin in depth.
- [SKILL-TASKS.md](SKILL-TASKS.md) — `@bind_*_task`, `@get_*_task_id`, `@activate`, `@block`, `@unblock`.
- [SKILL-COMPTIME.md](SKILL-COMPTIME.md) — `@comptime_assert`, `@comptime_print`, `@is_comptime`.
- [SKILL-MODULES.md](SKILL-MODULES.md) — `@import_module`.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — `@export_name`, `@export_symbol`, RPC builtins.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) *(planned)* — libraries that wrap raw config/builtin calls in ergonomic facades.
- Upstream docs: <https://sdk.cerebras.net/csl/language/builtins> and <https://sdk.cerebras.net/csl/language/builtins_wse3>
