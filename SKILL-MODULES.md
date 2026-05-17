---
name: csl-modules
description: CSL modules and @import_module — the only import mechanism. Covers the two filename forms (angle-bracket "<lib/name>" for the in-container stdlib, relative-path "./file.csl" / "../shared/x.csl" for user code), parameterization via the second-argument struct (param and color declarations bound from the caller), per-parameter-set instance specialization, dot-syntax member access, what module files contain (param, const, fn, task — no layout block), how module symbols are mangled (module_name.symbol_name), the imported_module comptime-only type, and the CSL_IMPORT_PATH bind-mount interaction for relative imports across directory boundaries.
---

# Modules and `@import_module`

CSL has exactly one import mechanism: `@import_module`. There are no `import`/`use` statements, no header files, no module declarations — just a builtin that, at compile time, reads another `.csl` file, evaluates its top-level declarations under your supplied parameters, and hands you back a comptime *module value* you can dot into.

This is how you reach the standard library, how you compose multi-file kernels, and how you share helpers between PEs.

## Syntax

```csl
@import_module(filename)
@import_module(filename, params_struct)
```

- `filename`: a comptime string. Either an angle-bracketed library name `"<...>"` or a relative path.
- `params_struct`: an anonymous struct literal binding any `param`s the imported file declares.

The result must be assigned to a top-level `const`:

```csl
const math_mod = @import_module("<math>");
const layout_mod = @import_module("<layout>");
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);
const stencil = @import_module("../../benchmark-libs/stencil_3d_7pts/layout.csl", .{
  .M = M, .N = N,
});
```

Imported values are *always* comptime — the result has type `imported_module`, which can't live in a runtime variable.

## Two filename forms

### Angle-bracket: `"<lib/name>"`

Resolves inside the SIF's bundled library directory. Cannot be overridden, cannot be reached from your filesystem.

```csl
const math = @import_module("<math>");
const debug = @import_module("<debug>");
const sys = @import_module("<memcpy/memcpy>", memcpy_params);
```

The bundled libraries (see [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) *(planned)*):

```
<complex>            <debug>          <directions>     <dsd_ops>
<empty>              <layout>         <malloc>         <math>
<random>             <simprint>       <string>         <tile_config>
<time>               <timer>          <types>          <kernels>
<collectives_2d>     <control>        <data_utils>
<message_passing>    (WSE-3 only)
<memcpy/get_params>  <memcpy/memcpy>  (memcpy infrastructure)
```

### Relative path: `"./file.csl"`, `"../shared/foo.csl"`

Resolves relative to the *importing* file's location. Standard `./` and `../` mechanics:

```csl
const helper = @import_module("./helper.csl");
const shared = @import_module("../shared/utils.csl", .{ .M = 8 });
```

**Crucial toolchain caveat:** the Apptainer wrappers only bind-mount `$PWD` into the container. Any relative path that escapes `$PWD` (`../foo`, `../../bar/...`) must have its parent in `CSL_IMPORT_PATH`. See [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md). Symptom of a missing bind: `error: Unable to open ...: no such file or directory`, even though the path resolves on the host.

## What a module file contains

A `.csl` file is a module — the same syntax that a top-level kernel file uses, *minus* the `layout { }` block (any `layout { }` in an imported file is ignored). Module files declare:

- `param`s — the file's compile-time interface, supplied by callers.
- `const` and `var` — top-level values (only `const` is reachable from the caller).
- `fn` — callable functions.
- `task` — events; tasks aren't usually accessed by name from importers since they're bound by id, but they participate in the same comptime evaluation.
- `comptime { }` blocks — side effects (asserts, exports).

A minimal module:

```csl
// math_helpers.csl
param scale: f32 = 1.0;

const PI: f32 = 3.14159;

fn scaled(x: f32) f32 {
  return x * scale;
}
```

Usage from a kernel:

```csl
const helpers = @import_module("./math_helpers.csl", .{ .scale = 2.0 });
const r = helpers.scaled(3.14);            // 6.28
const c = helpers.PI;                       // 3.14159
```

## Parameterization

Every `param` declaration in the imported file becomes a field the importer can bind. Defaults make a field optional:

```csl
// helper.csl
param N: i16;                    // required
param dtype: type = f32;         // optional with default
param color_x: color;            // params can have ANY comptime type
```

```csl
// caller.csl
const h1 = @import_module("./helper.csl", .{ .N = 4, .color_x = my_color });
const h2 = @import_module("./helper.csl", .{ .N = 8, .color_x = my_color, .dtype = f16 });
```

`h1` and `h2` are **distinct module values** — each parameter set produces a separately specialized module. They have the same shape (same fn signatures, same const names), but their internals are differently bound.

### Color params

Modules can declare `param name: color;`, letting the caller pass routable colors as part of the configuration. This is the standard pattern for fabric-aware library modules:

```csl
// module.csl
param tx: color;
param rx: color;
// ...
```

```csl
// caller.csl
const m = @import_module("./module.csl", .{ .tx = my_tx, .rx = my_rx });
```

