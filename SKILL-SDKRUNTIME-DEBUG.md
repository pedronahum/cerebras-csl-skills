---
name: csl-sdkruntime-debug
description: Reference for the SDK runtime debug surface — both the live methods on `SdkRuntime` (`dump_core`, `dump_elf_core`, `read_symbol`, `coord_logical_to_physical`) and the four post-mortem pybind modules (`csldebugpybind`, `sdkinstrtracepybind`, `rectangleopspybind`, `wavelettracepybind`). Use when chasing a deadlock, reading instruction traces, decoding wavelet traces, or post-mortem-inspecting a core dump. Pinned to SDK 2.10.0.
---

# Debug Reference

Two debug paths land on the same data:

1. **Live** — methods on `SdkRuntime` that work while the simulator is running. Best for assertion-driven tests and quick state checks. Sim-only (`is_simulation() == True`); on real hardware these are no-ops or raise.

2. **Post-mortem** — four pybind modules under `cerebras.sdk.debug.lib.*` that load saved trace / dump files and let you reconstruct what the simulator saw. Useful when reproducing a problem requires a long run or when you want to slice the trace many ways without re-running.

For the rest of `SdkRuntime` (lifecycle, memcpy, RPC, streams), see [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md).

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

The pybind module names below contain at least two typos preserved by the SDK (`Wavlets`, `WavletTrace`). They are reproduced verbatim — use the spelling the SDK exposes, not what looks correct.

## Module map

| Module | Purpose |
|---|---|
| `cerebras.sdk.runtime.sdkruntimepybind.SdkRuntime` | Live methods: `dump_core`, `dump_elf_core`, `read_symbol`, `coord_logical_to_physical`. |
| `cerebras.sdk.debug.lib.symbol.csldebugpybind` | CTF-format trace readers + ELF symbol tables (`CSLELFSymbol`, `CSLSymbolTable`, `SimfabInstructionTraceCtf`, `SimfabWaveletTraceCtf`). |
| `cerebras.sdk.debug.lib.instruction_trace.sdkinstrtracepybind` | High-level instruction-trace API (`SimfabInstructionTrace`, `Trace`, `Instruction`, iterators) + opcode-format enums. |
| `cerebras.sdk.debug.lib.rectangleopspybind` | Cross-PE rectangular reads + core dumps (`RectangleDebugger` + Sim/CM variants). |
| `cerebras.sdk.debug.lib.wavelet_trace.wavelettracepybind` | Wavelet timelines, back-pressure tracking (`SimfabWaveletTrace`, `SimfabWaveletTimeline`, `Wavlets`, `WavletTrace`). |

## Live debug (on `SdkRuntime`)

### `dump_core(path)` → `None`

**Python:** `dump_core(self, path: str) -> None`
**C++:** `cerebras::SdkRuntime::dump_core(std::string)`

Dumps a simulator-format core file at `path`, readable by `csdb` and the four post-mortem modules below.

**Requires** `dump_core=True` on the `SimfabConfig` used to build the platform:

```python
config   = SimfabConfig(dump_core=True)
platform = get_platform(addr=None, config=config, target=SdkTarget.WSE3)
rt       = SdkRuntime("out", platform)
# ... run kernel ...
rt.dump_core("dump.cs1")
```

Without the `SimfabConfig.dump_core=True` flag, this call **silently produces nothing** — the simulator wasn't recording.

### `dump_elf_core(path)` → `None`

**Python:** `dump_elf_core(self, path: str) -> None`
**C++:** `cerebras::SdkRuntime::dump_elf_core(std::string)`

ELF-format core dump, consumed by the SDK's debug shell and IDE integrations. Same `dump_core=True` requirement.

### `read_symbol(x, y, symbol_name, dtype='uint8')` → `object`

**Python:** `read_symbol(self, x: int, y: int, symbol_name: str, dtype: str = 'uint8') -> object`
**C++:** `cerebras::SdkRuntime::read_symbol(int, int, const std::string&) const`

Returns the live value of `symbol_name` on the PE at logical coordinate `(x, y)`. Python wrapper interprets the bytes via `dtype` — one of `"uint8"`, `"int8"`, `"uint16"`, `"int16"`, `"uint32"`, `"int32"`, `"float16"`, `"float32"`.

Wrong `dtype` produces a numpy array with the wrong shape / values rather than an error — pybind reinterprets bytes without sanity-checking against the symbol's declared CSL type.

This is the **assertion-friendly** path: peek at intermediate PE state without round-tripping through memcpy.

