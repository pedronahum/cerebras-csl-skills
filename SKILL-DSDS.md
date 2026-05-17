---
name: csl-dsds
description: Data Structure Descriptors (DSDs) in CSL — the fat-pointer abstraction that drives the tensor engines. Covers mem1d_dsd, mem4d_dsd, circbuf_dsd, fabin_dsd, fabout_dsd, fifo_dsd; tensor_access lambda syntax; mutators (@increment_dsd_offset, @set_dsd_length/stride/base_addr); async fabric operations; input/output queues and microthread allocation; priority; SIMD mode; wavelet_index_offset; control_transform; switch advancement.
---

# Data Structure Descriptors (DSDs)

DSDs are the central abstraction of CSL. A DSD is a compact, hardware-backed description of *where data lives and how to iterate over it* — a fat pointer carrying base address, length, stride (in 1D) or shape (in multi-D), and (for fabric variants) which queue/color/priority to use. The tensor engines consume DSDs directly: every vector intrinsic (`@fmacs`, `@fadds`, `@mov16`, ...) operates on DSD operands, applying the op across the entire shape in hardware without an explicit loop.

You construct DSDs with `@get_dsd(type, .{ ...fields })`, mutate them with `@set_dsd_*` / `@increment_dsd_offset` builtins, and consume them with the arithmetic builtins. There are exactly five DSD types and one related FIFO descriptor:

| Type | What it describes |
|---|---|
| `mem1d_dsd` | A strided 1D walk over memory. The everyday DSD. |
| `mem4d_dsd` | A walk over up to 4 dimensions of memory. |
| `circbuf_dsd` | A circular buffer in memory (must be loaded into a DSR before use as op operand). |
| `fabin_dsd` | A stream of incoming wavelets from a fabric color / input queue. |
| `fabout_dsd` | A stream of outgoing wavelets onto a fabric color / output queue. |
| `fifo_dsd` (`@allocate_fifo`) | An on-chip FIFO buffer; behaves as both producer and consumer. |

All DSDs carry an `extent` (or `length`), the count of repeated operations. Every DSD op fires `extent`-many element operations.

## Constructor: `@get_dsd`

```csl
@get_dsd(dsd_type, .{ ...fields });
```

Fields are case-sensitive; the anonymous-struct literal `.{ ... }` is comptime — every field's value must be `comptime`-known unless otherwise noted in the type-specific tables below.

## `mem1d_dsd` — 1D strided memory

Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `base_address` | pointer expression | one of `base_address`/`tensor_access` | Address of the first element. |
| `extent` | `u16` | with `base_address` | Number of elements to iterate over. |
| `stride` | `i8` | optional (default `1`) | Element step (in units of element type). Can be negative. |
| `offset` | `i16` | optional (default `0`) | Static offset, in elements, added to base. |
| `tensor_access` | lambda | one of `base_address`/`tensor_access` | See below. |
| `wavelet_index_offset` | `bool` | optional (default `false`) | Enables `.index` argument on ops; see *Explicit Index Offset*. |

### Two equivalent construction styles

```csl
var b: [M]f32;

// Style 1: explicit fields
var b_dsd = @get_dsd(mem1d_dsd, .{ .base_address = &b, .extent = M });

// Style 2: tensor-access lambda — strictly more expressive
var b_dsd = @get_dsd(mem1d_dsd, .{ .tensor_access = |i|{M} -> b[i] });
```

`tensor_access` is `|induction-vars|{extent-tuple} -> base-expr[index-expr]`. Anything affine in the induction variable is fine:

```csl
// Every other element, starting at index 1:
const oddElements = @get_dsd(mem1d_dsd, .{
  .tensor_access = |i|{5} -> array[2*i + 1]
});

// Diagonal of a square matrix (1D walk over 2D storage):
const array = @zeros([20, 20]u16);
const diagonal = @get_dsd(mem1d_dsd, .{
  .tensor_access = |i|{20} -> array[i, i]
});

// Strided column walk over a row-major matrix (see gemv-02 tutorial):
var A: [M*N]f32;
var A_col = @get_dsd(mem1d_dsd, .{ .tensor_access = |i|{M} -> A[i*N] });
// Equivalent:
var A_col = @get_dsd(mem1d_dsd, .{ .base_address = &A, .extent = M, .stride = N });
```

