---
name: csl-sdkruntime-types
description: Reference for SDK runtime value types and enums — `Task`, `SimfabConfig`, `SdkExecutionPlatform`, `SdkCompileArtifacts`, plus every enum (`SdkTarget`, `MemcpyDataType`, `MemcpyOrder`, `Edge`, `Route`, `FP16TYPE`). Use when you need to know exactly what a constructor takes, what a value member returns, or what an enum's numeric value is for cross-referencing a hex dump. Pinned to SDK 2.10.0.
---

# Types & Enums Reference

The runtime API surface revolves around a small set of value types — `Task`, `SimfabConfig`, `SdkExecutionPlatform`, `SdkCompileArtifacts` — and six enums. They show up across `SdkRuntime` method signatures, `SdkLayout` constructors, and stream / memcpy options. This file is a flat reference for each.

For the methods that *consume* these types, see [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md). For the layout builders that *produce* `SdkCompileArtifacts`, see [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md).

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

Enum numeric values are stable for this SDK version but **never hardcode them** — always reference by name. Numeric values are listed here only so a maintainer reading a hex dump or compile manifest can sanity-check.

## Types

| Type | Constructor | Role |
|---|---|---|
| `Task` | opaque — returned by non-blocking calls | Handle for `task_wait` / `is_task_done`. |
| `SimfabConfig` | `(num_threads=16, suppress_trace=False, dump_core=False, core_path=None)` | Simulator configuration knob. |
| `SdkExecutionPlatform` | built by `get_platform` / `get_simulator` / `get_system` | Runtime platform handle (sim or system). |
| `SdkCompileArtifacts` | `(path: str)` — or returned from `SdkLayout.compile()` | Compiled SdkLayout binary bundle. |

## `Task`

**Python:** opaque — no public constructor visible from Python. Returned by every non-blocking call on `SdkRuntime`.

**C++:**

```cpp
cerebras::SdkRuntime::Task                                    // public class
cerebras::SdkRuntime::Task::Task(std::shared_ptr<MemcpyTask>) // construction (internal)
cerebras::SdkRuntime::Task::Task(const Task&)                 // copy
cerebras::SdkRuntime::Task::Task(Task&&)                      // move
cerebras::SdkRuntime::Task::get_mtask() const                 // internal accessor
```

Pybind exposes `Task` purely as a handle — you can't construct it, can't inspect it, can only pass it back to `SdkRuntime.task_wait(task)` or `SdkRuntime.is_task_done(task)`.

Lifecycle:

```python
task = rt.memcpy_h2d(..., nonblock=True)    # opaque handle returned
while not rt.is_task_done(task):
    do_other_work()
rt.task_wait(task)                          # idempotent; ensures errors raised
```

**Rules:**

- Tasks are owned by the `SdkRuntime` instance that produced them. Passing a task from one runtime to another raises an opaque "invalid task" error.
- `task_wait` on an already-completed task is a no-op.
- A task whose underlying call errored re-raises that error on the *next* `task_wait` (errors are queued, not raised at issue time).
- There is no `cancel` / `kill`.

## `SimfabConfig`

```python
SimfabConfig(
    num_threads: int = 16,
    suppress_trace: bool = False,
    dump_core: bool = False,
    core_path: Optional[Path] = None,
) -> SimfabConfig
```

Simulator-only — has no effect when running against a real CS system.

| Field | Default | Purpose |
|---|---|---|
| `num_threads` | `16` | Simulator worker thread count. Higher = faster on bigger fabrics. Cap is 64. |
| `suppress_trace` | `False` | `True` skips writing simfab traces — faster runs at the cost of post-mortem visibility. |
| `dump_core` | `False` | `True` makes a later `SdkRuntime.dump_core("path")` actually produce a core file. Without this flag, `dump_core` silently produces nothing. |
| `core_path` | `None` | Optional default destination for core files when `dump_core=True`. Methods that take an explicit `path` arg still win. |

`SdkRuntime`'s constructor also has `suppress_simfab_trace` and `simfab_numthreads` kwargs — these forward to a `SimfabConfig` that the runtime builds internally if you didn't pass a platform built with an explicit `SimfabConfig`. If you do pass an explicit platform (via `get_platform(config=...)`), the platform's `SimfabConfig` wins.

```python
config   = SimfabConfig(num_threads=32, dump_core=True)
platform = get_platform(addr=None, config=config, target=SdkTarget.WSE3)
rt       = SdkRuntime(artifacts, platform, memcpy_required=False)
# rt now uses 32 simulator threads and core-dump is armed
```

## `SdkExecutionPlatform`

Opaque platform handle. Built only by the three free functions below; not user-constructible.

**Methods:**

```python
platform.is_simulation() -> bool
platform.is_system()     -> bool
```

Useful for branching test logic that should skip dump-related steps on real hardware:

```python
if platform.is_simulation():
    rt.dump_core("dump.cs1")
```

## `SdkCompileArtifacts`

```python
SdkCompileArtifacts(path: str) -> SdkCompileArtifacts
artifacts.add_port_mapping(file: str) -> SdkCompileArtifacts
```

