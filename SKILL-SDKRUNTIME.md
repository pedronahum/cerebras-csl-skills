---
name: csl-sdkruntime
description: Reference for the Cerebras SDK runtime — the host-side Python/C++ API that drives a compiled CSL program. Use when writing run.py / host scripts, when picking between memcpy and SdkLayout integration models, when chasing get_id / get_port_id mismatches, when reading the meaning of a kwarg, or when porting from one SDK version to another. Pinned to SDK 2.10.0; cross-check `_generated/SDK-VERSION.txt` against the installed SIF before trusting specifics.
---

# SDK Runtime: Host-Side Reference

Companion to [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md). That file is the *narrative* — when to reach for memcpy vs streams, what `unblock_cmd_stream()` does, the three integration models. **This** file is the *reference* — every public class, every constructor, every method (with overloads), pinned to a specific SDK build so the contract doesn't drift on you silently.

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

The full pinned dump (every signature, every overload, demangled C++ symbols from `/cbcore/lib`) is checked in next to this file:

- `_generated/sdkruntime-surface.json` — Python pybind11 view.
- `_generated/sdkruntime-symbols.txt` — C++ demangled symbol view (10 runtime `.so` libs).
- `_generated/SDK-VERSION.txt` — one-page provenance summary.

Regenerate with `scripts/refresh_sdk_surface.sh`. If the SDK on disk is a different build, regenerate first and treat this file's specifics as advisory until the diff is read.

Quick check that this file's pin matches the installed SDK:

```sh
shasum -a 256 "$(dirname "$(command -v cs_python)")"/sdk-cbcore-*.sif
# should match the sif_sha256 above; if not, refresh and audit drift
```

## Module map

| Module | Purpose | Detailed in |
|---|---|---|
| `cerebras.sdk.runtime.sdkruntimepybind` | Main public surface: `SdkRuntime`, `SdkLayout`, types, enums. | this file + drilled chapters |
| `cerebras.sdk.runtime.routepybind` | Lower-level memcpy-routing primitive (`CslIoRouting`). | [SKILL-SDKRUNTIME-ROUTE.md](SKILL-SDKRUNTIME-ROUTE.md) |
| `cerebras.sdk.runtime.cslwse{netlist,pintable,router,routeasm}` | Python wrappers that build `MEMCPY_XY_ROUTES.elf`. | [SKILL-SDKRUNTIME-ROUTE.md](SKILL-SDKRUNTIME-ROUTE.md) |
| `cerebras.sdk.debug.lib.symbol.csldebugpybind` | Symbol-table queries against compiled ELFs. | SKILL-SDKRUNTIME-DEBUG.md *(planned)* |
| `cerebras.sdk.debug.lib.instruction_trace.sdkinstrtracepybind` | Instruction-trace parsing. | SKILL-SDKRUNTIME-DEBUG.md *(planned)* |
| `cerebras.sdk.debug.lib.rectangleopspybind` | Rectangle ops on dump cores. | SKILL-SDKRUNTIME-DEBUG.md *(planned)* |
| `cerebras.sdk.debug.lib.wavelet_trace.wavelettracepybind` | Wavelet-trace parsing. | SKILL-SDKRUNTIME-DEBUG.md *(planned)* |
| `cerebras.sdk.sdk_utils` | Pure-Python helpers (`memcpy_view`, `input_array_to_u32`, …). | SKILL-SDK-UTILS.md *(planned)* |

## API surface (`sdkruntimepybind`)

### Classes