```python
val = rt.read_symbol(0, 0, "y", dtype="float32")
assert np.allclose(val, expected), f"PE(0,0) y={val} != expected={expected}"
```

### `coord_logical_to_physical((x, y))` → `(int, int)`

**Python:** `coord_logical_to_physical(self, coord: Tuple[int, int]) -> Tuple[int, int]`
**C++:** `cerebras::SdkRuntime::coord_logical_to_physical(int, int, int*, int*)`

Maps a logical PE coord (the one used by `@set_tile_code(x, y, ...)` in the layout) to a physical wafer coord. Use this to align an instruction / wavelet trace report (which uses physical coords) with the layout source.

## The post-mortem workflow

```
   run kernel with SimfabConfig(dump_core=True)
                 │
                 ▼
        rt.dump_core("dump.cs1")        # write core
                 │
                 ├──── csldebugpybind.CSLSymbolTable   ← symbol metadata
                 │     csldebugpybind.SimfabInstructionTraceCtf("dump.cs1", elf_dir)
                 │
                 ├──── sdkinstrtracepybind.SimfabInstructionTrace("dump.cs1", elf_dir)
                 │
                 ├──── rectangleopspybind.get_debugger("local", x, y, w, h)
                 │       .dumpcore(...)  /  .read(x, y, callback)
                 │
                 └──── wavelettracepybind.SimfabWaveletTrace("dump.cs1")
                       wavelettracepybind.SimfabWaveletTimeline("dump.cs1")
                 │
                 ▼
        slice traces, build dataframes, inspect colors, etc.
```

The four modules all consume the same core file but expose different views — symbol tables vs instruction streams vs cross-PE binary reads vs wavelet timelines. Pick the one that matches the question you're asking.

## `cerebras.sdk.debug.lib.symbol.csldebugpybind`

### `CSLELFSymbol(path)`

```
CSLELFSymbol(path: str) -> CSLELFSymbol

elf_sym.dimensions()                              -> AbstractRectangle<unsigned int>
elf_sym.init_symbol(routes_only: bool = False, debug_level: int = 0) -> int
```

Loads a single ELF symbol from disk. `dimensions()` returns its grid extent; `init_symbol()` re-runs the symbol's initializer (useful when you want to reproduce route binding without running the whole kernel).

### `CSLSymbolTable(dim, debug_level=0)`

```
CSLSymbolTable(dim: AbstractRectangle<unsigned int>, debug_level: int = 0) -> CSLSymbolTable

table.dimensions()                       -> AbstractRectangle<unsigned int>
table.load_elf(paths: List[str], …)      -> int
table.get_symbol_count()                 -> int
table.get_symbol_name(index: int)        -> str
table.get_coordinates_for_symbol(name)   -> List[Tuple[Point<unsigned int>, SymbolOffset]]
table.get_symbols_from_coordinate(point) -> Dict[int, SymbolOffset]
table.get_name_from_coordinate(point)    -> str
table.get_routing_colors()               -> List[int]
table.get_pre_run_routes_raw(x, y)       -> Dict[int, int]    # color id -> route mask
```

Full symbol-table reader. Build with the fabric dims; populate via `load_elf([per-pe-elf-paths], debug_flag)`. Use `get_coordinates_for_symbol("name")` to find every PE that hosts a given symbol; use `get_pre_run_routes_raw(x, y)` to see what colors were pre-wired at `(x, y)` before the first task ran.

### `SimfabInstructionTraceCtf(dump_path, elf_dir)`

```
SimfabInstructionTraceCtf(dump_path: str, elf_dir: str) -> SimfabInstructionTraceCtf

trace.get_fabric_dim()                                                    -> AbstractRectangle
trace.get_instruction_trace_at(pt, cycle_start=0, cycle_end=0)            -> object
trace.get_instruction_trace_per_task_at(pt, task_id)                      -> object
trace.get_instruction_trace_per_uthread_at(pt, uthread_id)                -> object
trace.get_instruction_trace_summary(pt, arg1, arg2)                       -> object
trace.get_tasks_at(pt)                                                    -> object
trace.get_uthreads_at(pt)                                                 -> object
```

CTF-format instruction trace reader. `pt` is a `cerebras::Point<unsigned int>` — usually `(x, y)`. Use `get_tasks_at` first to see which task IDs have trace data, then drill in with `get_instruction_trace_per_task_at`.

`cycle_start=0, cycle_end=0` means "the whole range." Pass positive integers to slice.

