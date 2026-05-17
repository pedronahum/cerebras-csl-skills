---
name: csl-storage
description: CSL storage classes — extern and export declarations, the linkname attribute for symbol-name overrides, the linksection attribute for ELF section placement, the ABI-compatible type restriction (only 16/32-bit integers, f16/f32, bool, color, DSDs except FIFOs, arrays/pointers of compatible types, extern/packed struct and union, enums with compatible backing), how extern declarations reference symbols defined by export declarations elsewhere, mixing extern and export with identical linknames, the prohibition on no-storage-class declarations sharing names with extern/export, the no-formally-defined-calling-convention status of extern fn, and the relationship to @export_name in the layout block (which is the higher-level mechanism for host-visible exports).
---

# Storage Classes

CSL provides two storage-class keywords — `extern` and `export` — for plumbing symbols across separately-compiled translation units. They're orthogonal to `@export_name`/`@export_symbol` (which is about *host*-visible symbols and operates through the layout block, see [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md)).

This is the smaller, more advanced storage mechanism. Reach for it when you need to share state or functions across multiple CSL object files that the linker will combine, or interface with externally-provided assembly. Most kernels don't need it.

## `extern` — declared here, defined elsewhere

```csl
extern var x: i16;
extern fn f() void;
```

Rules:

- **No initializer / no body.** Just a type signature.
- **Type must be export-compatible** (see *Type restrictions* below).
- **Cannot be called at compile time.** The compiler doesn't have the body.
- **A separate compilation unit must `export` a matching definition.** Names must agree.

## `export` — defined here, visible to others

```csl
export var x: i16 = 42;
export fn f() void { x += 1; }
```

Rules:

- **Variables may have an initializer; functions must have a body.**
- **Type must be export-compatible.**
- **No formally documented calling convention.** Treat exported functions as opaque from the caller side; don't rely on register layout being stable across compiler versions.

The symbol becomes accessible to other linked object files and to Python's `ELFLoader` class for post-execution inspection.

## `linkname` — override the symbol name

By default the linker symbol matches the CSL identifier. `linkname("name")` overrides this:

```csl
export var x: i16 linkname("foo") = 99;
// In source: `x`. In the object file / linker: `foo`.

extern var counter: i16 linkname("global_counter");
// In source: `counter`. In the object file: `global_counter`.
```

A common use: parametrising the link name from a module-level `param`:

```csl
param sym_name: comptime_string;
export var x: i16 linkname(sym_name);
```

This lets the same source file produce different symbols when imported with different `param` bindings — useful when a multi-tile kernel exports per-tile state.

## `linksection` — place the symbol in a named section

```csl
var fast_path: i16 linksection(".fast") = 0;
```

Used to control ELF placement for tooling that inspects sections (e.g., separating hot vs cold data). Rarely needed at user-code level.

## Type restrictions — what's "export-compatible"

The boundary between compilation units is the C-style ABI. Only types whose layouts are stable across builds can cross.

**Compatible:**

| Category | Examples |
|---|---|
| ABI-sized integers | `i16`, `i32`, `u16`, `u32` |
| Floats | `f32`, the active `@fp16()` format |
| Other primitives | `bool`, `color` |
| DSDs (except FIFOs) | `mem1d_dsd`, `fabin_dsd`, etc. |
| Arrays and pointers | of any compatible element type |
| Function pointers | `*const fn(...) ...` |
| Enums | with compatible backing types |
| Structured | `extern struct`, `extern union`, `packed struct`, `packed union` |

**Incompatible:**

- Non-ABI-sized integers (`u3`, `i64`, `u64` — note `i64`/`u64` are excluded from the ABI-sized list above).
- Comptime-only types: `comptime_int`, `comptime_float`, `type`, `comptime_string`, `imported_module`.
- Plain `struct` / `union` (not `extern` or `packed`).
- `direction`, `range`, raw function types (function *pointers* are fine).
- `void` outside function return position.
- `fifo_dsd`.

