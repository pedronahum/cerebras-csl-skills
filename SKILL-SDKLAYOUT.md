---
name: csl-sdklayout
description: Reference for the SdkLayout family — Python-side fabric layout, code regions, ports, streams, and routes. Covers SdkLayout, CodeRegion, Color, RoutingPosition, Edge, Route, EdgeRouteInfo, PortHandle, SdkCompileArtifacts, SdkExecutionPlatform, and the get_platform / get_simulator / get_system / get_edge_routing free functions. Use when building a layout in Python instead of layout.csl, when wiring ports between regions, when overriding routing on specific edges, or when reading an SdkLayout-driven host script. Pinned to SDK 2.10.0.
---

# `SdkLayout`: Python-Side Layout, Regions, Ports, Routes

`SdkLayout` is the alternative to writing a `layout.csl` file. Where the CSL-side layout block is declarative (you say "place this code at (x, y)" in CSL syntax), `SdkLayout` is imperative Python — you build code regions, paint colors with routing tables, create ports on the edges, and stitch them into streams. The compiled output is an `SdkCompileArtifacts` that `SdkRuntime` consumes (with `memcpy_required=False`).

For the narrative on *when* to use SdkLayout vs `layout.csl`, see [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md). For the runtime-side methods (`send`, `receive`, `get_port_id`, …) that consume the names this file produces, see [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md).

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

Every signature in this file came from that SIF via `scripts/refresh_sdk_surface.sh`. If the SIF on disk is different, refresh `_generated/` first.

## When to use which

