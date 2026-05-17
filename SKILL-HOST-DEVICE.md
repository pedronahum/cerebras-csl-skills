---
name: csl-host-device
description: Host↔device interaction for Cerebras CSL programs. Covers the two integration models — classic memcpy (bulk + RPC) and SdkLayout (port-based streams). Documents the PE-side memcpy library (<memcpy/get_params>, <memcpy/memcpy>, sys_mod.unblock_cmd_stream, MEMCPYH2D_N/MEMCPYD2H_N colors), symbol exports (@export_name in layout, @export_symbol in comptime), and the Python SdkRuntime API (memcpy_h2d/d2h with px/py/w/h/elem_per_pe/streaming/order/data_type/nonblock, broadcast variants, launch for RPC, send/receive for ports, get_id/get_port_id, load/run/stop, task handles, debug helpers). When to use streaming vs non-streaming. Sources from compile_data['params'] / out.json.
---

# Host ↔ Device: memcpy, SdkRuntime, and Streams

A Cerebras program has two sides: the CSL kernel that runs on the PEs, and a Python *host* script that drives it. The host script compiles to nothing on the wafer — it lives on the machine running the simulator or sitting next to the real CS-2/CS-3 — and uses `SdkRuntime` to ship data in/out, call kernel functions, and wait for completion.

There are two well-supported interaction models:

| Model | Host API | PE-side imports | When |
|---|---|---|---|
| **memcpy** (classic) | `memcpy_h2d` / `memcpy_d2h` / `launch` on `SdkRuntime` | `<memcpy/get_params>` in layout, `<memcpy/memcpy>` in PE code | Most programs. Bulk transfers + RPC calls. |
| **SdkLayout streams** (newer) | `send` / `receive` on `SdkRuntime` against named ports | None — layout is in Python | Programs where the Python side wants explicit control over fabric topology and where you want streaming-only I/O. |

Both can coexist; many real programs use memcpy for parameters/results and streams for the data flow.

## Model 1 — Classic memcpy

### PE side: layout

```csl
// 1x1 grid example (gemv-01)
const memcpy = @import_module("<memcpy/get_params>", .{ .width = 1, .height = 1 });

layout {
  @set_rectangle(1, 1);
  @set_tile_code(0, 0, "pe_program.csl", .{ .memcpy_params = memcpy.get_params(0) });

  // Declare host-visible array symbols
  @export_name("A", [*]f32, true);   // last arg: true = host can write
  @export_name("y", [*]f32, false);  // false = host can only read

  // Declare host-callable RPC functions
  @export_name("init_and_compute", fn()void);
}
```

`<memcpy/get_params>` parameters:

| Field | Required | Notes |
|---|---|---|
| `width` | yes | PE-grid columns. |
| `height` | yes | PE-grid rows. |

The module exposes `get_params(col)` (and on multi-row grids `get_params(col, row)`) — the result is a struct that each PE's program file accepts as the `memcpy_params` parameter.

For multi-PE programs (e.g. `gemv-05-multiple-pes`), iterate:

```csl
const memcpy = @import_module("<memcpy/get_params>", .{ .width = width, .height = 1 });

layout {
  @set_rectangle(width, 1);
  for (@range(i16, width)) |x| {
    @set_tile_code(x, 0, "pe_program.csl", .{
      .memcpy_params = memcpy.get_params(x),
      .M = M, .N = N,
    });
  }
  @export_name("A", [*]f32, true);
  @export_name("y", [*]f32, false);
  @export_name("compute", fn()void);
}
```

### PE side: program

```csl
param memcpy_params;

// sys_mod surfaces the memcpy infrastructure handles
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);

var A: [M*N]f32;
var y = @zeros([M]f32);
var A_ptr: [*]f32 = &A;
const y_ptr: [*]f32 = &y;

fn compute() void {
  // ... real work ...

  // REQUIRED at the end of every host-callable function. Without it, the
  // next memcpy/launch command from the host hangs forever.
  sys_mod.unblock_cmd_stream();
}

comptime {
  @export_symbol(A_ptr, "A");        // binds &A to host-visible name "A"
  @export_symbol(y_ptr, "y");        // binds &y to "y"
  @export_symbol(compute);           // makes compute() callable from host
}
```