| Name | Kind | Purpose |
|---|---|---|
| `SdkRuntime` | class | Runtime driver — load/run/stop, memcpy, RPC, streams, debug. 22 callable methods. |
| `SdkLayout` | class | Python-side layout builder (alternative to `layout.csl`). |
| `CodeRegion` | class | A grid of identical PEs inside an `SdkLayout`. |
| `SdkCompileArtifacts` | class | Output of `SdkLayout.compile()`; consumed by `SdkRuntime`. |
| `SdkExecutionPlatform` | class | Platform handle (simulator/system); built by `get_platform`. |
| `SimfabConfig` | class | Simulator config — thread count, trace suppression, core-dump policy. |
| `Color` | class | Named fabric color used in routing. |
| `RoutingPosition` | class | One row in a routing table (`.set_input([Route...])`, `.set_output([...])`). |
| `EdgeRouteInfo` | class | Per-edge routing summary. |
| `PortHandle` | class | Reference to an SdkLayout-created port. |
| `Task` | class | Handle returned by every non-blocking call; pass to `task_wait` / `is_task_done`. |

### Enums

| Name | Values |
|---|---|
| `SdkTarget` | `WSE2=0`, `WSE3=1` |
| `MemcpyDataType` | `MEMCPY_32BIT=0`, `MEMCPY_16BIT=1` |
| `MemcpyOrder` | `ROW_MAJOR=0`, `COL_MAJOR=1` |
| `Edge` | `TOP=0`, `BOTTOM=1`, `LEFT=2`, `RIGHT=3` |
| `Route` | `RAMP=0`, `EAST=1`, `WEST=2`, `NORTH=3`, `SOUTH=4` |
| `FP16TYPE` | `F16=0`, `BF16=1`, `CB16=2` |

The numeric values are stable for SDK 2.10.0 but **never hardcode them** — always reference them by name. The values are listed here only so a maintainer reading a hex dump can sanity-check.

Each enum member is also re-exported at module scope (so `m.WSE3` and `m.SdkTarget.WSE3` are the same value).

### Free functions

| Name | Signature (Python) |
|---|---|
| `get_platform` | `get_platform(addr: Optional[str] = None, config: SimfabConfig = SimfabConfig(), target: SdkTarget = SdkTarget.WSE3) -> SdkExecutionPlatform` |
| `get_simulator` | `get_simulator(config: SimfabConfig = ..., target: SdkTarget = SdkTarget.WSE3) -> SdkExecutionPlatform` |
| `get_system` | `get_system(addr: str) -> SdkExecutionPlatform` |
| `get_edge_routing` | Computes a standard `[RoutingPosition]` list for a given edge + direction. |

Note the **default target is WSE3**. WSE2 has to be selected explicitly via `get_platform(target=SdkTarget.WSE2)` or `get_simulator(target=SdkTarget.WSE2)`. `get_system` does not accept a target — the real CS hardware reports its own generation.

## Lifecycle

```
                  ┌── memcpy program ──┐         ┌── SdkLayout program ──┐
                  │                    │         │                       │
cslc → out/       │ name = 'out'       │         │ layout.compile() →    │
                  │                    │         │   SdkCompileArtifacts │
                  ↓                    ↓         ↓                       ↓
            SdkRuntime(name, **kwargs)        SdkRuntime(artifacts, platform,
                                                         memcpy_required=False, ...)
                  │
                  ▼
                load()         ← copy binary onto device / simulator
                  │
                  ▼
                run()          ← PEs start; command stream open
                  │
        ┌─────────┼─────────────┐
        ▼         ▼             ▼
   memcpy_h2d   launch       send / receive       ← repeat as needed
   memcpy_d2h   call         receive_tofile
        │         │             │
        └─────────┼─────────────┘
                  ▼
                stop()         ← drain pending tasks + tear down
```

### Constructor — `SdkRuntime`

Three overloads (from `_generated/sdkruntime-surface.json`):

```
SdkRuntime(name: str, **kwargs)
SdkRuntime(name: str, platform: SdkExecutionPlatform, **kwargs)
SdkRuntime(artifacts: SdkCompileArtifacts, platform: SdkExecutionPlatform, **kwargs)
```

Documented `**kwargs` (resolved by the C++ side, not visible in the bare pybind signature):

