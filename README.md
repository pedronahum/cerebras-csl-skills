# cerebras-csl-skills

Claude Code skills for developing in **CSL** (Cerebras Software Language) — the kernel language for the Cerebras Wafer-Scale Engine.

A complete domain-by-domain reference set: one router skill plus 14 deep-dives covering the surface syntax, type system, comptime, generics, the DSD/DSR data-movement abstractions, the event-driven task model, host↔device transfer, fabric routing, the full builtin and standard-library catalogues, and the SIMD model. Each file ships with YAML frontmatter so Claude Code can trigger-match on the topic at hand.

Modeled after [`avsm/ocaml-claude-marketplace`'s oxcaml skills](https://github.com/avsm/ocaml-claude-marketplace/tree/main/plugins/ocaml-dev/skills/oxcaml).

## Install

```sh
./install.sh
```

Symlinks this repo into `~/.claude/skills/csl/` so edits here apply immediately. Idempotent — safe to re-run. Claude Code discovers the skill on next launch.

## What's in here

`SKILL.md` is the entry point — frontmatter + a cheat sheet covering numeric types, vars/ptrs/fns, control flow, anonymous struct literals, comptime, imports, the `layout` block, DSDs, DSD ops, and tasks, plus common patterns and gotchas. Cheat-sheet syntax is verified against the bundled `gemv-01/02/05` tutorials.

The 14 specialized files:

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
| [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) | Three integration models: classic memcpy (bulk + RPC), streaming memcpy (data through fabric colors), and `SdkLayout` (Python-driven topology with explicit ports). Full `SdkRuntime` API reference: `memcpy_h2d` / `memcpy_d2h` with every argument, broadcast variants, `launch` for RPC, `send` / `receive` for streams, `nonblock` + task handles, debug helpers. The `<memcpy/get_params>` / `<memcpy/memcpy>` PE-side library, the `unblock_cmd_stream` discipline. |
| [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) | Survey of every bundled `<...>` library: `complex`, `control`, `data_utils`, `debug`, `directions`, `dsd_ops`, `empty`, `layout`, `malloc`, `math`, `random`, `simprint`, `string`, `tile_config` (with its color/exception/filter/queue-status/priority/switch/teardown submodules), `time`, `timer`, `types`, `kernels/fft`, `kernels/tally`, `collectives_2d`, plus the WSE-3-only `message_passing`. |
| [SKILL-BUILTINS.md](SKILL-BUILTINS.md) | Catalogue of every `@`-prefixed builtin, organised by category — type/comptime, comptime utilities, strings, array introspection, struct introspection, DSD construction/mutation, integer/bitwise DSD ops, the full f16/f32 floating-point DSD-op families, tasks & events, task ID constructors, colors & queues, configuration & layout, random, ranges, higher-order (`@map`), symbol exports / RPC, plus the WSE-3-only set. |
| [SKILL-SIMD.md](SKILL-SIMD.md) | Automatic memory SIMD (8-bank 6-KiB-each layout, per-cycle 2-read+1-write capacity, the `bank_1 % 4 != bank_2 % 4` parallel-read rule, alignment recommendations, stride-impact on width, per-arch ceilings); explicit fabric SIMD via `.simd_mode` on `fabout_dsd`; WSE-2-only SIMD on FIFOs. |

## How Claude Code uses these skills

Each `SKILL-*.md` carries YAML frontmatter (a `name` and `description`). When you ask Claude Code about a topic that overlaps with one of these descriptions, the matching skill is loaded as context — so a question like *"why doesn't `@import_module('../shared/foo.csl')` work?"* surfaces the `csl-toolchain` and `csl-modules` skills, which together explain that `CSL_IMPORT_PATH` needs to bind the parent directory into the Apptainer container.

You don't have to invoke skills explicitly. The descriptions are designed to be load-bearing for the trigger-match: domain terms (`DSD`, `fabin_dsd`, `microthread`, `memcpy_h2d`, `CSL_IMPORT_PATH`, `@bind_data_task`) appear in the frontmatter precisely so they catch.

## Source of truth

Authoritative reference for everything in here: <https://sdk.cerebras.net/csl/language_index>. When a skill file disagrees with the upstream docs, the upstream docs win — open an issue / PR. Skills are written against SDK **2.10.0** (build `sdk-202604101435`), targeting `--arch=wse3`.

Each skill includes inline upstream-docs links at the bottom for follow-up reading.

## Layout

```
.
├── README.md              # this file
├── SKILL.md               # router; cheat sheet; cross-references
├── SKILL-*.md             # 14 specialized deep-dives (see table above)
├── install.sh             # idempotent symlink into ~/.claude/skills/csl/
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