### `SimfabWaveletTraceCtf(dump_path)`

```
SimfabWaveletTraceCtf(dump_path: str) -> SimfabWaveletTraceCtf

trace.get_wavelet_trace_at(pt, kind: str)                       -> List[object]
trace.get_wavelet_trace_per_colors_at(pt, color_ids: List[int], kind: str) -> List[object]
```

CTF-format wavelet trace reader. `kind` selects which wavelet event class to return (e.g. `"send"`, `"recv"`, `"backpressure"` — check the SDK examples for the exact spelling). `color_ids` restricts to a subset.

### Free: `get_instruction_timeline(dump_path, elf_dir, pt, cycle_start, cycle_end)`

```
get_instruction_timeline(arg0: str, arg1: str, arg2: Point<unsigned int>,
                          arg3: int, arg4: int) -> object
```

One-shot helper that builds a CTF trace and pulls a timeline window at `pt` in one call. Use when you don't need the full `SimfabInstructionTraceCtf` lifecycle.

## `cerebras.sdk.debug.lib.instruction_trace.sdkinstrtracepybind`

A higher-level façade over the CTF reader, with explicit dataclasses and iterators.

### `SimfabInstructionTrace(dump_path, elf_dir)`

```
SimfabInstructionTrace(dump_path: str, elf_dir: str) -> SimfabInstructionTrace
# inherits from InstructionTrace
```

### `InstructionTrace`

```
trace.get_instructions(x, y)                                  -> TraceSequenceIterator
trace.get_instructions_per_task(x, y, task_id)                -> TraceSequenceIterator
trace.get_instructions_per_uthread(x, y, uthread_id)          -> TraceSequenceIterator
trace.get_tasks(x, y)                                         -> List[int]
trace.get_uthreads(x, y)                                      -> List[int]
trace.get_source_line(x, y, instr_id)                         -> SourceLine
```

`get_source_line` is the most useful: maps an instruction index back to the CSL source line that produced it.

### `Trace`

```
Trace(instrs: numpy.ndarray[Instruction], sequences: numpy.ndarray[Sequence]) -> Trace

trace.instrs()    -> numpy.ndarray[Instruction]
trace.sequences() -> numpy.ndarray[Sequence]
```

A loaded trace window. `instrs` is the flat instruction list; `sequences` indexes into it for control-flow boundaries. Build either by passing arrays you've assembled, or by filling one in via the iterator API.

### `Instruction`

```
Instruction()
instr.opname() -> str
```

Single instruction record. `opname` returns the canonical opcode name (e.g. `"fmacs"`, `"add16"`).

### `SourceLine`

```
SourceLine(filename: str, content: str) -> SourceLine
```

A `(file, content)` pair returned by `InstructionTrace.get_source_line`. Use directly — it's a value type.

### `TraceSequenceIterator`, `InstructionTraceIteratorApi`

```
iterator.has_next()         -> bool
iterator.get_next(out_trace) -> None
```

Pybind iterator pattern: caller passes a writable `Trace` (or `Sequence`) into `get_next`, which fills it. Loop while `has_next()`. Use this when the trace is too large to materialize at once.

### Enums

```
arch_e:            EINSTEIN=1, FEYNMAN=2, SCHRODINGER=4
data_format_t:     DATA_FORMAT_INVALID=0, DATA_FORMAT_FP16=1, DATA_FORMAT_CB16=2,
                   DATA_FORMAT_FP32=3, DATA_FORMAT_XP16=4
operand_type_t:    OPERAND_TYPE_INVALID=0, OPERAND_TYPE_DEST=1,
                   OPERAND_TYPE_SRC0=2, OPERAND_TYPE_SRC1=3, OPERAND_TYPE_SRC2=4
```

- `arch_e` — internal codename for the WSE generation (Einstein=WSE-1, Feynman=WSE-2, Schrodinger=WSE-3).
- `data_format_t` — operand data format per instruction. `DATA_FORMAT_XP16` is a packed 16-bit form.
- `operand_type_t` — which operand slot of an instruction (`SRC0`/`SRC1`/`SRC2`/`DEST`).

### Free functions

```
get_operand_format(arch: arch_e, instr_field: int, operand_type: operand_type_t) -> data_format_t
get_opname_size() -> int
```

`get_operand_format` decodes an instruction's operand format bits given the architecture and which operand you're asking about. `get_opname_size` returns the fixed buffer size used internally for opcode strings.

## `cerebras.sdk.debug.lib.rectangleopspybind`