### Unused / misnamed bindings warn

If you bind a field name that doesn't exist as a `param` in the target file, you'll get a compile warning. Missing required `param`s (no default) are a compile error.

## Member access

The module value supports comptime member access via `.`:

```csl
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);

sys_mod.unblock_cmd_stream();                  // call a member fn
const c = sys_mod.MEMCPYH2D_1;                 // read a member const
@get_color(@bitcast(u16, sys_mod.MEMCPYD2H_1));
```

You can access:

- Top-level `const`s.
- Top-level `fn`s.
- Top-level `param`s (each module value carries its own bound `param` values).

You cannot access:

- `var`s (runtime state inside the module is the module's own).
- `task`s by name (bound via `@bind_*_task`).
- Members of types-as-values returned by the module without further reflection.

## Mangled symbol names

In the produced ELF, a module's symbols are namespaced:

```
module_name.symbol_name
```

For example, `multiply_module.multiply` (from `const multiply_module = @import_module("multiply.csl", ...);`) appears in the binary as `multiply_module.multiply`. This is mostly invisible at the source level but matters when:

- Debugging with `csdb` and trying to set a breakpoint by name.
- Examining ELF dumps from `cs_readelf`.
- Choosing between two modules with the same import filename but different `const` names — they get distinct mangled prefixes.

## Identity and reimport

Importing the same file twice with the same params *probably* yields the same logical specialization, but you'll get two separate module values. Importing with different params definitely produces distinct specializations. Practical guideline: import each module exactly once per `(file, params)` tuple, at the top of your file, into a stable const name.

## Where modules fit in the source-file structure

```csl
// 1. params first
param memcpy_params;
param N: i16;

// 2. imports next — using params and constants you just declared is fine
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);
const helpers = @import_module("./helpers.csl", .{ .N = N });

// 3. top-level const / var / fn / task

// 4. comptime { } block
```

Imports must come *after* any `param`/`const` they reference. Forward references within imports do work in some cases (the compiler resolves a comptime DAG) but the readable convention is "params, then imports".

## Common module patterns

### Library facade

A user "library" module exposes a small set of `fn`s and `const`s parameterized by the caller's environment:

```csl
// my_collective.csl
param width: i16;
param my_color: color;

fn broadcast(value: f32) void { /* uses width, my_color */ }
```

Imported once per use site with the relevant `width`/`my_color`.

### Multi-tile shared helpers

In a multi-PE program, the PE program file imports the *same* helper module but with PE-coordinate-specific params:

```csl
// pe_program.csl
param x_coord: i16;
const utils = @import_module("./utils.csl", .{ .x_coord = x_coord });
```

Each PE gets a uniquely-specialized `utils`.

### Configuration module

A module whose only job is to compute a comptime config:

```csl
// config.csl
param raw_M: i16;
const M_padded: i16 = ((raw_M + 7) / 8) * 8;
const tile_count: i16 = M_padded / 8;
```

```csl
const cfg = @import_module("./config.csl", .{ .raw_M = M });
var buf: [cfg.M_padded]f32;
```

## Gotchas

- **Module values are comptime-only.** You can't pass an imported module as a runtime function argument.
- **Re-importing with the same params gives a fresh value, not a cached one.** Stick to one import per (file, params) tuple to avoid mangled-name surprises.
- **Layout blocks in imported files are ignored.** If you accidentally import a top-level layout file as if it were a module, the import succeeds but the layout does nothing. Use `@import_module("./layout.csl", ...)` only when you mean to consume the file's `param`/`const`/`fn` declarations.
- **Relative imports outside `$PWD` need `CSL_IMPORT_PATH`.** The path resolves to a host file just fine; Apptainer can't see it without the bind mount. See [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md).
- **No transitive `param` flow.** If `A` imports `B`, and `B` has `param N`, then `A` must supply `N` when importing `B`. There is no implicit "inherit from outer file".
- **`var`s in an imported module aren't visible from the importer**, even though the importer can call `fn`s that read/write them. Modules encapsulate their own state.
- **Naming a module-`const` the same as a builtin is fine** until you try to use it. `const f32 = ...;` in a module shadows the type inside *that* module, not in importers.
- **Stdlib imports (`<...>`) cannot be re-pointed.** Even with `CSL_IMPORT_PATH` set, angle-bracket names always resolve to the in-container library directory.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry.
- [SKILL-SYNTAX.md](SKILL-SYNTAX.md) — `param` declaration form and file structure.
- [SKILL-COMPTIME.md](SKILL-COMPTIME.md) — the `imported_module` type and comptime parameter flow.
- [SKILL-TYPES.md](SKILL-TYPES.md) — comptime-only types including `imported_module`.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) *(planned)* — what each bundled `<lib>` provides.
- [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) — `CSL_IMPORT_PATH` bind-mount rules for relative imports across directories.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — the `<memcpy/get_params>` / `<memcpy/memcpy>` parameterization pattern.
- Upstream docs: <https://sdk.cerebras.net/csl/language/modules>