| Kwarg | Default | Purpose |
|---|---|---|
| `cmaddr` | `None` | `"host:port"` for a real CS system. Omit / `None` selects the simulator. |
| `suppress_simfab_trace` | `False` | `True` to skip generating simfab traces — faster simulator. |
| `simfab_numthreads` | (defers to platform) | Simulator thread count. Max 64. See also `SimfabConfig.num_threads`. |
| `msg_level` | `"WARNING"` | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`. |
| `memcpy_required` | `True` | `False` only for SdkLayout-only programs. Passing `False` to a memcpy program hangs `load()`. |

The two argument shapes — compile-dir *name* (`str`) vs `SdkCompileArtifacts` — are not interchangeable. memcpy programs go through the file path overload; SdkLayout programs go through the artifacts overload. Crossing wires triggers a misleading error somewhere inside `load()`.

### Constructor — `SdkLayout`

```
SdkLayout(platform: SdkExecutionPlatform, *, msg_level: str = 'WARNING')
SdkLayout(path: str, *, msg_level: str = 'WARNING')
SdkLayout(target: SdkTarget, *, msg_level: str = 'WARNING')
```

The `target`-only overload is a convenience that builds a default `SdkExecutionPlatform` internally — fine for quick simulator runs, not for real CS systems (no `cmaddr` argument).

### Constructor — `SimfabConfig`

```
SimfabConfig(
    num_threads: int = 16,
    suppress_trace: bool = False,
    dump_core: bool = False,
    core_path: Optional[Path] = None,
)
```

**Default `num_threads=16`** — that is the truth as of SDK 2.10.0. Older skill notes mentioning `5` are stale.

`dump_core=True` is the prerequisite for the post-mortem debug flow (`SdkRuntime.dump_core()` plus `csdb`).

## `SdkRuntime` methods at a glance

22 callable methods. Grouped by purpose:

| Group | Methods |
|---|---|
| **Lifecycle** | `load`, `run`, `stop` |
| **Memcpy (bulk + streaming)** | `memcpy_h2d`, `memcpy_d2h`, `memcpy_h2d_rowbcast`, `memcpy_h2d_colbcast`, `memcpy_h2d_stride` |
| **RPC** | `launch`, `call` |
| **Streams (SdkLayout ports)** | `send` *(5 overloads)*, `receive` *(2)*, `receive_tofile` *(2)* |
| **Symbol resolution** | `get_id`, `get_port_id`, `report_port_infos` |
| **Task handles** | `task_wait`, `is_task_done` |
| **Debug** | `dump_core`, `dump_elf_core`, `read_symbol`, `coord_logical_to_physical` |

Every memcpy / stream / RPC method returns a `Task`. With `nonblock=False` (the default) the call blocks until the device acks; with `nonblock=True` it returns immediately and you wait via `task_wait(task)` or poll with `is_task_done(task)`.

## Minimal example — memcpy model

```python
#!/usr/bin/env cs_python
import argparse, numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import (
    SdkRuntime, MemcpyDataType, MemcpyOrder,
)

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--cmaddr")
args = ap.parse_args()

rt = SdkRuntime(args.name, cmaddr=args.cmaddr)
rt.load()
rt.run()

N = 64
data = np.arange(N, dtype=np.float32)
rt.memcpy_h2d(
    rt.get_id("A"), data, 0, 0, 1, 1, N,
    streaming=False, order=MemcpyOrder.ROW_MAJOR,
    data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False,
)

rt.launch("compute", nonblock=False)

out = np.zeros(N, dtype=np.float32)
rt.memcpy_d2h(
    out, rt.get_id("y"), 0, 0, 1, 1, N,
    streaming=False, order=MemcpyOrder.ROW_MAJOR,
    data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False,
)

rt.stop()
```

## Minimal example — SdkLayout model

```python
from cerebras.sdk.runtime.sdkruntimepybind import (
    Color, Edge, Route, RoutingPosition,
    SdkLayout, SdkTarget, SdkRuntime, SimfabConfig, get_platform,
)

