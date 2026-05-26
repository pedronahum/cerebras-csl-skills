---
name: csl-sdkruntime-api
description: Exhaustive per-method reference for `SdkRuntime` — every method on the runtime driver class with its Python signature(s), C++ signature(s), kwargs, return type, common failure modes, and a minimal call. Companion to SKILL-SDKRUNTIME.md (overview) and SKILL-HOST-DEVICE.md (narrative). Use when you need the contract of a specific call, not the conceptual model. Pinned to SDK 2.10.0; cross-check `_generated/SDK-VERSION.txt` against the installed SIF before trusting specifics.
---

# `SdkRuntime`: Per-Method Reference

This file is the contract sheet. For each callable on `SdkRuntime`, it gives the Python signature pybind11 surfaces, the underlying demangled C++ signature, the kwargs (which usually live on a hidden C++ `MemcpyOptions` struct), the return type, common failure modes, and a minimum-viable example.

For the conceptual model (when to use memcpy vs streams, the `unblock_cmd_stream()` rule), see [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md). For the high-level API surface and lifecycle, see [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md).

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

Every signature in this file was extracted from that exact SIF via `scripts/refresh_sdk_surface.sh`. If your installed SIF differs, refresh before trusting specifics — every per-method block below is recoverable from `_generated/sdkruntime-surface.json` directly.

## Method index

| Group | Methods |
|---|---|
| **Construction** | `__init__` |
| **Lifecycle** | `load`, `run`, `stop` |
| **Memcpy (bulk)** | `memcpy_h2d`, `memcpy_d2h` |
| **Memcpy (broadcast / stride)** | `memcpy_h2d_rowbcast`, `memcpy_h2d_colbcast`, `memcpy_h2d_stride` |
| **RPC** | `launch`, `call` |
| **Streams (SdkLayout ports)** | `send`, `receive`, `receive_tofile` |
| **Name resolution** | `get_id`, `get_port_id`, `report_port_infos` |
| **Task handles** | `task_wait`, `is_task_done` |
| **Debug (sim-only)** | `dump_core`, `dump_elf_core`, `read_symbol`, `coord_logical_to_physical` |

