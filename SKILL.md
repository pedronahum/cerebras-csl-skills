---
name: csl
description: Writing CSL (Cerebras Software Language) kernels for the Wafer-Scale Engine. Use when working with .csl files, the cslc compiler, the Cerebras SDK, or any program that targets WSE-2/WSE-3. Covers syntax, builtins, DSDs/DSRs, tasks, microthreads, host↔device transfer via memcpy/SdkRuntime, and the cslc/cs_python toolchain.
---

# CSL: Writing Kernels for the Cerebras Wafer-Scale Engine

You are writing code for the Cerebras Software Language, the kernel language for the Wafer-Scale Engine (WSE). CSL is syntactically a near-superset of Zig — `comptime`, anonymous struct literals (`.{ ... }`), `@`-prefixed builtins, for-loop iterator syntax `|idx|`, `||` payloads — with WSE-specific extensions for fabric layout, on-chip routing, tasks, and the data-structure-descriptor (DSD) model that drives the tensor engines.

Authoritative reference: <https://sdk.cerebras.net/csl/language_index>. This skill set summarizes; the docs are the source of truth.

## Detailed Guides

| Topic | Guide |
|---|---|
| **Toolchain & workflow** (`cslc`, `cs_python`, `CSL_IMPORT_PATH`, Lima VM, debugging) | [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) |
| **Syntax** (types, vars, pointers, functions, statements, operators) | [SKILL-SYNTAX.md](SKILL-SYNTAX.md) |
| **Type system** (numeric, struct, union, enum, array, pointer, `anyopaque`, `comptime_string`, `imported_module`, `direction`, coercions) | [SKILL-TYPES.md](SKILL-TYPES.md) *(planned)* |
| **Comptime** (comptime-known values, comptime expressions, types requiring comptime, evaluation rules) | [SKILL-COMPTIME.md](SKILL-COMPTIME.md) *(planned)* |
| **Generics** (constraining type parameters, specializing logic, computing with types) | [SKILL-GENERICS.md](SKILL-GENERICS.md) *(planned)* |
| **Storage classes** (`extern`, `export`, `linkname`, symbol names) | [SKILL-STORAGE.md](SKILL-STORAGE.md) *(planned)* |
| **Modules** (`@import_module`, `param`, binary symbol names) | [SKILL-MODULES.md](SKILL-MODULES.md) *(planned)* |
| **DSDs** (1D/2D/3D/4D memory vectors, fabric in/out, FIFOs, circular buffers, async ops, offset/stride/length mutation) | [SKILL-DSDS.md](SKILL-DSDS.md) |
| **DSRs** (DSR/XDSR/SR allocation, types, builtins, stride registers) | [SKILL-DSRS.md](SKILL-DSRS.md) *(planned)* |
| **Tasks** (data tasks, local tasks, control tasks, binding builtins, activation) | [SKILL-TASKS.md](SKILL-TASKS.md) |
| **Microthreads** (WSE-3 microthread IDs, blocking/unblocking, rotating tasks, queue handlers) | [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) *(planned)* |
| **Routes & fabric** (colors, rectangles, directions, color swapping, CE injection) | [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)* |
| **Host↔device** (memcpy infrastructure, SdkRuntime, `@export_name`/`@export_symbol`, RPC) | [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) |
| **Standard library** (`<math>`, `<debug>`, `<simprint>`, `<collectives_2d>`, `<dsd_ops>`, `<random>`, `<string>`, `<time>`, `<timer>`, `<tile_config>`, `<types>`, `<kernels>`, …) | [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) *(planned)* |
| **Builtins reference** (`@activate`, `@allocate_fifo`, `@bind_*`, `@get_dsd`, `@load_to_dsr`, `@map`, RPC builtins, DSD-op builtins) | [SKILL-BUILTINS.md](SKILL-BUILTINS.md) *(planned)* |
| **SIMD mode** (appendix) | [SKILL-SIMD.md](SKILL-SIMD.md) *(planned)* |

Files marked *(planned)* will be filled in over subsequent sessions; the cheat sheet below covers the essentials in the meantime.

## Quick reference

### Numeric types