| If you want | Reach for |
|---|---|
| A small program where the PE topology fits one `@set_rectangle(w, h)` and standard memcpy | `layout.csl` + memcpy. Simpler, fewer moving parts. |
| Explicit Python control over PE coordinates, custom routing tables, or multiple distinct code regions | `SdkLayout`. The whole topology is reified in Python. |
| Custom streaming-port topology — wavelets flowing in/out on specific edges of specific regions | `SdkLayout` (memcpy can't express this). |
| Mixed: bulk h2d for parameters, streaming for the data flow | Both can be combined; see SKILL-HOST-DEVICE.md's "Model 2 — Streaming memcpy". |

## Layout flow

```
  get_platform / get_simulator / get_system
              │
              ▼
       SdkExecutionPlatform ────┐
                                ▼
                          SdkLayout(platform, msg_level=…)
                                │
                                ▼
                    layout.create_code_region(src, name, w, h)
                                │
                                ▼
                          CodeRegion ─── set_param_all / set_symbol_all (init params + symbols)
                                │
                                ├── paint_all(color, routes)            ← routing tables
                                │   paint_range(rect, color, routes)
                                │   paint     (pe,   color, routes)
                                │
                                ├── create_input_port (color, edge, [routes], size, prefix)
                                │   create_output_port(color, edge, [routes], size, prefix)  → PortHandle
                                │
                                └── place(x, y)                         ← anchor to fabric coords
                                │
                                ▼
                    layout.create_input_stream(port, io_loc=…, io_buffer_size=1024)  → stream-name str
                    layout.create_output_stream(port, io_loc=…, io_buffer_size=1024) → stream-name str
                    layout.connect(port_a, port_b)                      ← direct region-to-region wiring
                                │
                                ▼
                    layout.compile(out_prefix, libs=[], cslc_prefix='',
                                   save_port_map=False, f16_type=F16)
                                │
                                ▼
                          SdkCompileArtifacts
                                │
                                ▼
                    SdkRuntime(artifacts, platform, memcpy_required=False)
```

Order matters mainly for `place(x, y)` and `compile()` — everything else is mutable until you compile. `place` is idempotent (call again to move a region before compile). `compile` is one-shot.

## `SdkLayout`

### Construction

Three overloads:

```python
SdkLayout(platform: SdkExecutionPlatform, *, msg_level: str = 'WARNING')
SdkLayout(path:     str,                  *, msg_level: str = 'WARNING')
SdkLayout(target:   SdkTarget,            *, msg_level: str = 'WARNING')
```

- `(platform, …)` — the canonical form. Build the platform first with `get_platform(addr, config, target)` (or `get_simulator` / `get_system`).
- `(path, …)` — load a pre-built layout from a directory on disk. Reuses the topology without rebuilding regions.
- `(target, …)` — convenience that builds a default `SdkExecutionPlatform` for the simulator on that target. Fine for quick simulator runs; not for real systems (no `cmaddr` argument).

`msg_level` is the standard `"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"`.

### `create_code_region(source, name, width, height)` → `CodeRegion`

**Python:** `create_code_region(source: str, name: str, width: int, height: int) -> CodeRegion`
**C++:** `cerebras::SdkLayout::create_code_region(std::string, std::string, int, int)`

`source` is the path to a `.csl` file containing the per-PE program (no layout block — that's the layout's job here). `name` is a unique identifier for the region (used in compile output). `width` / `height` are the region's PE-grid extent.

```python
region = layout.create_code_region('./kernel.csl', 'k', 4, 1)
```

The region is unplaced — call `place(x, y)` to anchor it before `compile()`.

### `connect(port_a, port_b)` → `None`

**Python:** `connect(arg0: PortHandle, arg1: PortHandle) -> None`
**C++:** `cerebras::SdkLayout::connect(PortHandle&, PortHandle&)`

Directly wires two port handles — typically an output port on region A to an input port on region B — without going through a host-visible stream. The runtime never sees the data flowing on this connection; it's pure region-to-region fabric.

### `create_input_stream(port, io_loc=None, io_buffer_size=1024)` → `str`

**Python:**

```
create_input_stream(port: PortHandle,
                    io_loc: Optional[IntVector] = None,
                    io_buffer_size: int = 1024) -> str
```

**C++:** `cerebras::SdkLayout::create_input_stream(PortHandle&, std::optional<IntVector>, unsigned short)`

Adds a host→fabric stream that feeds `port`. The runtime allocates a 1-PE staging region at `io_loc` to buffer data on its way from the host; if `io_loc` is `None`, the runtime picks an available location automatically. `io_buffer_size` is the staging buffer's wavelet capacity (default 1024).

The returned string is the **stream name** — pass it to `runtime.send(stream_name, ...)` later. Or resolve it to an integer id later via `runtime.get_port_id(stream_name)`.

### `create_output_stream(port, io_loc=None, io_buffer_size=1024)` → `str`

Symmetric. Adds a fabric→host stream draining `port`. Same staging-PE / buffer-size semantics. Pass the returned name to `runtime.receive(stream_name, ...)`.

### `create_input_stream_from_loc(loc, color, prefix='')` → `str`

**Python:** `create_input_stream_from_loc(loc: IntVector, c: Color, prefix: str = '') -> str`
**C++:** `cerebras::SdkLayout::create_input_stream_from_loc(IntVector, Color, std::string)`

Lower-level alternative: a code region already exists at `loc` and is set up to consume color `c`. This call just plumbs a host stream into that color at that location, without involving a `PortHandle`. Use when you've manually built the consumer region's routing and don't need the runtime to allocate a staging PE.

### `create_output_stream_from_loc(loc, color, prefix='')` → `str`

Symmetric output variant.

### `hstack(regions)` / `hstack(regions, origin)` → `int`

**Python (2 overloads):**

```
hstack(regions: List[CodeRegion]) -> int
hstack(regions: List[CodeRegion], origin: IntVector) -> int
```

Places `regions` side-by-side horizontally. First form anchors relative to the first child's existing position; second form anchors at `origin`. Returns an opaque int handle (currently unused for downstream calls — placement is the side-effect).

### `vstack(regions)` / `vstack(regions, origin)` → `int`

Vertical counterpart.

### `compile(out_prefix, libs=[], cslc_prefix='', save_port_map=False, f16_type=F16)` → `SdkCompileArtifacts`

**Python:**

```
compile(out_prefix: str,
        libs: List[str] = [],
        cslc_prefix: str = '',
        save_port_map: bool = False,
        f16_type: FP16TYPE = FP16TYPE.F16) -> SdkCompileArtifacts
```

| Arg | Purpose |
|---|---|
| `out_prefix` | Output directory prefix. Compile writes `<out_prefix>/...` with the per-region binaries and a manifest. |
| `libs` | Extra library directories to add to the `cslc` import path (resolves `@import_module("<lib/...>")` lookups). |
| `cslc_prefix` | Path to the `cslc` binary. Empty string means "use the one on `$PATH`". |
| `save_port_map` | `True` to emit a port-name → port-id mapping file. Required if you want to use the `SdkCompileArtifacts(path)` reload path later. |
| `f16_type` | The 16-bit float flavor (`F16`, `BF16`, or `CB16`) the compiled kernels assume. Default `F16`. |

Returns an `SdkCompileArtifacts` consumable by `SdkRuntime(artifacts, platform, memcpy_required=False)`.

## `CodeRegion`

A grid of identical PEs inside an `SdkLayout`. You don't construct it directly — use `layout.create_code_region(...)`.

### `place(x, y)` → `None`

Anchor this region at fabric coordinate `(x, y)`. Idempotent — calling again moves the region. Must be called (directly or via `hstack`/`vstack`) before `compile()`.

### Routing — `paint`, `paint_all`, `paint_range`

`paint_all` is the common case; the other two scope the painting to a single PE or a rectangular subset.

```
paint     (pe:   IntVector,    color: Color, routes: List[RoutingPosition]) -> None
paint_range(rect: IntRectangle, color: Color, routes: List[RoutingPosition]) -> None
paint_all (                     color: Color, routes: List[RoutingPosition])                            -> None
paint_all (                     color: Color, routes: List[RoutingPosition], edge_overrides: List[EdgeRouteInfo]) -> None
```

`paint_all` has a second overload with `edge_overrides: List[EdgeRouteInfo]` — paint the region uniformly except on listed edges, where the override routing applies. Use this when the interior PEs share one route table but the edge PEs need to absorb / source signals differently.

`paint_all` doesn't take an edge argument — the routes apply everywhere. To restrict routing to one edge, use `paint_range` or one of the `paint_all_with_edge_overrides` variants.

### Parameters — `set_param`, `set_param_all`, `set_param_range`

Each has three overloads — set an `unsigned int` value, a `Color` value, or a named-parameter-equal-to-color binding.

```
set_param_all(name: str, value: int)                  -> None        # @param name: i16/u16/i32/u32
set_param_all(color: Color)                            -> None        # binds color by its local-param name
set_param_all(name: str, color: Color)                 -> None        # name = color (explicit name)
```

The `Color`-only form uses `color.get_local_param_name()` as the parameter name — handy when the kernel declares `param tx: color;` and the layout uses a `Color('tx')`. Matching names means one call.

`set_param` is the per-PE variant taking an `IntVector` first. `set_param_range` is the rectangular variant taking an `IntRectangle` first.

### Symbols — `set_symbol_all(name, array, ofs1, ofs2)`

Five typed overloads — `numpy.int16`, `numpy.uint16`, `numpy.int32`, `numpy.uint32`, `numpy.float32`.

```
set_symbol_all(name: str, value: numpy.ndarray[dtype], arg2: int, arg3: int) -> None
```

Initialize a symbol named `name` on every PE in the region with values from the numpy array. The two trailing `int` arguments encode the per-PE slice (offset / count) — the array carries the values for *all* PEs in the region concatenated, and `(arg2, arg3)` parameterize how to slice it per PE. Consult bundled `sdklayout-*` examples in `csl-extras` for the exact slicing semantics; the dump doesn't document the per-arg meaning beyond the positional types.

### Ports

```
create_input_port (color: Color, edge: Edge, routes: List[RoutingPosition], data_size: int, prefix: str = '') -> PortHandle
create_output_port(color: Color, edge: Edge, routes: List[RoutingPosition], data_size: int, prefix: str = '') -> PortHandle
```

Creates a port on `edge` (one of `Edge.LEFT/RIGHT/TOP/BOTTOM`) bound to `color`. `routes` is the per-PE routing along the edge — typically a one-element list `[RoutingPosition().set_input([Route.RAMP])]` or `set_output([Route.RAMP])`. `data_size` is the buffer size in wavelets that the port will reserve. `prefix` namespaces the port's name (`"<prefix>_<auto>"`) to avoid collisions when a layout has multiple regions with same-named colors.

### `color(name)` / `color(name, value)` → `Color`

```
color(name: str)                -> Color
color(name: str, value: int)    -> Color
```

**Creates and returns** a new region-scoped `Color`. (Not a lookup — calling `region.color("rx")` *creates* `rx`; calling it again creates another distinct color.) The optional `value` pins the underlying color id; otherwise the compiler assigns one.

Prefer the module-level `Color(name)` constructor for colors shared across regions; use `region.color(...)` for colors local to one region.

## `Color`

A named fabric color.

```
Color(name: str, value: Optional[int] = None) -> Color

color.get_global_name()       -> str
color.get_local_param_name()  -> str
color.get_value()             -> Optional[int]
```

`get_global_name()` is the cross-region identifier (used in compile manifests). `get_local_param_name()` is the name a kernel program would `param tx: color;`-declare to receive this color. `get_value()` returns the numeric color id if it was pinned at construction (or after compile resolves it); otherwise `None` pre-compile.

## `RoutingPosition`

Routing table for one row of the PE's switch logic. Fluent — setters return `self`.

```
RoutingPosition()                                # empty
.set_input ([Route, Route, ...])  -> RoutingPosition   # replace input edges
.set_output([Route, Route, ...])  -> RoutingPosition   # replace output edges
.add_input (Route)                -> RoutingPosition   # append one input edge
.add_output(Route)                -> RoutingPosition   # append one output edge
.get_input ()                     -> List[Route]
.get_output()                     -> List[Route]
```

The convention in examples:

```python
receiver_routes = RoutingPosition().set_output([Route.RAMP])   # color goes UP to the PE
sender_routes   = RoutingPosition().set_input ([Route.RAMP])   # color comes FROM the PE
```

`Route.RAMP` is the local-PE handle; `EAST` / `WEST` / `NORTH` / `SOUTH` are the four cardinal edges. A wavelet entering on `EAST` and exiting on `RAMP` is consumed by the local PE.

## `Edge` enum

```
Edge.TOP    = 0
Edge.BOTTOM = 1
Edge.LEFT   = 2
Edge.RIGHT  = 3
```

Used for port placement (which edge of the region the port sits on) and for `get_edge_routing`.

## `Route` enum

```
Route.RAMP  = 0      # ↑ to the local PE (or ↓ from it, depending on input/output)
Route.EAST  = 1
Route.WEST  = 2
Route.NORTH = 3
Route.SOUTH = 4
```

These are *fabric* directions, distinct from `Edge` (which names a region's outer edge). A wavelet's path through a PE is `input route → output route(s)`; the two together form a `RoutingPosition`.

## `EdgeRouteInfo`

Opaque marker that describes routing for one edge of a region. Construct via:

```python
info = get_edge_routing(Edge.LEFT, [RoutingPosition().set_output([Route.RAMP])])
```

and pass into `CodeRegion.paint_all(color, routes, [info, ...])` to override routing on that edge only.

## `PortHandle`

Opaque handle returned by `CodeRegion.create_input_port` / `create_output_port`. Pass into `layout.create_input_stream` / `create_output_stream` / `connect`. Not user-constructible.

## `SdkCompileArtifacts`

Produced by `SdkLayout.compile`. Construct from a path to reload:

```python
SdkCompileArtifacts(path: str)
artifacts.add_port_mapping(file: str) -> SdkCompileArtifacts
```

`add_port_mapping` lets you load an additional port-map file (saved with `compile(save_port_map=True)`) — useful when reusing a compiled artifact across runs with different stream definitions.

## `SdkExecutionPlatform`

The platform handle. Construct via the free functions below; query with:

```python
platform.is_simulation() -> bool
platform.is_system()     -> bool
```

## Free functions

### `get_platform(addr=None, config=SimfabConfig(), target=SdkTarget.WSE3)` → `SdkExecutionPlatform`

Dispatches based on `addr`: `None` → simulator, non-`None` → real system. Default target is **WSE3**.

```python
platform = get_platform(addr=None, config=SimfabConfig(dump_core=True), target=SdkTarget.WSE3)
```

### `get_simulator(config=SimfabConfig(), target=SdkTarget.WSE3)` → `SdkExecutionPlatform`

Force simulator. Equivalent to `get_platform(addr=None, …)`.

### `get_system(addr)` → `SdkExecutionPlatform`

Force real system at `addr` (e.g. `"10.0.0.5:9000"`). **Does not** accept a `target` argument — real hardware reports its own WSE generation.

### `get_edge_routing(edge, routing_positions)` → `EdgeRouteInfo`

Builds an `EdgeRouteInfo` for one edge from a list of `RoutingPosition`s — feed into `CodeRegion.paint_all`'s second overload.

## Worked example — host stream → 2x1 region → host stream

```python
import argparse, numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import (
    Color, Edge, Route, RoutingPosition,
    SdkLayout, SdkRuntime, SdkTarget, SimfabConfig, get_platform,
)

ap = argparse.ArgumentParser()
ap.add_argument('--arch', default='wse3')
ap.add_argument('--cmaddr')
args = ap.parse_args()

target   = SdkTarget.WSE2 if args.arch == 'wse2' else SdkTarget.WSE3
config   = SimfabConfig(dump_core=True)
platform = get_platform(addr=args.cmaddr, config=config, target=target)
layout   = SdkLayout(platform)

rx = Color('rx')
tx = Color('tx')

region = layout.create_code_region('./add1.csl', 'a1', 2, 1)
region.set_param_all('size', 64)
region.set_param_all(rx)                       # binds rx by its local-param name
region.set_param_all(tx)
region.paint_all(rx, [RoutingPosition().set_output([Route.RAMP])])
region.paint_all(tx, [RoutingPosition().set_input ([Route.RAMP])])

rx_port = region.create_input_port (rx, Edge.LEFT,  [RoutingPosition().set_output([Route.RAMP])], 64)
tx_port = region.create_output_port(tx, Edge.RIGHT, [RoutingPosition().set_input ([Route.RAMP])], 64)
region.place(4, 4)

in_stream  = layout.create_input_stream (rx_port)
out_stream = layout.create_output_stream(tx_port)

artifacts = layout.compile(out_prefix='out')
rt = SdkRuntime(artifacts, platform, memcpy_required=False)

try:
    rt.load(); rt.run()
    src = np.arange(64, dtype=np.float32)
    dst = np.zeros (64, dtype=np.float32)
    rt.send   (in_stream,  src,                nonblock=True)
    rt.receive(out_stream, dst, n_wavelets=64, nonblock=False)
    assert np.allclose(dst, src + 1)
finally:
    rt.stop()
```

## Failure modes

| Symptom | Probable cause |
|---|---|
| `compile()` errors with "no code region placed" | Forgot `region.place(x, y)` (or `hstack`/`vstack`). |
| `RuntimeError: port 'X' not found` on `runtime.send` | The stream name returned by `create_input_stream` differs from what you stored; or you passed a `PortHandle` where a stream-name string was expected. |
| Wavelets received out of order on the output | Each port has its own FIFO; cross-port ordering is not guaranteed — wait on a `Task` between sends to serialize. |
| Kernel param mismatch error from `cslc` during compile | `set_param_all(name, value)` doesn't match the kernel's `param name: T;` declaration (wrong name, wrong type). |
| Color collision across regions | Two `Color('rx')` instances built at module scope are the *same* color globally; if each region needs a private color use `region.color('rx')` instead. |
| `RuntimeError: io_loc already in use` | Two streams asked for staging at the same coordinate. Either pass distinct `io_loc=` values or omit them and let the runtime pick. |
| Routing deadlock at runtime | Painted color has both `set_input([RAMP])` and `set_output([RAMP])` (the local PE is both source and sink for the same color) — re-think the topology. |

## See also

- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — host-side overview; how `SdkRuntime` consumes the artifacts produced here.
- [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) — `send` / `receive` / `get_port_id` / `task_wait` per-method reference.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — narrative: when SdkLayout is the right tool vs `layout.csl`.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) — fabric routes / colors / CE injection from the PE side (the CSL-language counterpart to `Color` and `Route`).
- [SKILL-DSDS.md](SKILL-DSDS.md) — `fabin_dsd` / `fabout_dsd` patterns on the PE side; the streams created here are consumed via those DSDs in the kernel.
- `_generated/sdkruntime-surface.json` — every signature, every overload, machine-readable.
- `_generated/sdkruntime-symbols.txt` — demangled C++ symbol view for cross-reference.
- Bundled `csl-extras-*/examples/tutorials/sdklayout-*` — progressively richer SdkLayout examples.
