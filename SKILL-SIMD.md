---
name: csl-simd
description: CSL SIMD execution — both the automatic memory-bank-driven SIMD that DSD ops opportunistically use when stride and alignment cooperate, and the explicit fabric SIMD mode (.simd_mode = .{ .simd_32 = true / .simd_64 = true / .simd_32_or_64 = true } on fabout_dsd) that packs multiple ops per wavelet. Covers the 8-bank 6-KB-each memory architecture, the per-cycle two-read-one-write constraint, the bank_1 % 4 != bank_2 % 4 rule for parallel reads, alignment recommendations ((src0_addr % 8) == ((src1_addr + 4) % 8) for optimal SIMD), stride-impact rules (strides 0/1/2/3/5/6 mod 8 yielding wider SIMD, others narrower), the WSE-3-up-to-8 vs WSE-2-up-to-4 width difference, the WSE-2-only on-FIFO SIMD mode, and the extent-divisibility requirement that packs operations cleanly.
---

# SIMD Mode

CSL has two distinct SIMD mechanisms, both contributing to higher throughput on DSD operations:

1. **Automatic memory SIMD** — DSD ops over memory-resident data opportunistically run multiple operations per cycle when stride and alignment allow. Driven by the PE's 8-bank memory layout. You don't write code for this; it Just Happens (or doesn't, depending on layout).
2. **Explicit fabric SIMD** — `fabout_dsd` (and on WSE-2, `fifo_dsd`) takes a `.simd_mode` field that packs 2 or 4 16-bit ops into a single 32- or 64-bit wavelet. You opt in per-DSD.

Both are advanced perf-tuning territory. Reach for them only after you've made the standard `@fmacs`-driven kernel work; then squeeze cycles by reading this skill.

## Automatic memory SIMD

### PE memory architecture

Each PE has 48 KiB of memory, divided into **8 banks of 6 KiB each**. Per cycle the hardware permits:

- **2 reads of 32-bit values** from *separate banks*, and
- **1 write of a 32-bit value**.

Two reads from the same bank serialize. The compiler aligns and lays out arrays to minimise bank collisions, but stride and base alignment still matter.

### The parallel-read constraint

Two reads in the same cycle must satisfy:

```
bank_1 % 4 != bank_2 % 4
```

Because the 8 banks are paired into 4 read-port groups, addresses whose bank ids are congruent mod 4 collide.

### Alignment for full SIMD

Optimal SIMD width over two source operands requires their addresses to be a half-cache-line apart at 32-bit granularity:

```
(src0_addr % 8) == ((src1_addr + 4) % 8)
```

When this holds, the compiler can issue two 32-bit reads in one cycle, doubling SIMD throughput.

The compiler does its best with whatever layout you give it; explicit `align(8)` on source arrays helps when you've measured that something fell short of expected throughput.

### Stride impact on SIMD width

Stride patterns affect achievable width:

| Stride (mod 8) | Achievable SIMD width |
|---|---|
| 0, 1, 2, 3, 5, 6 | Full (4 or 8 elements per cycle, arch-dependent) |
| Other values (4, 7) | Reduced to SIMD-2 or SIMD-1 |

This is why row-major matrix walks (stride 1) and contiguous column reductions perform well, while certain transpose-heavy patterns underperform unless explicitly reshaped.

### Width by arch

| Arch | Max SIMD width (16-bit ops) |
|---|---|
| WSE-2 | 4 |
| WSE-3 | 8 |

WSE-3's higher SIMD width is one of the main per-PE performance differentiators between the two architectures.

## Explicit fabric SIMD

`fabout_dsd` accepts a `.simd_mode` field to pack multiple ops per wavelet:

```csl
const out_dsd = @get_dsd(fabout_dsd, .{
  .extent = 10,
  .fabric_color = out_color,
  .simd_mode = .{ .simd_32 = true },        // also .simd_64, .simd_32_or_64
});
```

Options:

| Field | Meaning |
|---|---|
| `.simd_32 = true` | Pack two 16-bit ops into one 32-bit wavelet. Wavelet bandwidth halved (in wavelet count), throughput doubled. |
| `.simd_64 = true` | Pack four 16-bit ops into one 64-bit wavelet (where the fabric supports it). |
| `.simd_32_or_64 = true` | Let the compiler pick the wider mode that fits. |

The `extent` must be a multiple of the packing factor — `extent = 7` with `simd_32` is an error; with `simd_64` you need a multiple of 4.

### Use case

You're streaming 16-bit values out to neighbouring PEs at high rate. With `simd_32`, two 16-bit ops fit in each outbound wavelet — half the fabric traffic for the same logical throughput. Combine with `@add16`/`@mul16`/`@mov16` on the receiving side.

## WSE-2-only: SIMD on FIFOs

The `@allocate_fifo` options struct accepts `.simd_mode` on WSE-2 only:

```csl
const my_fifo = @allocate_fifo(
  some_buffer,
  if (@is_arch("wse2")) .{ .simd_mode = .{ .simd_64 = true } } else .{}
);
```

WSE-3 handles SIMD via the explicit-microthread / queue model rather than per-FIFO config.

## Interaction with normal DSD ops

When a DSD operation runs against a memory DSD, it automatically uses whatever memory SIMD width the data layout permits. When the same op runs against a fabric DSD with `.simd_mode` set, the explicit setting governs the wavelet packing.

A typical mixed setup: read 16-bit values from memory (automatic memory SIMD), pack them into 32-bit fabric wavelets (`.simd_32 = true` on `fabout_dsd`), unpack on the receiver side. Net: peak compute + halved fabric pressure.

## Verifying SIMD utilization

The simulator's `sim_stats.json` and the various traces emit cycle counts and bank-conflict counters. A SIMD-2 result where you expected SIMD-4 usually shows up as ~2× expected cycle count and elevated bank-conflict events. The standard debugging cycle is:

1. Compute expected cycles assuming peak SIMD (N elements / max_simd cycles).
2. Compare to actual cycles in the trace.
3. If much higher, inspect bank/alignment via the trace stats.
4. Apply `align(8)` or reshape data layout to fix.

## Gotchas

- **You can't *force* memory SIMD.** The compiler chooses what's feasible given your stride and alignment. Don't write `.simd_mode = ...` on `mem1d_dsd` — only fabric DSDs (and WSE-2 FIFOs) take that option.
- **`extent` divisibility matters for fabric SIMD.** A non-divisible extent with `simd_32` errors at compile time; with `simd_32_or_64` the compiler may pick the wider mode and then fail. Pad or split.
- **Bank conflict ≠ correctness bug.** A conflict serializes the reads — the result is correct, just slow. Don't chase phantom bugs in trace analysis.
- **WSE-3 doesn't support `.simd_mode` on FIFOs.** Cross-arch code must guard with `@is_arch("wse2")`.
- **`.simd_64` requires support on the wavelet path.** On topologies where the wavelet is 32-bit, the compiler will refuse `simd_64`.
- **Memory SIMD width is per-cycle, not per-op.** A single `@fmacs` over a 32-element DSD on WSE-3 takes 32/8 = 4 cycles if perfectly aligned; 16 cycles if every cycle suffers a bank conflict.
- **`align(8)` on an array won't help if its stride isn't friendly.** The constraint is both base alignment and stride; reshape data when stride is the problem.
- **`(src0_addr % 8) == ((src1_addr + 4) % 8)` is *between* two operands.** Aligning one operand without minding the other doesn't help.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-DSDS.md](SKILL-DSDS.md#simd-mode-fabric-only) — `.simd_mode` on `fabout_dsd` and WSE-2 FIFOs.
- [SKILL-DSRS.md](SKILL-DSRS.md) — DSRs that the SIMD ops load DSDs into.
- [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) — WSE-3's explicit microthread / queue path that replaces some WSE-2 SIMD-on-FIFO use cases.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md) — `@add16` / `@mul16` / `@mov16` (the 16-bit ops that benefit from SIMD packing).
- Upstream docs: <https://sdk.cerebras.net/csl/language/appendix>