Two symbol-export macros:

- `@export_name("name", type, mutability_bool)` in `layout { ... }` — declares the *name* and *type signature* the host will see. For arrays use `[*]T`; for functions, `fn(arg_types)return_type`.
- `@export_symbol(value, "name")` in `comptime { ... }` inside the PE program — binds an actual variable/pointer or function to that name on each PE. The two forms work together: layout declares, PE binds.

For functions, `@export_symbol(fn_name)` without a string argument is shorthand for `@export_symbol(fn_name, "fn_name")`.

### sys_mod surface

The struct returned by `@import_module("<memcpy/memcpy>", memcpy_params)` exposes:

| Field | Purpose |
|---|---|
| `unblock_cmd_stream()` | Call at the end of any host-callable function. Otherwise the host's next memcpy/launch command will hang. |
| `MEMCPYH2D_1`, `MEMCPYH2D_2`, ... | The fabric colors carrying streaming H2D channels. Bind to a `fabin_dsd` to consume. |
| `MEMCPYD2H_1`, `MEMCPYD2H_2`, ... | Streaming D2H channels. Bind to a `fabout_dsd`. |

The streaming colors are `color` values; use them via `@get_color(@bitcast(u16, sys_mod.MEMCPYH2D_1))` when constructing `fabin_dsd` / `fabout_dsd`. See [SKILL-DSDS.md](SKILL-DSDS.md) for the bind patterns.

### Host side: SdkRuntime

```python
#!/usr/bin/env cs_python
import argparse
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import (
    SdkRuntime, MemcpyDataType, MemcpyOrder,
)

parser = argparse.ArgumentParser()
parser.add_argument('--name',   help="compile output dir")
parser.add_argument('--cmaddr', help="IP:port for real CS system; omit for simulator")
args = parser.parse_args()

runner = SdkRuntime(args.name, cmaddr=args.cmaddr)

# Resolve names declared by @export_name + @export_symbol to integer IDs
A_id = runner.get_id('A')
y_id = runner.get_id('y')

runner.load()                # load binary to device / simulator
runner.run()                 # start execution loop

# Bulk H2D copy
A = np.arange(M*N, dtype=np.float32)
runner.memcpy_h2d(
    A_id, A,                                       # dest id, source array
    0, 0, 1, 1, M*N,                               # px, py, w, h, elem_per_pe
    streaming=False,
    order=MemcpyOrder.ROW_MAJOR,
    data_type=MemcpyDataType.MEMCPY_32BIT,
    nonblock=False,
)

# RPC: call a function that was @export_name'd as fn()void
runner.launch('compute', nonblock=False)

# Bulk D2H copy
y = np.zeros([M], dtype=np.float32)
runner.memcpy_d2h(
    y, y_id,
    0, 0, 1, 1, M,
    streaming=False,
    order=MemcpyOrder.ROW_MAJOR,
    data_type=MemcpyDataType.MEMCPY_32BIT,
    nonblock=False,
)

runner.stop()
```

### `memcpy_h2d` / `memcpy_d2h` argument reference

```python
runner.memcpy_h2d(
    dest,          # int symbol id (h2d) or numpy array (d2h)
    src,           # numpy array (h2d) or int symbol id (d2h)
    px, py,        # PE-grid origin of the target region (column, row)
    w, h,          # region extent in PEs
    elem_per_pe,   # elements per PE — total = w * h * elem_per_pe
    streaming,     # False: copy to a named symbol. True: stream over a memcpy color.
    order,         # MemcpyOrder.ROW_MAJOR or COL_MAJOR — host-array memory order
    data_type,     # MemcpyDataType.MEMCPY_16BIT or MEMCPY_32BIT
    nonblock,      # True: return a Task handle immediately; False: block until done
)
```

When `streaming=True`, `dest`/`src` is the memcpy color id (e.g. `MEMCPYH2D_DATA_1` read from the compile metadata) rather than a kernel symbol id — see *Streaming pattern* below.

### Broadcast variants

```python
runner.memcpy_h2d_rowbcast(...)    # one row-vector broadcast to all rows
runner.memcpy_h2d_colbcast(...)    # one column-vector broadcast to all columns
runner.memcpy_h2d_stride(row_stride=s, col_stride=s, ...)
```