```csl
i8, i16, i32, i64        // signed integers
u8, u16, u32, u64        // unsigned integers
f16, f32                 // floating point  (f16 via @fp16 conversions)
bool                     // bool (1 bit on the PE)
```

### Variables, constants, parameters

```csl
const M: i16 = 4;              // constant
var x: [N]f32;                 // mutable array (zero-initialized)
var y = @zeros([M]f32);        // explicit zero-init
var x_one = @constants([N]f32, 1.0);  // fill with a scalar

// `param` declares an input that the caller (a layout block or @import_module
// invocation) must provide. Like `const` but bound at compile time externally.
param memcpy_params;
param M: i16;
param width: i16 = 4;          // with a default
```

### Pointers

```csl
const y_ptr: [*]f32 = &y;      // many-item pointer (unknown length)
const p: *f32 = &y[0];         // single-item pointer
```

### Functions

```csl
fn gemv() void {
  // ...
}

fn add(a: f32, b: f32) f32 {
  return a + b;
}
```

### Control flow

```csl
// for-loop with @range
for (@range(i16, N)) |idx| {
  A[idx] = @as(f32, idx);
}

// while-loop with continuation
var i: i16 = 0;
while (i < M) : (i += 1) {
  b[i] = 2.0;
}

// if / else  (C-like; condition must be `bool`)
if (cond) { ... } else { ... }
```

### Anonymous struct literals

```csl
// Used everywhere — @import_module params, @get_dsd args, @set_tile_code params.
.{ .width = 4, .height = 1 }
.{ .tensor_access = |i|{M} -> b[i] }
```

### Comptime block

```csl
// comptime{} runs at compile time. Used for symbol exports and any
// preparation that must happen before the kernel runs.
comptime {
  @export_symbol(y_ptr, "y");
  @export_symbol(init_and_compute);
}
```

### Modules and imports

```csl
// Library imports use angle-brackets (resolved via CSL_IMPORT_PATH + bundled libs)
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);

// User imports use relative paths
const stencil = @import_module("../../benchmark-libs/stencil_3d_7pts/layout.csl", .{
  .M = M, .N = N,
});
```

> Cross-directory imports require `CSL_IMPORT_PATH` (Apptainer only bind-mounts `$PWD`).
> See [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md).

### Layout block (the top-level `layout.csl`)

```csl
const memcpy = @import_module("<memcpy/get_params>", .{ .width = 4, .height = 1 });

layout {
  @set_rectangle(4, 1);                    // PE grid: columns x rows
  for (@range(i16, 4)) |x| {
    @set_tile_code(x, 0, "pe_program.csl", .{
      .memcpy_params = memcpy.get_params(x),
      .M = M, .N = N,
    });
  }

  // Host-visible array symbols. Last arg: true = host can write, false = read-only.
  @export_name("A", [*]f32, true);
  @export_name("y", [*]f32, false);

  // Host-callable function symbol.
  @export_name("compute", fn()void);
}
```

### DSDs (the workhorse abstraction)

DSDs describe a region of memory or fabric so the tensor engines can stream over it. They look like fat pointers with stride/length/dimension/direction baked in.

```csl
// 1D memory DSD, two equivalent forms:
var b_dsd = @get_dsd(mem1d_dsd, .{ .tensor_access = |i|{M} -> b[i] });
var b_dsd = @get_dsd(mem1d_dsd, .{ .base_address = &b, .extent = M });

// Strided access (every Nth element):
var col_dsd = @get_dsd(mem1d_dsd, .{ .tensor_access = |i|{M} -> A[i*N] });
var col_dsd = @get_dsd(mem1d_dsd, .{ .base_address = &A, .extent = M, .stride = N });

// Mutating a DSD after construction:
col_dsd = @increment_dsd_offset(col_dsd, 1, f32);
col_dsd = @set_dsd_length(col_dsd, new_len);
col_dsd = @set_dsd_stride(col_dsd, new_stride);
```

### DSD operations

DSD operations apply the tensor engines to whole DSDs in one shot — the equivalent of vector intrinsics, but for arbitrarily-shaped strided regions:

```csl
// y = y + A_col * x[i]   (fused multiply-add, scalar broadcast)
@fmacs(y_dsd, y_dsd, A_dsd, x[i]);

// y = y + b              (vector add)
@fadds(y_dsd, y_dsd, b_dsd);

// Other common ops (full list in SKILL-BUILTINS.md when written):
// @fadds, @fsubs, @fmuls, @fmacs, @fmovs, @fnegs, @fabss
// @mov16/@mov32, @add16/@add32, @sub*, @mul*, @and*, @or*, @xor*
```

### Tasks (event-driven execution)

The PE is event-driven — code runs in response to *tasks* bound to *colors* (logical wire IDs) or to *local task IDs*:

```csl
// Bind a function to a local task ID; the compiler picks the ID when @get_local_task_id is called
const my_task_id: local_task_id = @get_local_task_id(8);
task my_task() void { ... }

comptime {
  @bind_local_task(my_task, my_task_id);
}

// Activate it from another task / from comptime startup:
@activate(my_task_id);
```

See [SKILL-TASKS.md](SKILL-TASKS.md) *(planned)* for data tasks (fire on wavelet arrival), local tasks (fire on `@activate`), and control tasks (fire on a control-color wavelet).

## Common patterns

### Single-PE compute with host I/O (gemv-01 template)

```csl
// layout.csl
const memcpy = @import_module("<memcpy/get_params>", .{ .width = 1, .height = 1 });
layout {
  @set_rectangle(1, 1);
  @set_tile_code(0, 0, "pe_program.csl", .{ .memcpy_params = memcpy.get_params(0) });
  @export_name("y", [*]f32, false);
  @export_name("compute", fn()void);
}
```

```csl
// pe_program.csl
param memcpy_params;
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);

var y = @zeros([M]f32);
const y_ptr: [*]f32 = &y;

fn compute() void {
  // ... fill y ...
  sys_mod.unblock_cmd_stream();   // required so the host's next memcpy command can run
}

comptime {
  @export_symbol(y_ptr, "y");
  @export_symbol(compute);
}
```

### Strided DSD over a matrix column (gemv-02 template)

```csl
var A: [M*N]f32;                                                 // row-major
var col_dsd = @get_dsd(mem1d_dsd, .{ .base_address = &A,
                                     .extent = M, .stride = N });
for (@range(u16, N)) |i| {
  @fmacs(y_dsd, y_dsd, col_dsd, x[i]);
  col_dsd = @increment_dsd_offset(col_dsd, 1, f32);              // advance to next column
}
```

### Compiling and running (wse3)

From a directory containing your `layout.csl`/`pe_program.csl`:

```sh
cslc --arch=wse3 ./layout.csl --fabric-dims=8,3 --fabric-offsets=4,1 \
     -o out --memcpy --channels 1
cs_python run.py --name out
```

The `--fabric-dims` / `--fabric-offsets` reserve a region of the simulated fabric large enough to contain your `@set_rectangle` plus the memcpy infrastructure. See [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) for the calculation rule.

## Gotchas

- **Wrappers only bind `$PWD`.** Any `@import_module("../somewhere/...")` outside the cwd needs the parent directory exported in `CSL_IMPORT_PATH` (colon-separated realpaths). Symptoms: `error: Unable to open ...: no such file or directory`. The compiler's INFO line reminds you.
- **`unblock_cmd_stream()` is mandatory** at the end of any host-RPC-callable function that does work — otherwise subsequent memcpy commands hang.
- **`@export_symbol` lives inside `comptime { }`.** Forgetting the wrapping block is a common copy-paste error.
- **CSL bool ≠ C bool.** Conditions must be `bool`, not `i32` — there is no truthiness coercion.
- **`f16` is not a first-class arithmetic type on all archs.** Use `@fp16` builtins to convert; prefer `f32` for compute.
- **Library names are angle-bracketed**: `"<memcpy/memcpy>"` not `"memcpy/memcpy"`. Relative paths use no brackets.

## See also

- Bundled examples: `${SDK}/csl-extras-*/examples/tutorials/` (35 progressive tutorials) and `examples/benchmarks/` (15+ real algorithms incl. BiCGStab, cholesky, FFT, GEMM, conjugate gradient).
- `commands_wse3.sh` next to every example — canonical compile/run invocation.
- This skill set is versioned against SDK **2.10.0**; check `cs_python --version` against your install before trusting specifics.