Cross-PE binary reads — useful when you want to dump a region of PE memory in one call rather than per-PE `read_symbol`s.

### `RectangleDebugger` (and variants)

Three classes, all with the same `dumpcore` / `read` shape. The factory `get_debugger(...)` picks the right one for you.

| Class | When |
|---|---|
| `RectangleDebuggerSim` | The runtime is a simulator. |
| `RectangleDebuggerCM` | Cluster manager / real-system path. |
| `RectangleDebugger` | Base class — don't instantiate directly. |

```
debugger.dumpcore(path: str) -> None
debugger.read(x: int, y: int,
              callback: Callable[[int, int, int, bytes], None]) -> None
```

`read(x, y, callback)` invokes `callback(x, y, offset, bytes_chunk)` for each PE memory region. The callback signature is `(int, int, int, bytes) -> None` — the third arg is the address within the PE; the fourth is the raw bytes.

### Free: `get_debugger(ip, x, y, w, h)`

```
get_debugger(ip: str, x: int, y: int, w: int, h: int) -> RectangleDebugger
```

Factory. `ip` is the simulator address (or `"local"` for in-process). `(x, y, w, h)` specifies the rectangle to read.

## `cerebras.sdk.debug.lib.wavelet_trace.wavelettracepybind`

> The module ships two name typos that the SDK has not fixed: `Wavlets` (missing 'e') and `WavletTrace` (missing 'e'). Use them as spelled — the canonical-looking `Wavelets` / `WaveletTrace` don't exist.

### `SimfabWaveletTrace(dump_path)`

```
SimfabWaveletTrace(dump_path: str) -> SimfabWaveletTrace

wt.get_wavelets(x, y)                                  -> WaveletTraceIterator
wt.get_wavelets_per_colors(x, y, color_ids: List[int]) -> WaveletTraceIterator
wt.get_backpressure_trace(x, y)                        -> List[BackPressure]
wt.get_backpressure_trace_per_colors(x, y, color_ids)  -> List[BackPressure]
```

The post-mortem wavelet view. `get_wavelets` returns an iterator (use `has_next` / `get_next`); `get_backpressure_trace` returns a list of back-pressure events.

### `SimfabWaveletTimeline(dump_path)`

```
SimfabWaveletTimeline(dump_path: str) -> SimfabWaveletTimeline

tl.get_wvlt_timeline(x, y, count)                                -> List[WaveletTimelineEntry]
tl.get_bkpr_timeline(x, y, count)                                -> List[BkprTimelineEntry]
tl.get_wvlt_and_bkpr_timeline_proto(x, y, count1, count2, count3) -> object
```

Wavelet timeline view — same data as `SimfabWaveletTrace` but ordered into a timeline for visualization. The `_proto` variant returns a serialized protobuf payload for the SDK's GUI tooling.

### Value types

```
Wavelet                  # opaque; .__init__()
Wavlets(arr)             # array container; .get_wavelet(i) -> Wavelet; .num_wavelets() -> int
BackPressure             # opaque event record
BkprTimelineEntry        # timeline entry
WaveletTimelineEntry     # timeline entry
```

`Wavlets(numpy.ndarray[Wavelet])` is the spelling — yes, missing 'e'. `WavletTrace` (also missing 'e') is an alternate trace class exposed alongside `SimfabWaveletTrace`; both have the same `get_wavelets` / `get_wavelets_per_colors` shape. Pick `SimfabWaveletTrace` for new code unless you have a specific reason.

### Iterator pattern

```
WaveletTraceIterator
  .has_next() -> bool
  .get_next(out_trace) -> None

WaveletTraceIteratorApi
  .has_next() -> bool
  .get_next(out: Wavlets) -> None
```

Two iterator variants; `WaveletTraceIteratorApi` writes into a `Wavlets` container, useful when you want to materialize a batch.

## Worked example — dump core, walk the instruction trace

```python
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import (
    SdkRuntime, SdkTarget, SimfabConfig, get_platform,
)
from cerebras.sdk.debug.lib.instruction_trace.sdkinstrtracepybind import (
    SimfabInstructionTrace, Trace,
)

config   = SimfabConfig(dump_core=True)
platform = get_platform(addr=None, config=config, target=SdkTarget.WSE3)

rt = SdkRuntime("out", platform)
rt.load(); rt.run()
rt.launch("compute", nonblock=False)
rt.dump_core("dump.cs1")
rt.stop()

# Post-mortem: walk instructions on PE (0, 0)
trace = SimfabInstructionTrace("dump.cs1", "out")     # elf_dir == compile output dir
tasks = trace.get_tasks(0, 0)
for tid in tasks:
    it = trace.get_instructions_per_task(0, 0, tid)
    out = Trace(
        np.zeros(64, dtype=object),   # buffer for Instruction[]
        np.zeros(8,  dtype=object),   # buffer for Sequence[]
    )
    while it.has_next():
        it.get_next(out)
        for ins in out.instrs():
            print(tid, ins.opname())
```