Produced primarily by `SdkLayout.compile()` (the common case — pass it directly into `SdkRuntime`). The `(path: str)` constructor reloads a previously-compiled artifact from disk; requires the original compile to have been done with `save_port_map=True` if you also need port-name lookup.

`add_port_mapping(file)` lets you attach additional port-name → port-id maps after construction. It returns `self`, so it's chainable:

```python
artifacts = SdkCompileArtifacts("out").add_port_mapping("extra_ports.json")
```

## Enums

| Enum | Members |
|---|---|
| `SdkTarget` | `WSE2=0`, `WSE3=1` |
| `MemcpyDataType` | `MEMCPY_32BIT=0`, `MEMCPY_16BIT=1` |
| `MemcpyOrder` | `ROW_MAJOR=0`, `COL_MAJOR=1` |
| `Edge` | `TOP=0`, `BOTTOM=1`, `LEFT=2`, `RIGHT=3` |
| `Route` | `RAMP=0`, `EAST=1`, `WEST=2`, `NORTH=3`, `SOUTH=4` |
| `FP16TYPE` | `F16=0`, `BF16=1`, `CB16=2` |

Each enum member is also exposed at module scope as a top-level constant — `sdkruntimepybind.WSE3` and `sdkruntimepybind.SdkTarget.WSE3` are the same value.

### `SdkTarget` — WSE generation

- `WSE2` — second-generation wafer (older fabric).
- `WSE3` — third-generation wafer (current default).

`get_platform`, `get_simulator` default to `WSE3`. `get_system(addr)` ignores target — real hardware reports its own generation.

### `MemcpyDataType` — payload word size

- `MEMCPY_32BIT` — for `float32` / `int32` / `uint32` host arrays. **This is the value `0`** — accidentally passing `data_type=0` will appear to work but pin you to 32-bit even when you wanted 16-bit.
- `MEMCPY_16BIT` — for `float16` / `int16` / `uint16` host arrays.

The host-array `dtype` and the `data_type=` kwarg must agree; mismatch is silent (bytes copy raw, kernel reads garbage).

### `MemcpyOrder` — host-array memory order

- `ROW_MAJOR` — host array is laid out row-major (numpy default).
- `COL_MAJOR` — host array is laid out column-major.

This describes the *host* array's order, **not** the device layout. Transposing a host array does not require flipping `order` — pass the transposed buffer (`arr.T.copy()`) and keep `order=ROW_MAJOR`.

### `Edge` — region edge

Used to place ports on a `CodeRegion`. Values are SDK-internal — never compare them numerically in user code.

### `Route` — fabric switch direction

Used inside `RoutingPosition().set_input([...])` / `.set_output([...])` to wire up colors.

- `RAMP` — local PE handle. Input from `RAMP` means "the local PE produced this wavelet"; output to `RAMP` means "the local PE consumes this wavelet."
- `NORTH` / `SOUTH` / `EAST` / `WEST` — cardinal fabric directions.

A complete `RoutingPosition` for a color that the local PE consumes (e.g. a receiver):

```python
RoutingPosition().set_input([Route.EAST]).set_output([Route.RAMP])
# wavelet enters from the east, is consumed by the local PE
```

A complete `RoutingPosition` for a color the local PE produces:

```python
RoutingPosition().set_input([Route.RAMP]).set_output([Route.WEST])
# wavelet originates at the local PE, exits west
```

Avoid `set_input([RAMP])` + `set_output([RAMP])` simultaneously on the same color — that loops the PE to itself and typically deadlocks.

### `FP16TYPE` — 16-bit float flavor

- `F16` (default) — IEEE-754 binary16 (1 sign + 5 exp + 10 mantissa).
- `BF16` — bfloat16 (1 sign + 8 exp + 7 mantissa).
- `CB16` — Cerebras-specific 16-bit float (CB16).

Passed to `SdkLayout.compile(f16_type=…)`. The kernels' `f16` arithmetic interprets bits according to the value set here.

## Cross-references

The dump records every signature with numpy-array dtype constraints inlined. A few non-obvious patterns:

- Memcpy methods expose `data_type=MemcpyDataType.MEMCPY_*` as a kwarg — but the bare pybind signature shows `arg1: numpy.ndarray` (untyped). The truth is the dtype constraint is checked by `data_type` at runtime, not by pybind overload resolution.
- Stream methods (`send`, `receive`) have multiple typed overloads for specific dtypes (`float32`, `int32`, `uint32`) — pybind *does* resolve those via overload dispatch. Passing `float64` raises `TypeError`.
- `CodeRegion.set_symbol_all` has 5 typed overloads (`int16` / `uint16` / `int32` / `uint32` / `float32`). `float16` is **not** supported there — the compiler-side conversion runs the other way.

## See also

- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — entry-point overview; surface map.
- [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) — every `SdkRuntime` method that takes one of these types as an argument.
- [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md) — `SdkLayout`, `CodeRegion`, the layout-building API that produces `SdkCompileArtifacts`.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — narrative on when to use each.
- `_generated/sdkruntime-surface.json` — every enum's numeric values and every constructor's defaults, machine-readable.
