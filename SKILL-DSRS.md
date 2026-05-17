---
name: csl-dsrs
description: CSL Data Structure Registers (DSRs) — the hardware-backed register slots that hold DSDs for op dispatch. Covers the five DSR slot types (dsr_dest, dsr_src0, dsr_src1, dsr_fifo_dest, dsr_fifo_src1), Extended DSRs (XDSR) for FIFOs / circular buffers / multi-dim, Stride Registers (SR) for mem4d_dsd, allocation (@get_dsr, @get_xdsr, @get_sr), loading (@load_to_dsr, @load_to_dsr_xdsr, @load_to_dsr_xdsr_sr), load constraints by DSD/DSR pairing, the .save_address option for sequential chunk processing, the .single_step option required for @map, FIFO allocation with explicit DSR control via @allocate_fifo options, and the rule that compiler auto-allocation handles most cases — manual DSR management is for advanced/perf scenarios.
---

# Data Structure Registers (DSRs)

DSRs are the hardware register slots that DSD operations actually run against. A DSD is a *description* of a data region; a DSR is the *hardware slot* that holds that description for the tensor engine to consume.

You almost never need to allocate DSRs yourself: the compiler does it automatically for every DSD op. Manual DSR management matters for:

- **Sequential chunk processing**, where one op should pick up where the previous left off (`.save_address`).
- **Element-wise user functions** through `@map` (`.single_step`).
- **Circular buffers** and **`mem4d_dsd`s**, which mandatorily route through XDSR/SR.
- **Resource-tight kernels** where you want explicit control of which slot holds which descriptor.

Skip this skill on first reading; come back when you hit a "DSR exhausted" diagnostic or need `@map`.

## DSR slot types

Five regular DSR slot types differ by direction and FIFO awareness:

| Type | Role | Notes |
|---|---|---|
| `dsr_dest` | Destination only. | Receives the result of a DSD op. |
| `dsr_src0` | Source (or destination, position-dependent). | Most general slot. |
| `dsr_src1` | Source only. | Pairs with `dsr_src0` for two-operand ops. |
| `dsr_fifo_dest` | FIFO-aware destination. | Tolerates full/empty gracefully. |
| `dsr_fifo_src1` | FIFO-aware source. | Same idea. |

Plus the *extended* slots:

| Type | Role |
|---|---|
| `xdsr` | Extended DSR for FIFOs, `circbuf_dsd`, and multi-dim memory. |
| `sr` | Stride Register — up to three per `mem4d_dsd` for per-dim strides. |

## Allocating DSRs

DSR identifiers are allocated by integer slot id at compile time:

```csl
const d_out  = @get_dsr(dsr_dest, 0);
const d_in0  = @get_dsr(dsr_src0, 1);
const d_in1  = @get_dsr(dsr_src1, 1);

const fifo_d = @get_dsr(dsr_fifo_dest, 4);
const fifo_s = @get_dsr(dsr_fifo_src1, 4);

const my_xdsr = @get_xdsr(4);
const my_sr   = @get_sr(2);
```

The integer id is the hardware slot number; the compiler reports a conflict if you reuse the same `(type, id)` pair from two non-overlapping load paths. The available slot count is hardware-fixed — check the upstream docs for the per-arch maxima — but typical kernels stay well under the ceiling.

## Loading a DSD into a DSR

```csl
@load_to_dsr(dsr, dsd);
@load_to_dsr(dsr, dsd, .{ .async = true, .activate = next_task });
```

After `@load_to_dsr`, DSD-op builtins can take the *DSR* in place of the DSD:

```csl
const d_out = @get_dsr(dsr_dest, 0);
const d_in0 = @get_dsr(dsr_src0, 1);

@load_to_dsr(d_out, y_dsd);
@load_to_dsr(d_in0, A_dsd);
@fmacs(d_out, d_out, d_in0, x_scalar);    // uses the DSRs, not the DSDs directly
```

### Load constraints by direction

The compiler enforces these:

- `fabin_dsd` (input wavelets) → may load into `dsr_src0`, `dsr_src1`, `dsr_fifo_src1`. **May not** load into `dsr_dest`.
- `fabout_dsd` (output wavelets) → may load into `dsr_dest`, `dsr_fifo_dest`. **May not** load into `dsr_src0` or `dsr_src1`.
- `mem1d_dsd` → any slot type, position-appropriate.
- `mem4d_dsd` → requires `@load_to_dsr_xdsr_sr` (a DSR + XDSR + up to three SRs).
- `circbuf_dsd` → requires `@load_to_dsr_xdsr` (a DSR + XDSR pair).

## `@load_to_dsr_xdsr` — circular buffers

`circbuf_dsd` cannot be a direct op operand; it must go through paired DSR + XDSR slots:

```csl
const dsr     = @get_dsr(dsr_src0, 2);
const xdsr    = @get_xdsr(2);
const circbuf = @get_dsd(circbuf_dsd, .{ .base_address = &buf, .extent = 100 });

@load_to_dsr_xdsr(dsr, xdsr, circbuf);
@mov32(dst_dsr, dsr);     // now usable as an op operand
```

## `@load_to_dsr_xdsr_sr` — `mem4d_dsd`

Multi-dimensional memory DSDs need a DSR, an XDSR, and one to three stride registers:

```csl
const dsr   = @get_dsr(dsr_src0, 3);
const xdsr  = @get_xdsr(3);
const sr_x  = @get_sr(0);
const sr_y  = @get_sr(1);
const sr_z  = @get_sr(2);
const dsd4d = @get_dsd(mem4d_dsd, .{
  .tensor_access = |i,j,k|{2,3,4} -> arr[i, j, k]
});

@load_to_dsr_xdsr_sr(dsr, xdsr, .{ sr_x, sr_y, sr_z }, dsd4d);
```