The lambda form is preferred when the access pattern is non-trivial — the compiler picks the right stride.

## `mem4d_dsd` — multi-dimensional memory

Up to four dimensions. Fields:

| Field | Type | Notes |
|---|---|---|
| `base_address` | comptime ptr to tensor | One of `base_address`/`tensor_access`. |
| `extent` | comptime tuple of `u16` | Per-dim count. |
| `stride` | comptime tuple of `i16` | Per-dim step (optional; inferred from `tensor_access`). |
| `offset` | `i16` | Static offset, in elements. |
| `tensor_access` | lambda | `|i,j,k,l|{e0,e1,e2,e3} -> arr[expr_i, expr_j, expr_k, expr_l]`. |
| `wavelet_index_offset` | `bool` | Optional, default `false`. |

```csl
const array = @zeros([1, 2, 3, 4]u16);
const subset = @get_dsd(mem4d_dsd, .{
  .tensor_access = |i, j, k, l|{1, 2, 1, 4} -> array[i, j, 1+k, l]
});
```

`@set_dsd_length` does **not** work on `mem4d_dsd`; mutate by reconstructing or by `@increment_dsd_offset`.

## `circbuf_dsd` — circular buffer

| Field | Type | Notes |
|---|---|---|
| `base_address` | comptime ptr | Buffer storage. |
| `extent` | non-negative int expr | Total elements to traverse (can exceed buffer length — that's the point). |
| `wraparound` | `u16` | Optional if `base_address` points to a tensor (then inferred from tensor length). |

```csl
var buffer: [10]f16;
const c1 = @get_dsd(circbuf_dsd, .{ .base_address = &buffer, .extent = 20 });
const c2 = @get_dsd(circbuf_dsd, .{ .base_address = &buffer, .extent = 20, .wraparound = 5 });
```

**Critical:** `circbuf_dsd` cannot be used directly as a DSD-op operand — it must be loaded into a DSR first via `@load_to_dsr_xdsr`. See [SKILL-DSRS.md](SKILL-DSRS.md) *(planned)*.

## `fabin_dsd` — incoming wavelets

Reads from a fabric color / input queue. Fields:

| Field | Type | Notes |
|---|---|---|
| `extent` | `u16` | Number of wavelets to consume. |
| `input_queue` | queue id | From `@get_input_queue(N)`. Required on WSE-3; preferred on WSE-2. |
| `fabric_color` | `color` | WSE-2 alternative; on WSE-3 the queue is the binding point. |
| `priority` | `.{ .high/.medium/.low = true }` | WSE-3 only. |
| `control_transform` | `bool` | See *Control wavelet transform* below. |

```csl
const recv = @get_dsd(fabin_dsd, .{ .extent = M, .input_queue = recv_w_iq });
```

WSE-2 / WSE-3 conditional pattern from the bundled `gemv-09-streaming` tutorial:

```csl
const in_dsd = @get_dsd(fabin_dsd, if (@is_arch("wse3")) .{
  .extent = M, .input_queue = recv_w_iq,
} else .{
  .fabric_color = recv_west_color, .extent = M, .input_queue = recv_w_iq,
});
```

## `fabout_dsd` — outgoing wavelets

| Field | Type | Notes |
|---|---|---|
| `extent` | `u16` | Number of wavelets to send. |
| `output_queue` | queue id | From `@get_output_queue(N)`. |
| `fabric_color` | `color` | The wire ID the wavelets go out on (WSE-2; on WSE-3 derived from the queue binding). |
| `control` | `bool` | Sends control wavelets (vs data). |
| `wavelet_index_offset` | `bool` | Index goes in high 16 bits of wavelet. |
| `simd_mode` | `.{ .simd_32/.simd_64/.simd_32_or_64 = true }` | Pack 32- or 64-bit operations into wavelets. |
| `zero` | `.{ .first_source/.second_source = true }` | Reset chosen op-source register on each op completion. |
| `advance_switch` | `bool` | Each completion advances router switch position. |
| `control_transform` | `bool` | See below. |
| `priority` | `.{ .high/.medium/.low = true }` | WSE-3 only. |

```csl
const send = @get_dsd(fabout_dsd, .{
  .extent = 1024, .output_queue = send_e_oq, .fabric_color = tx,
});

// Control-wavelet DSD (e.g., to flip a routing switch downstream):
const ctrl = @get_dsd(fabout_dsd, .{
  .extent = 1, .control = true, .fabric_color = out,
});
```

## `fifo_dsd` — on-chip FIFO

Allocated, not `@get_dsd`'d:

```csl
var fifo_buffer = @zeros([32]i16);
const fifo = @allocate_fifo(fifo_buffer);
```

Optional second argument is a config struct:

| Field | Type | Notes |
|---|---|---|
| `empty_action` | `.{ .terminate/.suspend/.fault/.test_or_suspend = true }` | Default: `test_or_suspend`. |
| `full_action` | same options | What to do when a producer hits a full FIFO. |
| `activate_pop` | task | Activates this task on each pop. |
| `activate_push` | task | Activates this task on each push. |
| `priority` | `.{ .high/.medium/.low = true }` | WSE-3 only. |
| `simd_mode` | `.{ .simd_32/.simd_64 = true }` | WSE-2 only. |

```csl
const fifo = @allocate_fifo(fifo_buffer, .{
  .empty_action = .{ .terminate = true },
  .full_action  = .{ .fault = true },
});

// Or task hooks:
task on_push() void { /* ... */ }
task on_pop()  void { /* ... */ }
const fifo = @allocate_fifo(fifo_buffer, .{
  .activate_push = on_push, .activate_pop = on_pop,
});
```

A FIFO is both a producer and consumer DSD — pass it to a DSD op as either source or destination. The compiler infers role by position.

## Mutating DSDs

DSDs are values; mutators return new values (treat them as immutable + reassign).

### `@increment_dsd_offset(dsd, offset, elem_type)`

Shifts the base by `offset` *elements* (not bytes). `elem_type` is the element type (e.g., `f32`, `i16`). Works on `mem1d_dsd` and `mem4d_dsd`. Canonical pattern (gemv-02/03): walking column-by-column over a row-major matrix:

```csl
var A_col = @get_dsd(mem1d_dsd, .{ .base_address = &A, .extent = M, .stride = N });
for (@range(u16, N)) |i| {
  @fmacs(y_dsd, y_dsd, A_col, x[i]);
  A_col = @increment_dsd_offset(A_col, 1, f32);  // step to next column
}
```

`offset` can be negative:

```csl
var d = @increment_dsd_offset(dsd, -10, f32);  // step backwards
```

### `@set_dsd_base_addr(dsd, ptr_or_array)`

Clones the DSD with a new base address. Accepts an array directly or a pointer:

```csl
var A = @zeros([10]i16);
var d1 = @set_dsd_base_addr(input_dsd, A);
var d2 = @set_dsd_base_addr(input_dsd, &A);
```

### `@set_dsd_length(dsd, u16_length)`

New length, in elements (memory) or wavelets (fabric). **Does not work on `mem4d_dsd`.**

### `@set_dsd_stride(dsd, i8_stride)`

`mem1d_dsd` only. Useful when stride is runtime-known.

### FIFO read/write lengths

```csl
@set_fifo_write_length(fifo, len);  // before pushing
@mov16(fifo, src_dsd);
@set_fifo_read_length(fifo, len);   // before popping
@mov16(dst_dsd, fifo);
```

## DSD operations — the actual work

The arithmetic builtins consume DSDs:

```csl
// y_dsd = y_dsd + A_col * x_scalar    (fused multiply-add, scalar broadcast)
@fmacs(y_dsd, y_dsd, A_col, x[i]);

// y_dsd = y_dsd + b_dsd
@fadds(y_dsd, y_dsd, b_dsd);

// Plain copy
@mov16(dst_dsd, src_dsd);
@mov32(dst_dsd, src_dsd);
```

Common families (full list in [SKILL-BUILTINS.md](SKILL-BUILTINS.md) *(planned)*): `@fadds`/`@fsubs`/`@fmuls`/`@fmacs`/`@fmovs`/`@fnegs`/`@fabss` (f32), `@fh*` variants (f16), `@mov16`/`@mov32`, `@add16`/`@add32`, `@sub16`/`@sub32`, `@mul16`, `@and16`/`@or16`/`@xor16`.

Operands can mix memory and fabric DSDs in the obvious ways: source from a `fabin_dsd`, destination to a `fabout_dsd`, intermediate accumulators in `mem1d_dsd`. Element counts must agree (the `extent`s), or you get a compile error.

## Async DSD operations

Any DSD op that touches a fabric DSD (`fabin_dsd`, `fabout_dsd`) can run asynchronously, allowing the calling task to continue while the tensor engine streams in the background:

```csl
@mov16(dst, src, .{ .async = true });
```

Async option fields:

| Field | Type | Effect |
|---|---|---|
| `async` | `bool` | Detach the op onto a microthread. |
| `activate` | task id | Activate the named task on completion. |
| `unblock` | task id | Unblock the task (assumed previously blocked) on completion. |
| `on_control` | `.{ .terminate = true }` / `.{ .activate = task }` | Reaction to receiving a control wavelet during the op. |
| `priority` | `.{ .high/.medium/.low = true }` | WSE-2 only on op-level; on WSE-3 set priority on the DSD/queue itself. |

```csl
@mov16(dst, src, .{ .async = true, .activate = next_task });

@fadds(out_dsd, y_dsd, in_dsd, .{ .async = true });  // gemv-09 pattern

@mov16(dst, src, .{
  .async = true,
  .on_control = .{ .terminate = true },  // stop op when a control wavelet arrives
});
```

Reads-not-writes for `out_dsd` operate normally during async; the op is fully concurrent with the calling task's subsequent execution.

## Input/output queues & microthread allocation

Every fabric DSD binds to a queue:

```csl
const h2d_x_iq:  input_queue  = @get_input_queue(2);
const x_oq:      output_queue = @get_output_queue(2);
```

Queue capacities (the maximum number of in-flight words the queue can buffer):

| Queue ID | WSE-2 In | WSE-2 Out | WSE-3 In | WSE-3 Out |
|---|---|---|---|---|
| 0, 1 | 6 | 2 | 8 | 8 |
| 2, 3 | 4 | 6 | 4 | 8 |
| 4, 5 | 2 | 2 | 4 | 8 |
| 6, 7 | 2 | N/A | 4 | 8 |

**On WSE-2** the microthread ID of an async op is implicit:
1. If a `fabout_dsd` is involved: thread ID = its `output_queue` id.
2. Else: thread ID = the first `fabin_dsd` operand's `input_queue` id.

Two concurrent async ops sharing the same implicit thread ID is a deadlock waiting to happen and the compiler will reject it:

```csl
const out_dsd = @get_dsd(fabout_dsd, .{ ..., .output_queue = @get_output_queue(0) });
const in_dsd  = @get_dsd(fabin_dsd,  .{ ..., .input_queue  = @get_input_queue(0)  });

task t() void {
  @mov16(out_dsd, mem1_dsd, .{ .async = true });   // microthread 0
  @mov16(mem2_dsd, in_dsd,  .{ .async = true });   // ERROR: also microthread 0
}
```

**On WSE-3** microthread allocation is explicit and richer — see [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) *(planned)*.

## Priority

Three levels: `high`, `medium`, `low` (default).

```csl
// WSE-2 — on the op:
@mov16(dst, src, .{ .async = true, .priority = .{ .high = true } });

// WSE-3 — on the DSD or FIFO:
const src = @get_dsd(fabin_dsd, .{
  .extent = 10, .input_queue = in_queue, .priority = .{ .high = true },
});
const fifo = @allocate_fifo(buf, .{ .priority = .{ .low = true } });
```

## SIMD mode (fabric only)

Pack multiple ops per wavelet for higher fabric bandwidth:

```csl
const out_dsd = @get_dsd(fabout_dsd, .{
  .extent = 10, .fabric_color = out_color,
  .simd_mode = .{ .simd_32 = true },         // also .simd_64, .simd_32_or_64
});

// WSE-2 only: SIMD mode on FIFOs
const my_fifo = @allocate_fifo(buf,
  if (@is_arch("wse2")) .{ .simd_mode = .{ .simd_64 = true } } else .{ }
);
```

See [SKILL-SIMD.md](SKILL-SIMD.md) *(planned)*.

## Explicit index offset (`wavelet_index_offset`)

Lets an op carry a runtime per-call index:

```csl
const memDSD = @get_dsd(mem1d_dsd, .{
  .tensor_access = |i|{10} -> array[i],
  .wavelet_index_offset = true,
});
const outDSD = @get_dsd(fabout_dsd, .{
  .extent = 1, .fabric_color = out, .wavelet_index_offset = true,
});

task my_task() void {
  @add16(memDSD, memDSD, 42, .{ .index = my_index });  // memDSD: index = word offset added to base
  @add16(outDSD, memDSD, 42, .{ .index = my_index });  // outDSD: index → high 16 bits of outgoing wavelet
}
```

Semantics differ by DSD class — memory: address offset; fabric output: wavelet metadata.

## Reset-on-completion (`zero`)

After each op completion, optionally reset a source operand to zero. Useful in pipeline patterns where an accumulator should be cleared between strides:

```csl
const out_dsd = @get_dsd(fabout_dsd, .{
  .extent = 10, .fabric_color = out_color,
  .zero = .{ .first_source = true },     // or .second_source
});
@fmulh(out_dsd, in_first_dsd, out_first_dsd);
```

## Advance switch position (`advance_switch`)

Each op completion advances the router switch one position:

```csl
const out_dsd = @get_dsd(fabout_dsd, .{
  .extent = 10, .fabric_color = out_color, .advance_switch = true,
});
```

Pairs with explicit switch tables in route declarations. See [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)*.

## Control wavelet transform (`control_transform`)

Buffers control wavelets through a FIFO so a PE can pass them along without consuming them as data. Pattern: a PE that simply relays both data and control between two colors.

```csl
var in_dsd = @get_dsd(fabin_dsd, .{
  .fabric_color = recv_channel, .extent = 100,
  .input_queue = @get_input_queue(0), .control_transform = true,
});
const out_dsd = @get_dsd(fabout_dsd, .{
  .extent = 100, .fabric_color = send_channel,
  .output_queue = @get_output_queue(1), .control_transform = true,
});

var buf = @zeros([5]u32);
const fifo = @allocate_fifo(buf);

task relay() void {
  @mov32(fifo, in_dsd,  .{ .async = true });
  @mov32(out_dsd, fifo, .{ .async = true });
}
```

**Caveat:** with `control_transform`, only the lower 14 bits of the wavelet index are user-controllable.

## Gotchas

- **`mem4d_dsd` doesn't accept `@set_dsd_length`** — reconstruct or `@increment_dsd_offset`.
- **`circbuf_dsd` can't be an op operand directly** — `@load_to_dsr_xdsr` first.
- **WSE-2 implicit microthread IDs collide silently if you forget the rule** — two async ops sharing a queue id deadlock. WSE-3 forces you to be explicit; consider gating WSE-2 code through `@is_arch("wse2")` blocks.
- **Extents must match across operands.** Mixing a 10-element `mem1d_dsd` with a 12-element `fabin_dsd` is a compile-time error.
- **`tensor_access` is comptime.** The induction variable bounds and the access expression are evaluated by the compiler. Anything runtime-known (e.g. a variable extent) must go through `base_address`/`extent`/`stride` fields.
- **`@increment_dsd_offset`'s offset is in elements, not bytes.** Same with `.offset` field. The `elem_type` parameter is the type used to size the step.
- **`stride` on `mem1d_dsd` is `i8`** — caps at ±127. For larger strides, use a `tensor_access` lambda (which packs the stride internally as i16).
- **Fabric ops without `.async = true` block the calling task** until the op completes. Often what you want; sometimes a hang.
- **Mixing `simd_mode` with non-multiple extents** — e.g., `simd_32` with `extent = 7` — is an error. Pad or split.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry-point.
- [SKILL-DSRS.md](SKILL-DSRS.md) *(planned)* — DSR/XDSR allocation; `@load_to_dsr_xdsr` for circular buffers.
- [SKILL-TASKS.md](SKILL-TASKS.md) *(planned)* — tasks, `@activate`, `@bind_*_task`.
- [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) *(planned)* — WSE-3 explicit microthread ids, rotating tasks.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)* — colors, switch tables, `advance_switch`.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md) *(planned)* — the full DSD-op catalogue.
- Tutorials grounded in real DSD usage: bundled `gemv-02-memory-dsds`, `gemv-03-memcpy`, `gemv-09-streaming`, and benchmarks `bandwidth-test`, `row-col-broadcast`, `gemv-collectives_2d`.
- Upstream docs: <https://sdk.cerebras.net/csl/language/dsds>