If you try to `export var x: u3;`, the compiler errors at the declaration.

## Mixing `extern` and `export` for the same symbol

Multiple `extern` declarations of the same `linkname`, plus at most *one* `export` declaration of that name, are allowed. All declarations must agree on kind (var vs fn) and type:

```csl
// In file A:
export var counter: i32 linkname("g_counter") = 0;

// In file B:
extern var counter: i32 linkname("g_counter");

// In file C:
extern var counter: i32 linkname("g_counter");
```

What's **not** allowed:

- A declaration *without* a storage class sharing the same linkname as an `extern` or `export` decl. The compiler will reject this — every reference to a cross-unit symbol needs a storage class.

## Relationship to `@export_name` / `@export_symbol`

These are different mechanisms:

| Mechanism | Visibility | Where used | Plumbed to |
|---|---|---|---|
| `extern` / `export` | Linker-level, between CSL compilation units. | In top-level CSL decl. | Host's `ELFLoader` for inspection, or other CSL files. |
| `@export_name` + `@export_symbol` | Host-visible, exposed through `SdkRuntime.get_id` and `runner.launch`. | In `layout { }` and `comptime { }`. | The Python `run.py` script. |

`@export_name`/`@export_symbol` is the right mechanism when you want the host to send data with `memcpy_h2d`/`memcpy_d2h` or invoke kernel functions via `runner.launch`. `extern`/`export` is for *inside-CSL* cross-unit sharing.

## When you'd actually use these

The everyday CSL kernel compiles as a single unit and needs neither `extern` nor `export`. Cases where they matter:

- **Custom assembly stubs.** You write an inline-assembly routine in one `.csl` file and declare it `extern` in others.
- **Per-tile state with link-name parameterisation.** Multiple tiles each `export var` with a `linkname` derived from their coordinates, so the host (or another tile, via reflection) can address them individually.
- **Tooling integration.** Post-mortem inspection via `ELFLoader` works against `export` symbols.
- **Multi-file kernels built outside the standard `layout { } @set_tile_code(...)` flow.** Most users don't hit this, but build systems that pre-compile per-tile object files do.

## Gotchas

- **`i64` / `u64` are *not* ABI-sized for export.** They work fine inside a single compilation unit; they cannot cross the `extern`/`export` boundary. Cast to `i32`/`u32` at the boundary if you need to.
- **Plain `struct` (without `extern` or `packed`) cannot be exported.** Add the `extern` modifier on the struct declaration to fix.
- **`fifo_dsd` cannot be exported.** Allocate the FIFO inside the unit that uses it.
- **`linkname` strings can collide across files.** Two `export` decls with the same linkname in different files cause a linker error. The compiler doesn't catch this; only the link phase does.
- **`extern` decls are not callable at comptime.** The body isn't visible. If you need comptime evaluation, the function must be defined locally.
- **`@export_name` / `@export_symbol` are about the *host* boundary**, not about `extern`/`export`. Don't confuse the two — they answer different questions.
- **No calling convention guarantee for `extern fn`.** Don't write inline assembly that calls an exported CSL function unless you're prepared to track ABI changes between compiler releases.
- **`linksection` is mostly for tooling.** It doesn't affect performance unless your build pipeline explicitly relocates sections.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-SYNTAX.md](SKILL-SYNTAX.md) — `extern` / `export` declaration syntax and `align`/`linksection` attributes.
- [SKILL-TYPES.md](SKILL-TYPES.md) — ABI-sized integer restriction and `extern struct` / `packed struct`.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — `@export_name` and `@export_symbol` (the host-boundary mechanism, distinct from these storage classes).
- [SKILL-MODULES.md](SKILL-MODULES.md) — `param`-driven `linkname` strings for per-import-instance unique symbols.
- Upstream docs: <https://sdk.cerebras.net/csl/language/storage-classes>