Useful when the same data goes to every PE in a row/column without the host having to manually replicate it.

### `launch` — calling a kernel function

```python
task = runner.launch('init_and_compute', nonblock=False)
# additional positional arguments are forwarded as RPC arguments to the kernel function
task = runner.launch('init_and_compute', 42, nonblock=False)
```

For this to work, the function must be both `@export_name`'d in the layout (`@export_name("init_and_compute", fn()void)`) and `@export_symbol`'d in the PE comptime block. Multi-arg signatures must match exactly.

### `nonblock` and task handles

Every transfer/launch accepts `nonblock=True`, returning a `Task` handle:

```python
task = runner.memcpy_h2d(..., nonblock=True)
# ... overlap other work ...
runner.task_wait(task)
# or:
while not runner.is_task_done(task):
    ...
```

Without `nonblock=True`, the call blocks until the device acks the transfer.

## Model 2 — Streaming memcpy (a hybrid)

When data flow naturally fits the fabric, you can let memcpy *stream* through a fabric color rather than copying to a named buffer. The PE program receives wavelets on the streaming color via a `fabin_dsd` (or sends via a `fabout_dsd`):

### PE side

```csl
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);

const h2d_x_iq: input_queue = @get_input_queue(2);   // WSE-3 binding

// fabin_dsd reading from the streaming H2D color
const x_in_dsd = @get_dsd(fabin_dsd, if (@is_arch("wse3")) .{
  .extent = N_per_PE, .input_queue = h2d_x_iq,
} else .{
  .extent = N_per_PE,
  .fabric_color = @get_color(@bitcast(u16, sys_mod.MEMCPYH2D_1)),
  .input_queue = h2d_x_iq,
});

const memcpy_recv_x_task_id: data_task_id =
  if      (@is_arch("wse2")) @get_data_task_id(@get_color(@bitcast(u16, sys_mod.MEMCPYH2D_1)))
  else if (@is_arch("wse3")) @get_data_task_id(h2d_x_iq);

task recv_x(x_val: f32) void { /* runs per-wavelet */ }

comptime {
  @bind_data_task(recv_x, memcpy_recv_x_task_id);
  if (@is_arch("wse3"))
    @initialize_queue(h2d_x_iq, .{ .color = @get_color(@bitcast(u16, sys_mod.MEMCPYH2D_1)) });
}
```

For D2H streaming, build a `fabout_dsd` against `MEMCPYD2H_1` and write to it; the host reads with `memcpy_d2h(..., streaming=True)`.

### Host side: streaming `memcpy_h2d` / `memcpy_d2h`

The destination/source id is the memcpy *color*, surfaced through the compile metadata in `out.json`:

```python
import json
with open(f"{args.name}/out.json", encoding='utf-8') as f:
    cd = json.load(f)

MEMCPYH2D_DATA_1 = int(cd['params']['MEMCPYH2D_DATA_1_ID'])
MEMCPYD2H_DATA_1 = int(cd['params']['MEMCPYD2H_DATA_1_ID'])
N_per_PE = int(cd['params']['N']) // int(cd['params']['kernel_x_dim'])

# Stream x to a column of PEs
runner.memcpy_h2d(
    MEMCPYH2D_DATA_1, x,
    0, 0, kernel_x_dim, 1, N_per_PE,
    streaming=True,
    order=MemcpyOrder.ROW_MAJOR, data_type=MemcpyDataType.MEMCPY_32BIT,
    nonblock=False,
)

# Stream y back from the right column
y = np.zeros([M], dtype=np.float32)
runner.memcpy_d2h(
    y, MEMCPYD2H_DATA_1,
    kernel_x_dim-1, 0, 1, kernel_y_dim, M_per_PE,
    streaming=True,
    order=MemcpyOrder.ROW_MAJOR, data_type=MemcpyDataType.MEMCPY_32BIT,
    nonblock=False,
)
```

Reading from `out.json` is the right way to plumb compile-time parameter values to the host — never hardcode them.

## Model 3 — SdkLayout (Python-driven layout + streams)

