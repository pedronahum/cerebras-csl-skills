# cerebras-csl-skills

Claude Code skills for developing in **CSL** (Cerebras Software Language) — the kernel language for the Cerebras Wafer-Scale Engine.

A complete domain-by-domain reference set: one router skill, fifteen CSL-language deep-dives (syntax, type system, comptime, generics, DSD/DSR data movement, the event-driven task model, fabric routing, the full builtin and standard-library catalogues, the SIMD model), and an eight-file host-side bundle that documents the Python + C++ SdkRuntime / SdkLayout / debug / routing surface — pinned to a specific SDK build with provenance dumps under `_generated/`. Each file ships with YAML frontmatter so Claude Code can trigger-match on the topic at hand.

Modeled after [`avsm/ocaml-claude-marketplace`'s oxcaml skills](https://github.com/avsm/ocaml-claude-marketplace/tree/main/plugins/ocaml-dev/skills/oxcaml).

## Install

```sh
./install.sh
```

Symlinks this repo into `~/.claude/skills/csl/` so edits here apply immediately. Idempotent — safe to re-run. Claude Code discovers the skill on next launch.

## What's in here

`SKILL.md` is the entry point — frontmatter + a cheat sheet covering numeric types, vars/ptrs/fns, control flow, anonymous struct literals, comptime, imports, the `layout` block, DSDs, DSD ops, and tasks, plus common patterns and gotchas. Cheat-sheet syntax is verified against the bundled `gemv-01/02/05` tutorials.

### CSL language reference (15 files)

| File | Owns |
|---|---|
| [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) | `cslc` / `cs_python` / `sdk_debug_shell` wrappers; `CSL_IMPORT_PATH` bind-mount semantics; every meaningful `cslc` flag; the canonical compile-run cycle; packaging extra Python deps via `SINGULARITYENV_PYTHONPATH`; common error messages and their actual causes; Lima/Rosetta specifics on Apple Silicon. |
| [SKILL-SYNTAX.md](SKILL-SYNTAX.md) | The surface syntax framed as a delta from Zig — declarations (`const`/`var`/`param`), pointer kinds (`*T`, `[*]T`, `*const T`), `fn` vs `task`, control flow (`for ... \|elem, idx\|`, `while ... : (...)`), labelled blocks, anonymous struct literals, the `comptime { }` and `layout { }` top-level blocks. |
| [SKILL-TYPES.md](SKILL-TYPES.md) | Arbitrary-width integers with the 16/32-bit ABI-sized constraint at export boundaries; three FP16 formats (`f16`/`cb16`/`bf16`); comptime-only types; struct/union/enum families incl. `extern` and `packed` variants; multi-dim arrays `[N, M]T` with comma syntax; pointer coercions; peer-type resolution. |
| [SKILL-COMPTIME.md](SKILL-COMPTIME.md) | Comptime-known values; `comptime var`, `comptime fn_call(...)`, and `comptime { }` block; comptime-only types; control-flow pruning (untaken branches not semantically checked — what makes `@is_arch` work); `@comptime_assert`, `@comptime_print`, `@is_comptime`. |
| [SKILL-GENERICS.md](SKILL-GENERICS.md) | `comptime T: type` vs `anytype`; monomorphization; constraining type params via `@comptime_assert` + `<types>` predicates; specialising logic with `if (comptime ...)`; functions that return `type`; deriving types from values via `@type_of` / `@element_type` / `@rank`. |
| [SKILL-STORAGE.md](SKILL-STORAGE.md) | `extern` / `export` cross-translation-unit visibility; `linkname` for symbol-name overrides; `linksection` for ELF section placement; export-compatible type set; mixing rules; the distinction from `@export_name` / `@export_symbol` (which is the host boundary). |
| [SKILL-MODULES.md](SKILL-MODULES.md) | `@import_module` with the two filename forms (angle-bracket `"<lib/name>"` for in-container stdlib, relative path for user code); parameter-driven specialization; member access; symbol mangling; `CSL_IMPORT_PATH` interaction. |
| [SKILL-DSDS.md](SKILL-DSDS.md) | All six DSD types (`mem1d_dsd`, `mem4d_dsd`, `circbuf_dsd`, `fabin_dsd`, `fabout_dsd`, `fifo_dsd`); the `tensor_access` lambda syntax; mutators (`@increment_dsd_offset`, `@set_dsd_*`); the full async-op options surface (`.async`, `.activate`, `.unblock`, `.on_control`); microthread allocation, priority, SIMD mode, `wavelet_index_offset`, `control_transform`, switch advancement, reset-on-completion. |
| [SKILL-DSRS.md](SKILL-DSRS.md) | The five DSR slot types + XDSR + SR; `@get_dsr` / `@get_xdsr` / `@get_sr`; `@load_to_dsr` / `@load_to_dsr_xdsr` / `@load_to_dsr_xdsr_sr`; `.save_address` for sequential chunks; `.single_step` for `@map`; explicit FIFO slot allocation. |
| [SKILL-TASKS.md](SKILL-TASKS.md) | Data / local / control tasks and their triggers; ID types (`data_task_id`, `local_task_id`, `control_task_id`); binding builtins; activation, `@block` / `@unblock`; the WSE-3 `@initialize_queue` requirement; reserved task ID slots for memcpy and runtime; DSD-op `.activate` / `.unblock` completion hooks. |
| [SKILL-MICROTHREADS.md](SKILL-MICROTHREADS.md) | WSE-3 explicit microthreads (`@get_ut_id`, `.ut_id`); how they differ from WSE-2's implicit queue-based model; default-resolution priority hierarchy; many-to-many queue↔microthread relationship; the related WSE-3 dispatch builtins (`@queue_flush`, `@set_empty_queue_handler`, `@set_control_task_table`, `@bind_rotating_tasks`). |
| [SKILL-ROUTES.md](SKILL-ROUTES.md) | Colors as logical channels; per-tile routes (`NORTH`/`SOUTH`/`EAST`/`WEST`/`RAMP`); RX/TX direction control; switch tables, `advance_switch`, `control_transform`; color swapping (XOR-paired colors); CE Injection (WSE-2 only); the host-side `SdkLayout` counterparts (`Color`, `Edge`, `Route`, `RoutingPosition`). |
| [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) | Survey of every bundled `<...>` library: `complex`, `control`, `data_utils`, `debug`, `directions`, `dsd_ops`, `empty`, `layout`, `malloc`, `math`, `random`, `simprint`, `string`, `tile_config` (with its color/exception/filter/queue-status/priority/switch/teardown submodules), `time`, `timer`, `types`, `kernels/fft`, `kernels/tally`, `collectives_2d`, plus the WSE-3-only `message_passing`. |
| [SKILL-BUILTINS.md](SKILL-BUILTINS.md) | Catalogue of every `@`-prefixed builtin, organised by category — type/comptime, comptime utilities, strings, array introspection, struct introspection, DSD construction/mutation, integer/bitwise DSD ops, the full f16/f32 floating-point DSD-op families, tasks & events, task ID constructors, colors & queues, configuration & layout, random, ranges, higher-order (`@map`), symbol exports / RPC, plus the WSE-3-only set. |
| [SKILL-SIMD.md](SKILL-SIMD.md) | Automatic memory SIMD (8-bank 6-KiB-each layout, per-cycle 2-read+1-write capacity, the `bank_1 % 4 != bank_2 % 4` parallel-read rule, alignment recommendations, stride-impact on width, per-arch ceilings); explicit fabric SIMD via `.simd_mode` on `fabout_dsd`; WSE-2-only SIMD on FIFOs. |

### Host-side / SDK runtime reference (8 files, pinned to SDK 2.10.0)

Reference for the Python + C++ host API — the side that loads the compiled binary, drives memcpy / RPC / streams, and inspects state. Pinned to a specific SDK build (sha256 in `_generated/SDK-VERSION.txt`) so signatures don't drift silently. Regenerate the pinned dump with `scripts/refresh_sdk_surface.sh` whenever the SIF changes; diffs in `_generated/` make drift auditable.

| File | Owns |
|---|---|
| [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) | The narrative side. Three integration models: classic memcpy (bulk + RPC), streaming memcpy (data through fabric colors), and `SdkLayout` (Python-driven topology with explicit ports). The `<memcpy/get_params>` / `<memcpy/memcpy>` PE-side library, the `unblock_cmd_stream` discipline, when to reach for which model. |
| [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) | Entry-point reference. API surface map across all 7 captured pybind / Python modules; lifecycle (`load` → `run` → memcpy/launch/send → `stop`); the `SdkRuntime` / `SdkLayout` / `SimfabConfig` constructor overloads; two worked minimal examples (memcpy + SdkLayout); the C++ ↔ Python cross-reference patterns (the hidden `MemcpyOptions` kwarg splat, `unsigned short` as the universal ID type). |
| [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) | Per-method `SdkRuntime` reference. Every callable with its Python signature(s), demangled C++ signature, kwargs, return type, failure modes, and a minimal example. Method groups: lifecycle, bulk memcpy, broadcast/stride memcpy, RPC (`launch` / `call`), streams (`send` / `receive` / `receive_tofile`), name resolution (`get_id` / `get_port_id`), task handles, debug. Ends with a flat symptom → cause failure-mode catalogue. |
| [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md) | `SdkLayout`, `CodeRegion`, ports, routes, streams. Layout-flow diagram; `create_code_region` / `connect` / `create_input_stream` / `compile` per-method coverage; routing via `paint` / `paint_all` / `paint_range`; parameter binding via `set_param` / `set_param_all` (incl. the `Color`-kwarg overloads); `set_symbol_all` for bulk init; the `Color` / `RoutingPosition` / `Edge` / `Route` topology types. Worked end-to-end example (host stream → 2×1 region → host stream). |
| [SKILL-SDKRUNTIME-TYPES.md](SKILL-SDKRUNTIME-TYPES.md) | Value types and enums. `Task` (opaque handle semantics + per-runtime arena rule), `SimfabConfig` (the four kwargs incl. the real `num_threads=16` default), `SdkExecutionPlatform` (`is_simulation` / `is_system`), `SdkCompileArtifacts` (`(path)` constructor + `add_port_mapping`), every enum (`SdkTarget`, `MemcpyDataType`, `MemcpyOrder`, `Edge`, `Route`, `FP16TYPE`) with numeric values for hex-dump cross-checking and explicit "never hardcode by value" rule. |
| [SKILL-SDKRUNTIME-DEBUG.md](SKILL-SDKRUNTIME-DEBUG.md) | Both halves of the debug surface. Live: `dump_core` (and its `SimfabConfig(dump_core=True)` prerequisite), `dump_elf_core`, `read_symbol`, `coord_logical_to_physical`. Post-mortem: the four pybind modules — `csldebugpybind` (CTF trace readers + symbol tables), `sdkinstrtracepybind` (high-level instruction trace + opcode-format enums), `rectangleopspybind` (cross-PE binary reads), `wavelettracepybind` (wavelet timelines + back-pressure tracking, including the SDK-shipped `Wavlets` / `WavletTrace` typos). Two worked examples. |
| [SKILL-SDK-UTILS.md](SKILL-SDK-UTILS.md) | `cerebras.sdk.sdk_utils` reference. Cycle counting (`calculate_cycles`, `sub_ts`, `make_u48`, `float_to_hex`), memcpy data shaping (`memcpy_view`, `input_array_to_u32`, `cast_uint32`), RPC schema introspection (`get_api_info_dict`, `parse_host_callable_api`, `check_rpc_api`, `is_valid_primitive_type`), and `getOutputNameFromCompileOptions`. Worked example for the full timestamp round-trip. |
| [SKILL-SDKRUNTIME-ROUTE.md](SKILL-SDKRUNTIME-ROUTE.md) | Low-level memcpy-routing internals — *prototype scope* per the SDK's own labelling. `routepybind.CslIoRouting` (the pybind primitive) plus the Python pipeline (`CslWseNetlist` → `CslWsePinTable.create_pin_assignments()` → `CslWseRouter.route()` → `CslWseRouterAssembler.generate_route_elf()` → `MEMCPY_XY_ROUTES.elf`). Documents the `CardinalDirection` vs `Route` numeric-ordering footgun. End-user programs do not touch this surface. |
| [SKILL-SDKRUNTIME-CPP.md](SKILL-SDKRUNTIME-CPP.md) | The *reconstructed* C++ side of the API. Documents `_generated/cerebras_sdkruntime.hpp` (300-line reverse-engineered header), with a fact-by-fact provenance table (what each piece of info came from + how strong the evidence is), the `MemcpyOptions` field-order claim and how it was inferred, four potentially-undocumented kwargs (`setup_phase_only`, `run_phase_only`, `wio_flows`, `worker`) found in the pybind .rodata, the diagnostic strings the runtime emits, and the toolchain-reality reasons this header is documentation rather than a build artifact. |

## How Claude Code uses these skills

Each `SKILL-*.md` carries YAML frontmatter (a `name` and `description`). When you ask Claude Code about a topic that overlaps with one of these descriptions, the matching skill is loaded as context — so a question like *"why doesn't `@import_module('../shared/foo.csl')` work?"* surfaces the `csl-toolchain` and `csl-modules` skills, which together explain that `CSL_IMPORT_PATH` needs to bind the parent directory into the Apptainer container.

You don't have to invoke skills explicitly. The descriptions are designed to be load-bearing for the trigger-match: domain terms (`DSD`, `fabin_dsd`, `microthread`, `memcpy_h2d`, `CSL_IMPORT_PATH`, `@bind_data_task`) appear in the frontmatter precisely so they catch.

## Source of truth

Authoritative reference for the CSL language: <https://sdk.cerebras.net/csl/language_index>. When a CSL skill file disagrees with the upstream docs, the upstream docs win — open an issue / PR.

The host-side / SDK runtime reference is pinned to a specific SDK build: **2.10.0** (build `sdk-202604101435`, git `4586d3f0d8`), with provenance recorded in `_generated/SDK-VERSION.txt`. For those eight files the source of truth is pybind11 introspection + the demangled C++ symbol surface of `/cbcore/lib/lib*.so`, captured at extraction time — the upstream API docs at <https://sdk.cerebras.net/api-docs/sdkruntime-api> often lag a release. To refresh against a newer SIF, run `scripts/refresh_sdk_surface.sh`; the resulting diff in `_generated/` makes any drift in the curated `.md` files auditable.

All skills target `--arch=wse3`. Each skill includes inline upstream-docs / source-of-truth links at the bottom for follow-up reading.

## Layout

```
.
├── README.md                          # this file
├── SKILL.md                           # router; cheat sheet; cross-references
├── SKILL-{TOOLCHAIN,SYNTAX,…}.md      # 15 CSL-language deep-dives
├── SKILL-{HOST-DEVICE,SDKRUNTIME*,    # 8-file host-side / SDK runtime
│   SDKLAYOUT,SDK-UTILS}.md            #   reference (pinned to SDK 2.10.0)
├── _generated/                        # pinned dump of the SDK pybind + C++ surface
│   ├── SDK-VERSION.txt                #   provenance summary
│   ├── sdkruntime-surface.json        #   pybind11 introspection (every signature)
│   ├── sdkruntime-symbols.txt         #   demangled C++ symbol surface (10 .so libs)
│   ├── sdkruntime-pybind-imports.txt  #   curated user-facing C++ API (pybind's imports)
│   ├── sdkruntime-preconditions.txt   #   runtime assertion strings mined from .rodata
│   ├── sdkruntime-libstdcpp.txt       #   libstdc++ ABI requirements (GLIBCXX/CXXABI)
│   └── cerebras_sdkruntime.hpp        #   reconstructed C++ header
├── scripts/
│   ├── extract_sdk_surface.py         # pybind introspection (runs under cs_python)
│   ├── refresh_sdk_surface.sh         # host driver (Lima → SIF → _generated/)
│   └── generate_cpp_header.py         # reconstruct cerebras_sdkruntime.hpp from dumps
├── install.sh                         # idempotent symlink into ~/.claude/skills/csl/
└── .gitignore
```

## Contributing

Open issues / PRs welcome. Style conventions used throughout:

- Frontmatter on every file: `name` + `description`. Make descriptions specific and term-dense — they're load-bearing for Claude Code's trigger matching.
- Tables for reference material (types, flags, builtins, options).
- Progressive code examples (simple → complex), grounded in real bundled-tutorial syntax wherever possible.
- A *Gotchas* section near the end of each file.
- Cross-references between files via relative markdown links.
- Inline upstream-doc URL at the bottom.