target   = SdkTarget.WSE3
config   = SimfabConfig(dump_core=True)
platform = get_platform(addr=None, config=config, target=target)
layout   = SdkLayout(platform)

rx = Color('rx'); tx = Color('tx')

region = layout.create_code_region('./kernel.csl', 'k', 1, 1)
region.set_param_all('size', 64)
region.set_param_all(rx); region.set_param_all(tx)

rx_port = region.create_input_port (rx, Edge.LEFT,  [RoutingPosition().set_output([Route.RAMP])], 64)
tx_port = region.create_output_port(tx, Edge.RIGHT, [RoutingPosition().set_input ([Route.RAMP])], 64)
region.place(0, 0)

in_stream  = layout.create_input_stream(rx_port)
out_stream = layout.create_output_stream(tx_port)

artifacts = layout.compile(out_prefix='out')
rt = SdkRuntime(artifacts, platform, memcpy_required=False)
rt.load(); rt.run()

rt.send   (in_stream,  np.arange(64, dtype=np.float32), nonblock=True)
rt.receive(out_stream, dest := np.zeros(64, dtype=np.float32), 64, nonblock=False)
rt.stop()
```

## Reading the C++ side

The SDK ships only stripped `.so` files; there are no headers. The pinned dump captures the demangled C++ symbol surface so each Python method can be cross-referenced. Two patterns recur and matter for understanding the Python API:

1. **`MemcpyOptions` struct hidden behind Python kwargs.** Every C++ `memcpy_*` method ends in `const cerebras::MemcpyOptions&`. pybind splats this struct's fields into Python kwargs — which is why `streaming=`, `order=`, `data_type=`, `nonblock=` are required keyword-only in Python but invisible in the bare pybind signature.

   ```
   C++:    SdkRuntime::memcpy_h2d(unsigned short, void*, int, int, int, int, int,
                                  const MemcpyOptions&)
   Python: memcpy_h2d(dest_id, src, px, py, w, h, elem_per_pe,
                      *, streaming, order, data_type, nonblock)
   ```

2. **String-name vs id overloads on stream methods.** `send`, `receive`, `receive_tofile` each have two C++ overloads — one taking a port *name* (`std::string`), one taking a numeric port *id* (`unsigned short`). Python sees 2-5 overloads (some methods add typed numpy variants on top).

   ```
   C++:    SdkRuntime::send(std::string const&, void const*, unsigned long, bool)
   C++:    SdkRuntime::send(unsigned short, void const*, unsigned long, bool)
   Python: send(port_name_or_id, array, n_wavelets, nonblock=False)
   ```

   The first positional argument can be the string returned by `create_*_port` (named) or the int from `get_port_id` — they resolve to the same backend.

3. **Numeric-id arguments are `unsigned short` (u16) in C++.** Symbol IDs, port IDs, and memcpy-stream-color IDs all fit in 16 bits. Passing a Python `int` that overflows u16 produces an OverflowError from pybind before the call gets near the device — easy to misread as a runtime bug.

The full C++ symbol view for cross-reference is in `_generated/sdkruntime-symbols.txt`, sectioned by `.so`:

```
## /cbcore/lib/libsdkruntime.so
cerebras::SdkRuntime::launch(...)
cerebras::SdkRuntime::memcpy_h2d(unsigned short, void*, int, int, int, int, int,
                                 cerebras::MemcpyOptions const&)
...
## /cbcore/lib/libsdk_layout.so
cerebras::SdkLayout::CodeRegion::create_input_port(
    cerebras::SdkLayout::Color const&, cerebras::SdkLayout::Edge,
    std::vector<cerebras::SdkLayout::RoutingPosition> const&,
    unsigned long, std::string const&)
