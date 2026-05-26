---
name: csl-sdkruntime-cpp
description: Reference for the *reconstructed* C++ side of the Cerebras SDK runtime API — what's in `_generated/cerebras_sdkruntime.hpp`, where each piece of information came from, and where the limits are. The SDK ships no C++ headers; this file documents the best-effort recovery built from the demangled symbol surface of `/cbcore/lib/*.so` plus pybind11 introspection. **Not Cerebras-authoritative.** Pinned to SDK 2.10.0.
---

# Reconstructed C++ Header — Provenance and Limits

The Cerebras SDK does not ship C++ headers. `/cbcore/lib/` contains 142 stripped `.so` files and nothing else — no `*.h`, no DWARF debug info, no source maps. The public C++ API is reachable only by:

1. Demangling the symbols pybind11 binds against (`nm -D --demangle /cbcore/lib/lib*.so`).
2. Asking pybind11 itself what it exposes (`import` the pybind module, walk `dir()` / `__doc__`).
3. Mining the pybind `.so` file's `.rodata` section for kwarg-name strings, defaults, diagnostic messages, and embedded mangled type references.

Combined, those three sources let us reconstruct a usable header: `_generated/cerebras_sdkruntime.hpp`. This file documents what it contains, where each piece came from, and what is still genuinely unknown.

For the Python side of the same API, see [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md). For the narrative on when to reach for which integration model, see [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md).

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

`_generated/cerebras_sdkruntime.hpp` is generated against that exact SIF by `scripts/generate_cpp_header.py`. Regenerate after any `scripts/refresh_sdk_surface.sh` run.

## What's in the header

Eleven classes plus three top-level enums plus a struct, all in `namespace cerebras`:

- **Top-level enums** (values authoritative — sourced from pybind11 `__members__`): `SdkTarget`, `MemcpyDataType`, `MemcpyOrder`.
- **`MemcpyOptions`** struct (RECONSTRUCTED — see below). Fields: `streaming`, `data_type`, `order`, `nonblock`.
- **`SimfabConfig`** struct (RECONSTRUCTED — see below). Fields: `num_threads`, `suppress_trace`, `dump_core`, `core_path`.
- **`SdkExecutionPlatform`** (single ctor + one internal method).
- **`SdkCompileArtifacts`** (two ctors — one string-only, one with `nlohmann::json` that pybind doesn't expose).
- **`SdkRuntime`** + nested **`Task`** (the bulk — 22 methods + the 8-arg constructor).
- **`SdkLayout`** + nested **`Color`**, **`RoutingPosition`**, **`EdgeRouteInfo`**, **`PortHandle`**, **`CodeRegion`**, plus nested enums **`Edge`**, **`Route`**, **`FP16TYPE`**.

The four nested classes inside `SdkLayout` (`Color`, `RoutingPosition`, `EdgeRouteInfo`, `PortHandle`) have **zero C++ symbols** in the runtime `.so` files — they're header-only / inline. Their members are documented as commented pybind signatures inside the class body; that's all the dump can say about them.

## Where each piece of information came from

For every method in the header, every individual fact is sourced from one of these origins. The "strength" column indicates how reliable each is.

| Fact | Origin | Strength |
|---|---|---|
| Method exists | `nm -D --demangle` on the runtime `.so` | **Strong** (it's compiled in) |
| Parameter types | `nm` mangling decoded by `c++filt` | **Strong** (encoded in ABI) |
| Parameter `const`-ness (`const&` vs `&`) | `nm` mangling | **Strong** |
| Method `const`-ness (trailing `const`) | `nm` mangling | **Strong** |
| Class scope (nested vs top-level) | `nm` qualified name | **Strong** |
| Overload count | `nm` (every overload gets its own symbol) | **Strong** |
| **Return type** | pybind11 docstring `(...) -> RetType` | **Medium** — pybind reflects what `py::class_::def<R(Args...)>` deduced. Sometimes Python-flavored (`object`, `Tuple[int, int]`); we translate. |
| **Argument names** | pybind11 docstring `arg_name: type` | **Medium** — present only when binding used `py::arg("name")`. Otherwise `arg0/arg1/...`. |
| **Default argument values** | pybind11 docstring `arg: T = value` | **Medium** — present only when binding used `py::arg("name") = default`. Otherwise absent. |
| Enum members + values | pybind11 `__members__` dict | **Strong** (real `enum class` values, queryable at runtime). |
| `MemcpyOptions` / `SimfabConfig` field set | pybind11 `**kwargs` splat names | **Strong** (these are the kwargs the binding requires). |
| `MemcpyOptions` field order | Order of name-strings in pybind `.so` `.rodata` | **Inferred** — see [the MemcpyOptions section](#the-memcpyoptions-field-order-claim) below. |
| Padding / alignment of structs | none | **Unknown** — would require ABI probing or DWARF (we have neither). |
| Member visibility (`public`/`private`) | none | **Unknown** — header marks everything `public`. |
| `virtual` / `final` / `inline` qualifiers | none directly | **Unknown** — RTTI grep showed no virtual user-facing classes, so likely none. |
| Inline / template-only methods | none | **Lost** — never emit standalone symbols. |

## Things the header does NOT recover

Spelled out in the header's top comment, but recapping for emphasis:

- **No return types in raw nm output.** The Itanium ABI doesn't include return types in mangling for normal functions (only for templates and operators). We compensate by pulling return types from the pybind docstring `... -> ReturnType` field, mapped to C++ types where possible. Methods with no pybind binding remain `auto`.
- **No default argument values in nm.** Pybind docstrings give us `arg: T = default` only when the binding wrote `py::arg("name") = default`. For most arguments we have no defaults at all.
- **No padding/alignment knowledge** for `MemcpyOptions`, `SimfabConfig`. The field SET is correct; the LAYOUT is a guess. Constructing one via aggregate-init may write fields in the wrong byte offsets.
- **No member visibility.** Everything is rendered `public`. The runtime likely has `private` helpers we can see (e.g. `SdkRuntime::Task::get_mtask`), and we tag them `/* internal — not in pybind */`, but their actual access modifier in the original header is unknown.
- **No body / inline definitions.** Method bodies of `Color`, `RoutingPosition`, `EdgeRouteInfo`, `PortHandle` are inlined in the SDK's source and never emit symbols. We have no recovery path.

## The `MemcpyOptions` field-order claim

Three pieces of evidence:

1. **The field set is rock-solid.** The pybind binding requires `streaming`, `data_type`, `order`, `nonblock` as kwargs (confirmed by the diagnostic string `"Must specify the streaming, data_type, order, and nonblock kwargs to memcpy_h2d()"` in the pybind `.so` `.rodata`).
2. **The names appear contiguously in `.rodata`**, in the order `streaming, data_type, order, nonblock` (offsets that are adjacent in `strings(1)` output, lines 5892–5895 in this SDK's pybind `.so`). pybind11's `.def(...)` chains `py::arg("name")` calls and writes their strings sequentially into `.rodata`.
3. **The pybind binding convention** is to declare `py::arg(...)` in the same order as the C++ struct fields (so the lambda body's aggregate init lines up). This is convention, not contract. Our header trusts it.

If you intend to **construct `MemcpyOptions` from C++**, do not rely on the inferred field order. Either:

- Probe field order experimentally (compile a probe `.cpp` inside the SIF, set sentinel values, observe what reaches the device or what pybind reads back).
- Or write a `MemcpyOptions` instance via pybind's own Python interface (which uses the splat path it knows is correct).

## New facts the recovery surfaced

Mining beyond the obvious nm/pybind path produced several things the existing skill files didn't have:

### The 4 previously-undocumented `SdkRuntime` ctor kwargs (RESOLVED)

The pybind `.so` `.rodata` exposed four kwargs (`setup_phase_only`, `run_phase_only`, `wio_flows`, `worker`) that don't appear in pybind's `__doc__`. A second pass mining `libsdkruntime.so` `.rodata` for assertion strings + finding the `cerebras::SdkRuntime::Impl::generate_wio_flow()` / `generate_wio_flow_directlink()` methods nailed their semantics:

| Kwarg | What it does | Evidence |
|---|---|---|
| `setup_phase_only` | Map onto an internal `sdk_setup_phase_only` flag. When `true`, the runtime refuses `run()` calls — used to compile/setup-only without executing. Mutually exclusive with `run_phase_only`. | Strings `"Setup phase (sdk_setup_phase_only=true) cannot call run()"` and `"sdk_setup_phase_only and sdk_run_phase_only must be mutual exclusive"` in `libsdkruntime.so`. |
| `run_phase_only` | Onto internal `sdk_run_phase_only`. When `true`, refuses `load()` and assumes the binary is already loaded from a prior setup run. Pair with `setup_phase_only=true` for split setup/run workflows. | Strings `"Run phase (sdk_run_phase_only=true) cannot call load()"` and `"Run phase only: must call run() after the Sdkruntime()"`. |
| `wio_flows` | Path to a `wio_flows.json` describing fabric LVDS pin routing for H2D / D2H / cmd / ingress channels. Consumed by `cerebras::SdkRuntime::Impl::generate_wio_flow()` (PIMPL — function visible in nm). | Strings `"[parse_wio_flows] Reading file "`, `"cannot find lvds of H2D in the wio_flows.json"` (also for `cmd`, `D2H`, `D2H data cmd`, `ingress`), `"mkdtemp failed to create a temporary folder for wio_flows.json"`. |
| `worker` | MPI worker mode. Requires `OMPI_COMM_WORLD_SIZE` and `OMPI_COMM_WORLD_RANK` env vars to be set — the runtime checks `workers.json` against the MPI world size. | Strings `"workers.json requires OMPI_COMM_WORLD_SIZE"`, `"workers.json requires OMPI_COMM_WORLD_RANK"`, `"OMPI_COMM_WORLD_SIZE is not equal number of workers"`. |

These are real kwargs accepted by the runtime, not just stray strings. Specifics like the JSON file's expected schema aren't recoverable from the binaries; the SDK presumably documents them internally.

### Precondition / assertion catalog

`.rodata` of `libsdkruntime.so` + `libsdk_layout.so` + `libstreamer.so` carries the *actual* assertion strings the runtime emits when its preconditions fail. These are the exact constraints in force at runtime, much higher fidelity than what pybind's docstrings tell you. The full pinned list is in `_generated/sdkruntime-preconditions.txt`. Selected highlights:

**Lifecycle order**

- `Cannot call run() multiple times, or call run() if load() has not been called`
- `Cannot call stop() multiple times, or call stop() if run() has not been called`
- `SdkRuntime must be running to accept memcpy commands.`
- `Cannot call dump_core() if load() has not been called`
- `Cannot dump core on real hardware` (so `dump_core` / `dump_elf_core` are sim-only — confirmed)

**memcpy region checks**

- `h2d subrectangle must be inside the core rectangle`
- `d2h subrectangle must be inside the core rectangle`
- `row_stride or col_stride must be positive` (for `memcpy_h2d_stride`)
- `Illegal data type option for memcpy` (rejects unknown `MemcpyDataType` values)
- `Illegal order option for memcpy` (rejects unknown `MemcpyOrder` values)

**SdkLayout topology**

- `Number of ingress and egress tiles must be equal.`
- `All ingress tiles must be at the edge of the fabric` (similarly for egress)
- `Expects number of PE inputs to be less than the number of West ingress tile.` (and East)
- `The output port must have even number of wavelets`
- `Invalid rectangle dimensions - attempted to create a route that was outside the fabric. The kernel is too large (if running on WSE) or the fabric size is too small (if running in simulation).`
- `'hstack' requires at least one child.` / `'vstack' requires at least one child.`
- `cannot connect ports with incompatible data sizes.` / `... incompatible number of PEs.`
- `input port cannot have input route.` / `output port cannot have output route.`

**RPC**

- `Cannot find exported function with name ...` (when `launch` / `call` is given an unknown name)
- `functional protype does not match what is defined in the kernel` (RPC arg-list mismatch; note SDK typo "protype")

### libstdc++ ABI requirement

The pybind `.so` links against:

```
libstdc++.so.6   (from /cb/toolchains/buildroot/.../usr/lib/)
libgcc_s.so.1
libc.so.6
```

The bundled `libstdc++` exports up to **`GLIBCXX_3.4.32`** and **`CXXABI_1.3.14`** — those map to **GCC 13.x** runtime support. Anyone wanting to link C++ user code against the SDK's `.so` needs to either:

1. Build with GCC 13+ (or Clang configured against a matching libstdc++).
2. Bundle the SDK's `libstdc++.so.6` and use `LD_LIBRARY_PATH` to force load it.

Full version listing in `_generated/sdkruntime-libstdcpp.txt`.

### The `cerebras::SdkRuntime::Impl` PIMPL pattern

Two internal symbols visible in the runtime `.so`:

```
cerebras::SdkRuntime::Impl::generate_wio_flow()
cerebras::SdkRuntime::Impl::generate_wio_flow_directlink()
```

`SdkRuntime` is a PIMPL-pattern facade — the public `SdkRuntime` class holds an opaque `std::unique_ptr<Impl>`, with the heavy lifting (route generation, IPC, simulator coordination) on `Impl`. This is why the public surface is so small (~30 methods) compared to the 322 total `cerebras::*` symbols in `libsdkruntime.so` — the bulk is `Impl::*` and other internal helpers.

The reconstructed header declares `class Impl;` as a forward decl with no members.

### `cerebras::to_words<T>` template helper

Five `to_words<T>` template instantiations are exported from the runtime, one per dtype:

```cpp
template <typename T>
std::vector<unsigned short> cerebras::to_words(std::vector<T> const&);
// instantiated for T = float, int, unsigned int, short, unsigned short
```

This is the helper that powers the typed `runtime.send(name, numpy[float32])` overloads on the Python side. pybind's binding for those overloads calls `to_words<float>(...)` to pack the input into 16-bit wavelets, then dispatches to the canonical `send(string, void*, size_t, bool)`.

### Diagnostic strings worth knowing

Pulled verbatim from the pybind `.so`:

- `"Must specify the streaming, data_type, order, and nonblock kwargs to memcpy_h2d()."`
- `"Must specify the streaming, data_type, order, and nonblock kwargs to memcpy_d2h()."`
- `"Must specify the nonblock kwarg to '..."` (applies to `send`/`receive`)
- `"Internal data type of any memcpy_d2h() or memcpy_h2d() operation should be 32 bit."` — interesting: confirms the device-side payload is always 32-bit. The `MEMCPY_16BIT` `data_type` packs two 16-bit values per wavelet rather than transferring 16-bit wavelets directly.
- `"functional protype does not match what is defined in the kernel"` — `launch`/`call` RPC schema validation (note the typo "protype" in the SDK).
- `"overloading a method with both static and instance methods is not supported; error while attempting to bind "` — pybind binding-time error.

### Hidden `SdkCompileArtifacts` constructor

nm shows two ctors:

```
cerebras::SdkCompileArtifacts::SdkCompileArtifacts(std::string const&)
cerebras::SdkCompileArtifacts::SdkCompileArtifacts(std::string const&, nlohmann::json const&)
```

pybind only binds the first. The second takes a `nlohmann::json const&` — presumably a pre-parsed port-map. Internal use; not user-callable.

### `SdkExecutionPlatform` ctor + internal accessor

```
cerebras::SdkExecutionPlatform::SdkExecutionPlatform(std::string const&)
cerebras::SdkExecutionPlatform::load_fabric_config() const
```

Pybind exposes neither. The Python user always builds `SdkExecutionPlatform` via the three free functions (`get_platform` / `get_simulator` / `get_system`), which themselves have **no C++ symbols** — they exist only inside the pybind binding code as wrappers that call this constructor.

## The toolchain reality

Even with a clean header, *actually building* C++ against this SDK is a separate, harder problem:

1. **No C++ compiler in the SIF.** The SDK SIF includes `cslc`, `cs_python`, and supporting tools but not `g++`/`clang++`. You'd need to bring your own compiler that matches the SDK's `libstdc++` ABI (Ubuntu 24.04 / gcc 13 toolchain at the time of SDK 2.10.0). Easy on a matching host; hard cross-platform.
2. **All 142 `.so` files are intra-SIF dependencies.** Outside the SIF, `LD_LIBRARY_PATH` would need to point at copies of every `libcbkm-*`, `libcerebras_logger`, `libcs_grpc_utils`, `libsdk_*`, `libWs*`, MLIR/LLVM lib that the runtime references. Possible but fragile across SDK upgrades.
3. **No supported ABI surface.** Cerebras commits to the pybind API. The C++ ABI underneath is internal — any release can rename `cerebras::SdkRuntime::call`, refactor `MemcpyOptions`, change member alignment. Every SDK bump requires regenerating this header and auditing the diff.
4. **EULA.** `cerebras-software-eula.pdf` ships next to the SIF. Reverse-engineering an API surface to *understand and document* it is one thing; redistributing reconstructed headers as a parallel build artifact is a different question. Read it before scoping a build path.

Use the reconstructed header for **understanding** (documentation, IDE autocomplete of the Python wrapper's underlying types, code review of `run.py`-style scripts), not as a foundation for shipping C++ code.

## How to regenerate

After refreshing the dump for a new SDK:

```sh
scripts/refresh_sdk_surface.sh       # captures pinned dumps to _generated/
scripts/generate_cpp_header.py        # produces _generated/cerebras_sdkruntime.hpp
```

The generator is deterministic — same inputs produce identical output. A `git diff _generated/cerebras_sdkruntime.hpp` after a refresh shows exactly which signatures changed between SDK releases.

## Gotchas

- **The header is `#pragma once`-guarded but uses placeholder forward declarations** (`pybind11::object`, `pybind11::array`, `nlohmann::json`, `cerebras::IntVector`, `cerebras::Point<T>`, etc.). Including it as-is in a project that also includes the real headers for those types will produce redeclaration errors. The header is intentionally not buildable.
- **All return types of `cerebras::SdkLayout::Color`-family classes are `auto`** (in the rendered fallback comments). They show as pybind signatures; the underlying C++ return types are not recoverable.
- **`MemcpyOptions` aggregate-init order is a guess.** See above. Never write `MemcpyOptions opts{true, MemcpyDataType::MEMCPY_32BIT, MemcpyOrder::ROW_MAJOR, false}` and trust it without probing.
- **The `nlohmann::json` constructor of `SdkCompileArtifacts` is real but unsupported.** It exists; pybind doesn't expose it; relying on it bypasses the pybind layer that everyone else uses.
- **`SdkLayout` ctor argument names show as "platform" for all 3 overloads** because the generator uses the first pybind overload's named args. The actual semantics differ (`SdkExecutionPlatform` / `path` / `SdkTarget`). The types make this unambiguous despite the misleading name; don't trust the parameter name alone.
- **Method `Task::get_mtask() const` returns `auto`** in the header — we know from nm it returns `std::shared_ptr<MemcpyTask>` (it's the internal accessor), but the generator can't read return types from nm directly. Documented here for the record.

## See also

- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — entry-point overview of the SDK runtime (Python view).
- [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) — per-method Python reference, including the pybind signature each method exposes.
- [SKILL-SDKRUNTIME-TYPES.md](SKILL-SDKRUNTIME-TYPES.md) — `Task`, `SimfabConfig`, enums.
- `_generated/cerebras_sdkruntime.hpp` — the reconstructed header itself.
- `_generated/sdkruntime-symbols.txt` — the demangled C++ symbol surface (the primary input).
- `_generated/sdkruntime-surface.json` — pybind11 introspection (return types, arg names, defaults, enum values).
- `scripts/generate_cpp_header.py` — the generator.
- `scripts/refresh_sdk_surface.sh` — refresh-the-dumps driver.