**Rule for runtime-known DSDs:** always reserve three SRs even if some dimensions are degenerate. The compiler may need slots for runtime strides it can't yet analyse. At comptime, supply exactly the count of distinct non-trivial strides.

## Async loads + completion hooks

`@load_to_dsr` takes the same `.async`/`.activate`/`.unblock`/`.priority` options as a DSD op. Async load + sync op chains a prefetch behind compute:

```csl
@load_to_dsr(d_in0, slow_fabin_dsd, .{ .async = true, .activate = compute_task });
// compute_task body uses d_in0 once the wavelets have arrived
```

## `.save_address` — sequential chunk processing

Set `.save_address = true` on a load to tell the hardware to advance the DSR's base by the consumed extent on each completion:

```csl
const d_in = @get_dsr(dsr_src0, 1);
@load_to_dsr(d_in, chunk_dsd, .{ .save_address = true });

@mov32(d_out, d_in);          // processes chunk[0..extent]
@mov32(d_out, d_in);          // automatically processes chunk[extent..2*extent]
@mov32(d_out, d_in);          // chunk[2*extent..3*extent]
```

This lets a single load drive multiple ops with sequential addressing — useful when streaming a long array through a fixed-size op pipeline.

## `.single_step` — required for `@map`

`@map` runs a user function once per element. Each invocation needs the DSR to advance exactly one element. Mark the load with `.single_step = true`:

```csl
const in_dsr  = @get_dsr(dsr_src0, 1);
const out_dsr = @get_dsr(dsr_dest, 0);

@load_to_dsr(in_dsr,  in_dsd,  .{ .single_step = true });
@load_to_dsr(out_dsr, out_dsd, .{ .single_step = true });

@map(math_lib.sqrt_f16, in_dsr, out_dsr);
```

Omitting `.single_step` on a `@map` source/destination is a compile error (or a runtime stride bug, depending on architecture).

## FIFO allocation with explicit DSRs

By default `@allocate_fifo(buffer)` lets the compiler pick DSR slots. For tight resource budgets you can request explicit slots:

```csl
var fifo_buf = @zeros([32]i16);
const fifo = @allocate_fifo(fifo_buf, .{
  .dest = @get_dsr(dsr_fifo_dest, 4),
  .src  = @get_dsr(dsr_fifo_src1, 4),
  .xdsr = @get_xdsr(1),
});
```

**Caution:** non-FIFO DSR types (`dsr_dest`, `dsr_src1`) holding a FIFO yield undefined behavior on full/empty. Always use `dsr_fifo_*` for FIFO storage.

## When the compiler auto-allocates and when it doesn't

The compiler will allocate DSRs/XDSRs/SRs automatically for any plain DSD op. You only need explicit DSR allocation when:

1. **`.save_address`** is needed — the option is on the load, so you must have an explicit load.
2. **`.single_step`** is needed for `@map`.
3. **Circular buffers** — the language requires `@load_to_dsr_xdsr` for `circbuf_dsd`.
4. **`mem4d_dsd`** — same: `@load_to_dsr_xdsr_sr` is mandatory.
5. **Fine-grained queue allocation** — assigning specific FIFO slots when the default packing isn't what you want.
6. **DSR-pressure errors** — if the compiler reports it can't find a free slot, you may need to manually reuse slots in non-overlapping regions of code.

For everyday code (`@fmacs`, `@fadds`, `@mov*`), the compiler handles everything.

## Gotchas

- **DSR ids are *hardware* slots, not arbitrary names.** Two DSDs loaded into `@get_dsr(dsr_src0, 1)` in non-overlapping code regions reuse the same physical register — that's the *point*. But if they overlap (one op's body refers to both), the second load clobbers the first.
- **`@get_dsr(dsr_src1, 0)` and `@get_dsr(dsr_src0, 0)` are different slots**, despite the shared id. The (type, id) pair is the identity.
- **`circbuf_dsd` and `mem4d_dsd` cannot be op operands directly.** Forgetting this gives a compile error pointing at the op, not the DSD construction.
- **`fabin_dsd` into `dsr_dest` is a compile error** (you can't write to inbound wavelets). Same in reverse for `fabout_dsd` into a source slot.
- **`.save_address` adds runtime state to the DSR.** If you reuse the DSR for an unrelated op, that state can produce surprising offsets. Reset by re-loading with `.save_address = false` (or omit it).
- **`.single_step` is `@map`-only.** Using `.single_step = true` for non-`@map` ops applies element-by-element semantics, which usually isn't what you want.
- **SR slot 0/1/2 ordering matters in `@load_to_dsr_xdsr_sr`.** The tuple's order maps to dimensions in declaration order — get this wrong and you stride through phantom positions.
- **Per-arch DSR counts differ.** WSE-2 and WSE-3 have different ceilings on slot counts and FIFO DSR counts. Hard-coding slot ids past the arch's maximum gives a compile error.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-DSDS.md](SKILL-DSDS.md) — every DSD type that ultimately backs into a DSR.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md) — `@get_dsr`, `@get_xdsr`, `@get_sr`, `@load_to_dsr`, `@load_to_dsr_xdsr`, `@load_to_dsr_xdsr_sr`, `@map`.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) — `<dsd_ops>` provides a typed wrapper over the DSR-fronted ops.
- Upstream docs: <https://sdk.cerebras.net/csl/language/dsrs>