...
```

## Drilled-down chapters (planned, in the order they will land)

| Chapter | Covers |
|---|---|
| [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) | `SdkRuntime` — every method, every overload, every kwarg, the matching C++ signature, failure modes. |
| [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md) | `SdkLayout`, `CodeRegion`, `create_*_port`, `create_*_stream`, `place`, `paint`, `set_param_all`, `compile`. |
| [SKILL-SDKRUNTIME-TYPES.md](SKILL-SDKRUNTIME-TYPES.md) | `Task`, `SimfabConfig`, `SdkExecutionPlatform`, `SdkCompileArtifacts`, all enums. |
| [SKILL-SDKRUNTIME-DEBUG.md](SKILL-SDKRUNTIME-DEBUG.md) | `dump_core` / `dump_elf_core` / `read_symbol` workflow + the four debug pybind modules. |
| [SKILL-SDK-UTILS.md](SKILL-SDK-UTILS.md) | `cerebras.sdk.sdk_utils` — `memcpy_view`, `input_array_to_u32`, `calculate_cycles`, RPC schema parsing. |

Until those land, the authoritative per-method shape is in `_generated/sdkruntime-surface.json` (Python view) and `_generated/sdkruntime-symbols.txt` (C++ view) — both pinned to the same SDK build as this file.

## Gotchas (entry-level — drilled chapters add more)

- **Bare pybind signatures lie about kwargs.** A signature like `memcpy_h2d(self, arg0: int, arg1: numpy.ndarray, ..., arg6: int, **kwargs)` is *truth* about what pybind exposes, but every real call also needs `streaming=`, `order=`, `data_type=`, `nonblock=`. They live in `MemcpyOptions` on the C++ side. The drilled chapters list both views side-by-side; do not rely on Python `help()` alone.
- **`name` vs `SdkCompileArtifacts` is not interchangeable.** Memcpy programs use `SdkRuntime("out")`; SdkLayout programs use `SdkRuntime(artifacts, platform, memcpy_required=False)`.
- **`memcpy_required=False` is *only* valid with SdkLayout.** Passing it to a memcpy program hangs `load()`.
- **`get_id("name")` returns `Optional[int]`.** A `None` return means the name wasn't `@export_name`'d in the layout. Don't blindly pass the result into `memcpy_h2d` — check for `None`.
- **`Task` handles are not interchangeable across runtimes.** Each `SdkRuntime` instance has its own task arena. Cross-mixing produces an opaque "invalid task" error.
- **`stop()` is mandatory before process exit.** The simulator otherwise leaks file descriptors and named sockets that future `cs_python` invocations stumble on.
- **Pybind overloads dispatch by static type.** Passing `np.float64` to a method overloaded only for `float32` / `int32` / `uint32` raises `TypeError` with a multi-line "no overload matched" message. The dtype list per overload is in `_generated/sdkruntime-surface.json`.
- **`SdkTarget` defaults to WSE3.** WSE2 has to be selected explicitly via `get_platform(target=SdkTarget.WSE2)` (or `get_system(addr, target=SdkTarget.WSE2)`). Running a WSE2-compiled binary against a WSE3 platform handle silently mis-routes.
- **`SimfabConfig.num_threads` default is 16, not 5.** Older notes (and an earlier version of this skill bundle) claimed 5; that was wrong.

## See also

- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — narrative: when to use memcpy vs SdkLayout, `unblock_cmd_stream()` rule, `out.json` metadata reading.
- [SKILL-DSDS.md](SKILL-DSDS.md) — PE-side companion: `fabin_dsd` / `fabout_dsd` consume the memcpy streaming colors.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) — fabric routes / colors / CE injection from the PE side.
- [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) — compiling against memcpy, `--memcpy --channels N`, fabric dim math.
- `_generated/sdkruntime-surface.json` — every Python signature, machine-readable, pinned.
- `_generated/sdkruntime-symbols.txt` — every demangled C++ symbol from 10 `/cbcore/lib/*.so` libs, pinned.
- `_generated/SDK-VERSION.txt` — pinned SDK metadata + per-module surface counts.
- Upstream API docs: <https://sdk.cerebras.net/api-docs/sdkruntime-api> (often lags a release behind this dump).