Used when you want the layout (rectangle, routes, ports) declared in Python rather than `layout.csl`. The kernel file becomes a tiny per-PE program; everything topological is host-side.

```python
from cerebras.sdk.runtime.sdkruntimepybind import (
    Color, Edge, Route, RoutingPosition,
    SdkLayout, SdkTarget, SdkRuntime, SimfabConfig, get_platform,
)

config = SimfabConfig(dump_core=True)
target = SdkTarget.WSE3 if args.arch == 'wse3' else SdkTarget.WSE2
platform = get_platform(args.cmaddr, config, target)
layout  = SdkLayout(platform)

rx1 = Color('rx1'); rx2 = Color('rx2'); tx = Color('tx')

receiver_routes = RoutingPosition().set_output([Route.RAMP])
sender_routes   = RoutingPosition().set_input ([Route.RAMP])

add2vec = layout.create_code_region('./add2vec.csl', 'add2vec', 1, 1)
add2vec.set_param_all('size', size)
add2vec.set_param_all(rx1); add2vec.set_param_all(rx2); add2vec.set_param_all(tx)

rx1_port = add2vec.create_input_port (rx1, Edge.RIGHT, [receiver_routes], size)
rx2_port = add2vec.create_input_port (rx2, Edge.RIGHT, [receiver_routes], size)
tx_port  = add2vec.create_output_port(tx,  Edge.LEFT,  [sender_routes],   size)
add2vec.place(7, 4)                               # place region at fabric (7, 4)

in_stream1 = layout.create_input_stream(rx1_port)
in_stream2 = layout.create_input_stream(rx2_port)
out_stream = layout.create_output_stream(tx_port)

artifacts = layout.compile(out_prefix='out', cslc_prefix=args.cslc_prefix)

runtime = SdkRuntime(artifacts, platform, memcpy_required=False)
runtime.load(); runtime.run()

runtime.send   (in_stream1, data1, nonblock=True)
runtime.send   (in_stream2, data2, nonblock=True)
runtime.receive(out_stream, actual, size, nonblock=True)

runtime.stop()
```

Highlights:

- `SdkLayout(platform)` is the imperative layout builder.
- `create_code_region(file, name, width, height)` instantiates a chunk of identical PEs.
- `create_input_port(color, edge, [routing], n_wavelets)` exposes a port on the named fabric edge (`Edge.LEFT/RIGHT/TOP/BOTTOM`).
- `create_input_stream(port)` returns a stream handle the host uses with `runner.send` / `runner.receive`.
- `SdkRuntime(artifacts, platform, memcpy_required=False)` disables the memcpy infrastructure (no `<memcpy/...>` imports needed in the kernel; you must not call `unblock_cmd_stream()` either).

See `examples/tutorials/sdklayout-*` for progressively more complex SdkLayout setups.

## Direct-link send / receive (streams)

Whether the layout came from CSL (`@export_name`) or SdkLayout (`create_*_stream`), the host side uses:

```python
# Wavelets in
task = runner.send(port_or_stream, src_array, n_wavelets=count, nonblock=False)
# (n_wavelets is auto-inferred from the array length if omitted)

# Wavelets out
task = runner.receive(port_or_stream, dest_array, n_wavelets=count, nonblock=False)

# Stream to a file directly
task = runner.receive_tofile(port_or_stream, outfile="data.bin", nonblock=False)
```

`get_port_id` and `report_port_infos` enumerate ports if you need to discover them at runtime.

## Reading compile metadata from `out.json`

Every compile produces `<out_dir>/out.json` containing the resolved `param` values, fabric dims, and memcpy color IDs. The host reads it to size buffers and discover streaming colors:

```python
with open(f"{args.name}/out.json") as f:
    cd = json.load(f)

N = int(cd['params']['N'])
kernel_x_dim = int(cd['params']['kernel_x_dim'])
MEMCPYH2D_DATA_1 = int(cd['params']['MEMCPYH2D_DATA_1_ID'])
```

Hardcoding parameters on the host that the kernel resolves at compile time is the second most common source of "the test passes locally but fails when I change N" bugs.

## Debugging helpers

Simulator-only:

```python
runner.dump_core("corefile.cs1")              # for csdb post-mortem
runner.dump_elf_core("corefile")
value = runner.read_symbol(x, y, "name", dtype="uint32")   # peek at a PE's memory
```