The exact dtypes for the `Trace` buffers depend on the iterator implementation; consult bundled SDK examples (`sdk_debug_instr_trace.py` under `${SDK}/cs_sdk/py_root/cerebras/sdk/` — check via `cs_python -c "import cerebras.sdk.sdk_debug_instr_trace as m; print(m.__file__)"`) for the canonical buffer-sizing recipe.

## Worked example — peek at PE state without core dump

`read_symbol` is the fastest live-debug path — no dump required, no post-mortem tooling.

```python
rt = SdkRuntime("out")
rt.load(); rt.run()
rt.launch("compute", nonblock=False)

y_at_origin = rt.read_symbol(0, 0, "y", dtype="float32")
y_at_corner = rt.read_symbol(3, 0, "y", dtype="float32")
assert np.allclose(y_at_origin, expected_origin)
assert np.allclose(y_at_corner, expected_corner)

rt.stop()
```

Each `read_symbol` round-trips a small RPC, so don't put it in a hot loop. For comprehensive end-of-run state, use `memcpy_d2h` on a flattened buffer instead.

## Gotchas

- **`dump_core` requires `SimfabConfig(dump_core=True)`.** Without the flag, `rt.dump_core("path")` silently does nothing. Single most common debug-flow trap.
- **The dump and the ELF directory must come from the same compile.** Post-mortem readers cross-reference instruction addresses against symbol tables in the ELF — mismatched dirs give garbage `get_source_line` mappings.
- **Live `read_symbol` is sim-only.** On a real system it either returns empty or raises, depending on platform. Branch on `platform.is_simulation()`.
- **Two preserved typos: `Wavlets`, `WavletTrace`.** Both ship in `wavelettracepybind` with the missing 'e'. Spelling them correctly produces `AttributeError`.
- **`coord_logical_to_physical` doesn't go the other way.** There is no `coord_physical_to_logical` — to map a trace report's physical coord back to your layout's logical coord, build the inverse table at start-of-run.
- **`get_source_line` resolution depends on debug info being in the ELF.** A release-mode compile may strip it; results are file=`"<unknown>"`, content=`""`. Use the debug compile flow (see SKILL-TOOLCHAIN.md).
- **`SimfabInstructionTrace` and `SimfabInstructionTraceCtf` are not the same class.** The CTF variant in `csldebugpybind` is the lower-level CTF reader; the non-CTF variant in `sdkinstrtracepybind` is the higher-level façade. The C++ class hierarchy connects them (the higher-level class wraps the CTF one), but the Python types are distinct.
- **`RectangleDebugger.read` is push-style.** You provide a callback; the debugger calls you with each chunk. Don't expect a return value of bytes.
- **Iterators consume the underlying trace stream.** Calling `has_next` after `get_next` returned the final chunk is safe (`False`), but you can't "reset" — re-construct the iterator if you need a second pass.

## See also

- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — entry-point overview.
- [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) — the rest of `SdkRuntime` (memcpy, RPC, streams).
- [SKILL-SDKRUNTIME-TYPES.md](SKILL-SDKRUNTIME-TYPES.md) — `SimfabConfig(dump_core=True)` etc.
- [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md) — when running SdkLayout programs, the dump / read flow is unchanged.
- [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) — `cslc` debug flags that populate the ELF debug-info `get_source_line` consumes.
- `_generated/sdkruntime-surface.json` — every signature in this file, machine-readable.
- `_generated/sdkruntime-symbols.txt` — C++ symbol surface; the `cerebras::sdk::*` symbols underpinning each pybind class.
- Bundled SDK scripts (under `${SDK}/cs_sdk/py_root/cerebras/sdk/`): `sdk_debug_instr_trace.py`, `sdk_debug_wavelet_trace.py`, `sdk_debug_pe_symbol_dump.py`, `sdk_debug_shell.py`, `sdk_smoke.py`. These exercise the modules above end-to-end and are the canonical references for the iterator buffer-sizing recipes.