Every memcpy / RPC / stream method returns a `Task` and accepts `nonblock=` plus the `MemcpyOptions` kwarg group described in the [shared-kwargs](#shared-kwargs-the-memcpyoptions-surface) section.

## Construction

### `SdkRuntime(...)`

**Python (3 overloads):**

```
SdkRuntime(name: str, **kwargs) -> None
SdkRuntime(name: str, platform: SdkExecutionPlatform, **kwargs) -> None
SdkRuntime(artifacts: SdkCompileArtifacts, platform: SdkExecutionPlatform, **kwargs) -> None
```

**C++:**

```cpp
cerebras::SdkRuntime::SdkRuntime(
    const SdkCompileArtifacts&,
    const SdkExecutionPlatform&,
    std::string suppress_simfab_trace_or_cmaddr,
    bool,
    bool,
    bool,
    std::string,
    std::string
)
```

The C++ constructor has eight positional args; pybind exposes the first one or two as positional and folds the rest into `**kwargs`.

**Kwargs (kwarg, default, purpose):**

| Kwarg | Default | Purpose |
|---|---|---|
| `cmaddr` | `None` | `"host:port"` for a real CS system. Omit / `None` selects the simulator. Only valid on the `name`-only and `(name, platform)` overloads. |
| `suppress_simfab_trace` | `False` | `True` skips writing simfab traces — faster simulator runs. |
| `simfab_numthreads` | platform default (typically `SimfabConfig.num_threads = 16`) | Simulator worker thread count (max 64). Higher = faster simulator on bigger fabrics. |
| `msg_level` | `"WARNING"` | One of `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`. |
| `memcpy_required` | `True` | `False` *only* for SdkLayout-only programs that don't link the memcpy infrastructure. Passing `False` to a memcpy program hangs `load()` silently. |
| `setup_phase_only` | `False` | Refuses `run()` calls — used for compile/setup-only workflows. Mutually exclusive with `run_phase_only`. Reverse-engineered from runtime assertion strings; not in pybind's public docstrings. |
| `run_phase_only` | `False` | Refuses `load()` calls — assumes a prior `setup_phase_only=True` invocation produced the loadable binary. Pair with `setup_phase_only` for split setup/run pipelines. |
| `wio_flows` | `None` | Path to a `wio_flows.json` describing fabric LVDS pin routing (H2D / D2H / cmd / ingress channels). Consumed by an internal `Impl::generate_wio_flow()` step during `load()`. Schema not documented externally. |
| `worker` | `False`-ish | MPI worker mode. Requires `OMPI_COMM_WORLD_SIZE` / `OMPI_COMM_WORLD_RANK` env vars and a `workers.json` whose worker count matches the MPI world size. Used to coordinate multi-node runs against a single cluster. |

**When to use which overload:**

- `SdkRuntime("out")` — compiled output directory (memcpy program), simulator. The runtime fabricates a `SdkExecutionPlatform` internally.
- `SdkRuntime("out", platform)` — same, but you've explicitly built the platform (e.g. with `get_system("ip:port")`).
- `SdkRuntime(artifacts, platform, memcpy_required=False)` — SdkLayout program. `artifacts` came from `SdkLayout.compile()`. You also need `memcpy_required=False`.

**Failure modes:**

- Passing a string path to a directory that doesn't contain a compile output (`out.json` etc.): `RuntimeError` from `load()`, not at construction time.
- Passing `SdkCompileArtifacts` without an explicit `platform`: `TypeError: no overload matched`.
- Passing `memcpy_required=False` to a memcpy program: `load()` hangs (no error — the runtime is waiting for memcpy bring-up that won't happen).

**Minimal calls:**

```python
# Simulator, memcpy program:
rt = SdkRuntime("out")

# Real system, memcpy program:
rt = SdkRuntime("out", cmaddr="10.0.0.5:9000")

# Simulator, SdkLayout program:
rt = SdkRuntime(artifacts, platform, memcpy_required=False)
```

## Lifecycle

### `load()` → `None`

**Python:** `load(self) -> None`
**C++:** `cerebras::SdkRuntime::load()`

Copies the compiled binary onto the simulator (or real CS, when `cmaddr` is set) and prepares the runtime. Must be called exactly once, before `run()`. No kwargs.

**Failure modes:**

- `load()` blocks forever: usually `memcpy_required=False` was passed for a memcpy program, or the compile output dir is incomplete.
- `RuntimeError: failed to open ...`: missing `out.json` or per-PE ELF.

### `run()` → `None`

**Python:** `run(self) -> None`
**C++:** `cerebras::SdkRuntime::run()`

Releases the PEs; the device begins executing whatever tasks are bound to startup. Must be called exactly once after `load()`. Subsequent host commands (`memcpy_h2d`, `launch`, `send`, …) are queued onto the command stream that this call opens.

### `stop()` → `None`

**Python:** `stop(self) -> None`
**C++:** `cerebras::SdkRuntime::stop()`

Drains pending tasks and tears the runtime down. **Mandatory** before process exit, even on error paths — the simulator otherwise leaks named sockets that future `cs_python` invocations may stumble on. Wrap in `try` / `finally` for any test harness.

```python
rt = SdkRuntime("out")
try:
    rt.load(); rt.run()
    # ...
finally:
    rt.stop()
```

## Memcpy — bulk

### `memcpy_h2d(dest_id, src, px, py, w, h, elem_per_pe, **kwargs)` → `Task`

**Python:**

```
memcpy_h2d(dest_id: int, src: numpy.ndarray,
           px: int, py: int, w: int, h: int, elem_per_pe: int,
           **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::memcpy_h2d(
    unsigned short dest_id,
    void* src,
    int px, int py, int w, int h, int elem_per_pe,
    const MemcpyOptions& opts
)
```

Copies `w * h * elem_per_pe` elements from the host array `src` into the region of PEs from `(px, py)` of size `(w, h)`. Each PE receives `elem_per_pe` elements bound to the kernel symbol identified by `dest_id` (from `get_id("name")`).

**Required kwargs:** `streaming`, `order`, `data_type`, `nonblock`. See [shared-kwargs](#shared-kwargs-the-memcpyoptions-surface).

**Positional argument detail:**

| Position | C++ type | Purpose |
|---|---|---|
| `dest_id` | `unsigned short` | Kernel symbol id (from `get_id`) when `streaming=False`. Memcpy color id (from `out.json['params']['MEMCPYH2D_DATA_N_ID']`) when `streaming=True`. |
| `src` | `void*` | Numpy array. Must be contiguous; pybind copies its dtype check against `data_type` (see failure modes). |
| `px, py` | `int` | Origin of the destination region in the PE grid (column, row). |
| `w, h` | `int` | Region extent in PEs. Total elements copied = `w * h * elem_per_pe`. |
| `elem_per_pe` | `int` | Elements *per PE*. The most common off-by-`w*h` bug when migrating single-PE → multi-PE. |

**Failure modes:**

- `dest_id` outside `unsigned short` range (i.e. `> 65535`): `OverflowError` from pybind, before the call reaches the device.
- `src.dtype` mismatch with `data_type=`: silent — the bytes get copied raw and the kernel reads garbage.
- `src` not contiguous (e.g. `arr.T` view on a 2D array): pybind raises `TypeError` complaining the numpy array is not C-contiguous.
- `w * h * elem_per_pe != src.size`: hangs the runtime; the simulator log eventually flags a buffer-size mismatch.
- `streaming=True` with a symbol id (not a memcpy-color id): hang.

**Minimal call:**

```python
rt.memcpy_h2d(
    rt.get_id("A"), np.arange(N, dtype=np.float32),
    0, 0, 1, 1, N,
    streaming=False, order=MemcpyOrder.ROW_MAJOR,
    data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False,
)
```

### `memcpy_d2h(dest, src_id, px, py, w, h, elem_per_pe, **kwargs)` → `Task`

**Python:**

```
memcpy_d2h(dest: numpy.ndarray, src_id: int,
           px: int, py: int, w: int, h: int, elem_per_pe: int,
           **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::memcpy_d2h(
    void* dest, unsigned short src_id,
    int px, int py, int w, int h, int elem_per_pe,
    const MemcpyOptions& opts
)
```

Symmetric of `memcpy_h2d` — first arg is the host destination array, second is the device source id. Region semantics and all kwargs are identical.

**Pre-allocate the destination yourself** — pybind doesn't allocate for you. The array's `dtype` must match `data_type` (`float32`/`int32`/`uint32` for `MEMCPY_32BIT`; `float16`/`int16`/`uint16` for `MEMCPY_16BIT`).

## Memcpy — broadcast and stride

### `memcpy_h2d_rowbcast(dest_id, src, px, py, w, h, elem_per_pe, **kwargs)` → `Task`

**Python:**

```
memcpy_h2d_rowbcast(dest_id: int, src: numpy.ndarray,
                    px: int, py: int, w: int, h: int, elem_per_pe: int,
                    **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::memcpy_h2d_rowbcast(
    unsigned short, void*, int, int, int, int, int,
    const MemcpyOptions&
)
```

Same shape as `memcpy_h2d` but `src` has only the data for *one row* (`w * elem_per_pe` total) and the runtime broadcasts that row's contents into every row of the region. Saves the host having to manually replicate.

### `memcpy_h2d_colbcast(dest_id, src, px, py, w, h, elem_per_pe, **kwargs)` → `Task`

**Python:**

```
memcpy_h2d_colbcast(dest_id: int, src: numpy.ndarray,
                    px: int, py: int, w: int, h: int, elem_per_pe: int,
                    **kwargs) -> Task
```

Column counterpart. `src` size is `h * elem_per_pe`.

### `memcpy_h2d_stride(dest_id, src, px, py, w, h, elem_per_pe, row_stride, col_stride, **kwargs)` → `Task`

**Python:**

```
memcpy_h2d_stride(dest_id: int, src: numpy.ndarray,
                  px: int, py: int, w: int, h: int, elem_per_pe: int,
                  row_stride: int, col_stride: int,
                  **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::memcpy_h2d_stride(
    unsigned short, void*, int, int, int, int, int,
    int row_stride, int col_stride,
    const MemcpyOptions&
)
```

Strided variant — useful when the host array packs data with row / column strides that don't match a contiguous block-row pattern. Two extra positional args after `elem_per_pe`.

## RPC

### `launch(name, *args, **kwargs)` → `Task`

**Python:** `launch(name: str, *args, **kwargs) -> Task`
**C++:** No direct overload — `launch` is Python sugar that packs `*args` into `uint32` and calls the C++ `call` method below.

Calls a host-callable function on the device. The function must have been declared with `@export_name("name", fn(arg_types)return_type)` in the layout block and bound with `@export_symbol(name)` in the PE comptime block.

Positional args (`*args`) are forwarded as RPC arguments. They're packed into a `uint32` vector before being shipped to the device (every CSL-level RPC argument must be representable as one or more `uint32` words).

**Kwargs:** `nonblock` (only). The full `MemcpyOptions` group is *not* applicable — there's no host buffer involved.

**Failure modes:**

- Argument count / type mismatch with the `@export_name` declaration: device-side trap, reported as `RuntimeError` on the next blocking host call.
- Calling a function that wasn't `@export_symbol`'d in the PE program: `KeyError: launch target 'name' not found`.
- Forgetting `sys_mod.unblock_cmd_stream()` at the end of the kernel function: every subsequent host call hangs. This is the single most common bug in this surface.

**Minimal calls:**

```python
rt.launch("compute", nonblock=False)            # void(void)
rt.launch("compute_n", 42, nonblock=False)      # void(u32)
task = rt.launch("compute", nonblock=True)
# ... overlap work ...
rt.task_wait(task)
```

### `call(name, args_u32, **kwargs)` → `Task`

**Python:** `call(name: str, args_u32: numpy.ndarray[numpy.uint32], **kwargs) -> Task`

**C++:**

```cpp
cerebras::SdkRuntime::call(
    const std::string& name,
    const std::vector<unsigned int>& args,
    const MemcpyOptions& opts
)
```

The lower-level form of `launch` — accepts a pre-packed `uint32` vector instead of `*args`. Use when you have arguments larger than `u32` (pack manually into multiple words) or when you're producing the argument vector from data already in numpy form.

Most user code uses `launch`. `call` is documented for completeness and for cases where you need to construct the argument vector dynamically.

## Streams (SdkLayout ports)

### `send(port, src, n_wavelets, **kwargs)` → `Task`

**Python (5 overloads):**

```
send(port: str, src: numpy.ndarray,                  n_wavelets: int, **kwargs) -> Task
send(port: int, src: numpy.ndarray,                  n_wavelets: int, **kwargs) -> Task
send(port: str, src: numpy.ndarray[numpy.int32],                      **kwargs) -> Task
send(port: str, src: numpy.ndarray[numpy.uint32],                     **kwargs) -> Task
send(port: str, src: numpy.ndarray[numpy.float32],                    **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::send(const std::string&, const void*, unsigned long n_wavelets, bool nonblock)
cerebras::SdkRuntime::send(unsigned short, const void*, unsigned long n_wavelets, bool nonblock)
```

Streams `n_wavelets` worth of data from `src` into the SdkLayout input stream identified by `port`. The first argument can be either the stream name (string returned by `SdkLayout.create_input_stream(...)`) or the integer id (from `runtime.get_port_id("name")`) — they resolve to the same backing call.

The three extra typed overloads (`int32`, `uint32`, `float32`) drop the explicit `n_wavelets` parameter — pybind infers it from `src.size`. They're sugar.

**Kwargs:** `nonblock` (only).

**Failure modes:**

- Calling `send` against a runtime built with `memcpy_required=True` and no SdkLayout ports: `RuntimeError: no port named 'X'`.
- Dtype mismatch with what the kernel binds the stream to: silent — bytes are forwarded raw, kernel reads garbage.

### `receive(port, dest, n_wavelets, **kwargs)` → `Task`

**Python (2 overloads):**

```
receive(port: str, dest: numpy.ndarray, n_wavelets: int, **kwargs) -> Task
receive(port: int, dest: numpy.ndarray, n_wavelets: int, **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::receive(const std::string&, void*, unsigned long, bool)
cerebras::SdkRuntime::receive(unsigned short, void*, unsigned long, bool)
```

Symmetric of `send`. Pre-allocate `dest` to the right `dtype` and size; pybind doesn't allocate for you. `n_wavelets` is mandatory — it's the count the runtime drains from the port before returning the `Task`.

### `receive_tofile(port, path, **kwargs)` → `Task`

**Python (2 overloads):**

```
receive_tofile(port: str, path: str, **kwargs) -> Task
receive_tofile(port: int, path: str, **kwargs) -> Task
```

**C++:**

```cpp
cerebras::SdkRuntime::receive_tofile(const std::string&, const std::string&, bool)
cerebras::SdkRuntime::receive_tofile(unsigned short, const std::string&, bool)
```

Streams the output port's bytes directly to `path` on the host filesystem — useful for very large traces / benchmarks where keeping the data in a numpy array would blow memory. The file is written as a raw byte stream (no header, no shape info).

## Name resolution

### `get_id(name)` → `Optional[int]`

**Python:** `get_id(self, name: str) -> Optional[int]`
**C++:** `cerebras::SdkRuntime::get_id(const std::string&) const`

Resolves a symbol name (declared with `@export_name(...)` in the layout block + `@export_symbol(...)` in the PE comptime block) to its numeric id. The id is what the memcpy methods take as `dest_id` / `src_id`.

**Returns `None`** if no such name exists. Always check — passing `None` into `memcpy_h2d` raises a pybind type error, but doing so via `int(None_or_id)` blows up with a confusing message.

```python
sid = rt.get_id("A")
if sid is None:
    raise RuntimeError("'A' was not @export_name'd in the layout — check layout.csl")
rt.memcpy_h2d(sid, host_arr, ...)
```

### `get_port_id(name)` → `Optional[int]`

**Python:** `get_port_id(self, name: str) -> Optional[int]`
**C++:** `cerebras::SdkRuntime::get_port_id(const std::string&)`

Same shape as `get_id`, but for stream-port names declared via `SdkLayout.create_input_port` / `create_output_port`. Returns `None` for an unknown name. Most user code uses the *string* name directly with `send` / `receive` and never needs `get_port_id`; the id form is for cases where you want to cache the resolution.

### `report_port_infos()` → `None`

**Python:** `report_port_infos(self) -> None`
**C++:** `cerebras::SdkRuntime::report_port_infos()`

Prints (to the runtime's configured logger) a summary of every known port. Diagnostic only — useful when chasing a `get_port_id("X") is None` error to confirm what names the runtime actually knows about.

## Task handles

`Task` is opaque — you don't construct it directly. Every non-blocking call returns one; pass it back to `task_wait` to block or `is_task_done` to poll.

### `task_wait(task)` → `None`

**Python:** `task_wait(self, task: Task) -> None`
**C++:** `cerebras::SdkRuntime::task_wait(const Task&)`

Blocks until the task completes. Cheap idempotent — calling on an already-completed task returns immediately.

### `is_task_done(task)` → `bool`

**Python:** `is_task_done(self, task: Task) -> bool`
**C++:** `cerebras::SdkRuntime::is_task_done(const Task&)`

Non-blocking poll.

```python
task = rt.launch("compute", nonblock=True)
while not rt.is_task_done(task):
    do_other_work()
rt.task_wait(task)   # idempotent; ensures errors raised
```

`Task` handles are *not interchangeable across runtimes* — each `SdkRuntime` has its own task arena. Mixing produces an opaque "invalid task" error.

## Debug (simulator-only)

These all assume `SdkRuntime` was built against a simulator (`cmaddr=None`). On a real CS system they typically return empty or raise.

### `dump_core(path)` → `None`

**Python:** `dump_core(self, path: str) -> None`
**C++:** `cerebras::SdkRuntime::dump_core(std::string)`

Dumps a simulator-format core file at `path`, readable by `csdb`. Requires the runtime / `SimfabConfig` to have been built with `dump_core=True`; otherwise the call silently produces nothing.

### `dump_elf_core(path)` → `None`

**Python:** `dump_elf_core(self, path: str) -> None`
**C++:** `cerebras::SdkRuntime::dump_elf_core(std::string)`

ELF-format core dump. Use with the SDK's debug shell / IDE integrations.

### `read_symbol(x, y, symbol_name, dtype='uint8')` → `object`

**Python:** `read_symbol(self, x: int, y: int, symbol_name: str, dtype: str = 'uint8') -> object`
**C++:** `cerebras::SdkRuntime::read_symbol(int, int, const std::string&) const`

Returns the live value of `symbol_name` on the PE at logical coordinate `(x, y)`. The Python wrapper interprets the raw bytes via `dtype`: one of `"uint8"`, `"int8"`, `"uint16"`, `"int16"`, `"uint32"`, `"int32"`, `"float16"`, `"float32"`. Wrong `dtype` produces a numpy array with the wrong shape/values rather than an error.

Useful in tests for asserting against intermediate PE state without round-tripping through memcpy.

```python
val = rt.read_symbol(0, 0, "y", dtype="float32")
assert np.allclose(val, expected)
```

### `coord_logical_to_physical((x, y))` → `(int, int)`

**Python:** `coord_logical_to_physical(self, coord: Tuple[int, int]) -> Tuple[int, int]`
**C++:** `cerebras::SdkRuntime::coord_logical_to_physical(int, int, int*, int*)`

Translates a logical PE coordinate (the one you used with `@set_tile_code(x, y, ...)` in the layout) to a physical wafer coordinate. Useful when reading hardware traces that report physical coords.

## Shared kwargs — the `MemcpyOptions` surface

Every C++ memcpy-family method (`memcpy_h2d`, `memcpy_d2h`, `memcpy_h2d_rowbcast`, `memcpy_h2d_colbcast`, `memcpy_h2d_stride`, and `call` — yes, `call` too) takes a final `const cerebras::MemcpyOptions&` parameter. pybind11 splats this struct's fields into Python kwargs. They are *not* visible in the raw pybind signature — you must know about them out-of-band.

| Kwarg | Type | Required? | Purpose |
|---|---|---|---|
| `streaming` | `bool` | yes for memcpy | `False`: copy to a named kernel symbol. `True`: stream over a memcpy color (id from `out.json['params']['MEMCPYH2D_DATA_N_ID']`). |
| `order` | `MemcpyOrder` | yes for memcpy | `ROW_MAJOR` or `COL_MAJOR`. Describes the *host array* memory order. The device layout is independent. |
| `data_type` | `MemcpyDataType` | yes for memcpy | `MEMCPY_16BIT` (for `float16`/`int16`/`uint16`) or `MEMCPY_32BIT` (for `float32`/`int32`/`uint32`). Must match the host array's dtype. |
| `nonblock` | `bool` | recommended | `False`: block until device acks. `True`: return immediately with a `Task` handle. Default in most examples is `False`. |

`order=ROW_MAJOR` does *not* mean "row-major on the device" — it means "the host array is laid out row-major." When you transpose a host array with `arr.T.copy()` and want to send the transposed view, you do not flip `order` — you just send the new buffer.

`data_type` and `src.dtype` must agree. Mismatch is **silent** — bytes get copied as-is and the kernel reads garbage. The bug surface from this is large; the easiest defense is a one-line assert before the call:

```python
assert src.dtype == np.float32 and data_type == MemcpyDataType.MEMCPY_32BIT
```

## Common failure-mode catalog

A flat list — when something on `SdkRuntime` goes wrong, look here first.

| Symptom | Probable cause |
|---|---|
| `load()` hangs forever | `memcpy_required=False` on a memcpy program, *or* missing `out.json` in the compile dir. |
| Every host command after a `launch` hangs | The launched kernel function forgot `sys_mod.unblock_cmd_stream()` at the end. |
| `get_id("X") is None` | `X` wasn't `@export_name`'d in the layout. Or layout block declared it but the PE program never `@export_symbol`'d it. |
| `OverflowError` from `memcpy_h2d` / `send` | First positional id is `> 65535`. The C++ side uses `unsigned short`. |
| `TypeError: no overload matched` from `send` / `receive` / `__init__` | Argument types don't match any of the C++ overloads — most commonly `np.float64` against a method only bound for `float32`/`int32`/`uint32`. |
| Output array is all zeros after `memcpy_d2h` | Destination dtype didn't match `data_type=`, or `nonblock=True` was used without `task_wait`. |
| "invalid task" error from `task_wait` | `Task` came from a different `SdkRuntime` instance. |
| Garbage values in the PE / on the host | `data_type` ≠ `src.dtype` (silent byte-copy). |
| `RuntimeError: no port named 'X'` | Either typo in the port name, or running an SdkLayout call against a memcpy-only runtime. |
| Simulator file-descriptor errors on next `cs_python` invocation | Previous run didn't call `stop()`. |

## Precondition catalog

The runtime checks these conditions and emits matching strings when they fail. The full pinned list is at `_generated/sdkruntime-preconditions.txt` (extracted from `.rodata` of `libsdkruntime.so`, `libsdk_layout.so`, `libstreamer.so`). Reach for it when chasing an opaque runtime error.

| Constraint | Error message (verbatim) |
|---|---|
| `load()` exactly once, before `run()` | "Cannot call run() multiple times, or call run() if load() has not been called" |
| `run()` exactly once, before `stop()` | "Cannot call stop() multiple times, or call stop() if run() has not been called" |
| Memcpy needs running runtime | "SdkRuntime must be running to accept memcpy commands." |
| `dump_core` is sim-only | "Cannot dump core on real hardware" |
| `dump_*` after `load()` | "Cannot call dump_core() if load() has not been called" |
| memcpy regions inside fabric | "h2d subrectangle must be inside the core rectangle" / d2h variant |
| `memcpy_h2d_stride` positive strides | "row_stride or col_stride must be positive" |
| Valid `data_type` / `order` enum | "Illegal data type option for memcpy" / "Illegal order option for memcpy" |
| `setup_phase_only` ⊕ `run_phase_only` | "sdk_setup_phase_only and sdk_run_phase_only must be mutual exclusive" |
| `worker` mode env vars | "workers.json requires OMPI_COMM_WORLD_SIZE" / RANK |
| Layout ingress/egress symmetry | "Number of ingress and egress tiles must be equal." |
| Layout ports on fabric edge | "All ingress tiles must be at the edge of the fabric" |
| Even-wavelet output | "The output port must have even number of wavelets" |
| `hstack`/`vstack` non-empty | "'hstack' requires at least one child." |
| Connect compatible port shapes | "cannot connect ports with incompatible data sizes" / "... incompatible number of PEs" |
| Port routing direction | "input port cannot have input route." / output variant |
| Known RPC symbol | "Cannot find exported function with name " |
| RPC arg-list match | "functional protype does not match what is defined in the kernel" (SDK typo) |

## See also

- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — entry-point overview (surface map, lifecycle, both worked examples).
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — narrative on when to use memcpy vs SdkLayout vs streams; the `unblock_cmd_stream()` rule; `out.json` metadata reading.
- [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md) — the `SdkLayout` / `CodeRegion` / port / route API that produces the names/ids consumed by the stream methods here.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `fabin_dsd` / `fabout_dsd`, the PE-side companion to `send` / `receive` and streaming memcpy.
- `_generated/sdkruntime-surface.json` — every signature in this file, machine-readable. The block under `modules[...].classes.SdkRuntime.members` is the literal source for the per-method blocks above.
- `_generated/sdkruntime-symbols.txt` — the C++ symbol dump that the cross-reference rows quote from.