Utility functions for shaping host arrays to wavelet format:

```python
from cerebras.sdk.sdk_utils import calculate_cycles, memcpy_view, input_array_to_u32

cycles = calculate_cycles(timestamp_buf)              # from a <time>-stamped buffer
view   = memcpy_view(array_32bit, np.float16)         # reinterpret 32-bit elements as f16 pairs
u32s   = input_array_to_u32(array_16bit, sentinel=None, fast_dim_sz=N)   # pack into wavelets
```

## SdkRuntime lifecycle, in one place

```
runner = SdkRuntime(name_or_artifacts, cmaddr=..., suppress_simfab_trace=..., simfab_numthreads=..., msg_level=...)
runner.load()                                   # binary onto device/simulator
runner.run()                                    # PEs start their tasks; command stream open
# ... transfers, launches, sends, receives ...
runner.stop()                                   # drain pending tasks, tear down
```

Constructor parameters:

| Param | Purpose |
|---|---|
| `name` (or artifacts) | Path to compile output dir, OR an `SdkCompileArtifacts` (with `SdkLayout`). |
| `cmaddr` | `"IP:PORT"` for a real wafer. Omit/`None` for the simulator. |
| `suppress_simfab_trace` | `True` to skip generating simfab traces (faster simulator). |
| `simfab_numthreads` | Default 5, max 64. Higher = faster simulator on bigger fabrics. |
| `msg_level` | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`. |
| `memcpy_required` | `False` to disable memcpy infrastructure for SdkLayout programs. |

## Gotchas

- **Forgetting `sys_mod.unblock_cmd_stream()`** at the end of a `launch`-called function: every subsequent host command hangs. Single most common bug. The function isn't optional; it tells memcpy that it can dispatch the next command.
- **`@export_name` types must match the host's expectations.** If a kernel exports `[*]f32` but the host array is `np.float64`, the transfer succeeds with garbage and you'll chase the bug for hours.
- **`elem_per_pe` is per-PE, total is `w * h * elem_per_pe`.** When migrating from a single-PE to a multi-PE program this is the most common off-by-N error.
- **`streaming=True` uses the memcpy *color* id, not a symbol id.** Pull the color id from `out.json` — never hardcode.
- **`order=ROW_MAJOR` is the host-array memory order, not the device layout.** Combined with `transpose`/`reshape` calls on the numpy side, this is where `gemv-09`-style layouts get tricky; read `run.py` carefully when porting.
- **`@export_symbol` lives inside `comptime { }`.** Outside it: compile error or silent missing-symbol at host load.
- **`get_id` for a name that isn't `@export_name`'d in the layout** returns garbage; the host will then send memcpy commands into the void. Always cross-check the names appear in both layout and the PE comptime block.
- **The host running `cs_python run.py` is *inside* the SIF.** Don't expect `pip install numpy` on macOS to take effect — `cs_python` brings its own numpy. To add packages, use the `cs_pip_install.sh` helper (see [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md)).
- **`SdkRuntime(memcpy_required=False)` is only valid with SdkLayout.** Don't pass it for memcpy-based programs.
- **Multiple `launch` calls without `task_wait` between them are serialized by the runtime**, but only because the command stream itself is serial. Pretending they run in parallel will surprise you on real hardware.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry.
- [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) — compiling against memcpy, `--memcpy --channels N` flags, `--fabric-dims` math accounting for memcpy halo.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `fabin_dsd` / `fabout_dsd` patterns for memcpy streaming.
- [SKILL-TASKS.md](SKILL-TASKS.md) — `@bind_data_task` for the streaming-channel receive task.
- [SKILL-MODULES.md](SKILL-MODULES.md) *(planned)* — `@import_module` semantics and parameterization patterns.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)* — wiring memcpy-color routes into the fabric in non-trivial layouts.
- Working `run.py` examples: bundled `gemv-03-memcpy` (bulk memcpy + launch), `gemv-09-streaming` (streaming + out.json metadata), `sdklayout-04-h2d-d2h` (SdkLayout streams).
- Upstream API docs: <https://sdk.cerebras.net/api-docs/sdkruntime-api>
