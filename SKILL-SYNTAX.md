---
name: csl-syntax
description: CSL surface syntax — declarations (const/var/param with align/linksection/storage attributes), pointer types (*T, *const T, [*]T, &/.*), function declarations (fn vs task, anytype/comptime params, inline/noinline/export/extern/linkname), control flow (for-loop iterator and @range forms, while-with-continuation, switch, labeled blocks/breaks, block expressions), operators and their CSL spellings (and/or/! for logical, .* for dereference, & for address-of, no truthiness coercion), comments, inline assembly. CSL is Zig-shaped — this file enumerates the CSL-specific differences and the syntactic patterns that show up in every real kernel.
---

# CSL Syntax

CSL is a hardware-specific extension of Zig: the surface syntax is virtually identical, with extra concepts (`task`, `layout`, `param`, the `@`-prefixed WSE builtins) and a handful of removed Zig features (errors, defer, async/await as a general mechanism — the WSE has its own async model via DSDs and tasks). If you know Zig you can read CSL; if you don't, the table at the bottom of this file maps every common pattern.

## Declarations

Three keywords introduce a named value:

```csl
const ten_i: i16 = 10;            // immutable; requires initializer
var   ten_f: f16 = 10.0;          // mutable; initializer optional
param ten_d: f32 = 10.0;          // compile-time parameter; default optional
```

- **`const`** — must be initialized, never reassigned. The initializer can be runtime-known *or* comptime-known; the variable inherits.
- **`var`** — mutable; if the initializer is omitted, the value is *zero-initialized* (numerics → 0, arrays → all-zero).
- **`param`** — a compile-time input. The caller (a `layout { }` block via `@set_tile_code`, or a `@import_module` invocation) supplies the value. Defaults allowed. Always `comptime` from the program's perspective.

### Attributes

```csl
const aligned_var: i16 align(32) = 10;
var   global_var:  i16 linksection(".mySection") = 10;

export var x: i16 = 12;            // visible to external linkers
extern var y: i16;                 // declared here, defined elsewhere
```

- **`align(N)`** — forces N-byte alignment.
- **`linksection(".name")`** — place in a named ELF section.
- **`export`** — make the symbol externally visible.
- **`extern`** — declare a symbol defined in another translation unit. No initializer.
- **`linkname("name")`** — override the linker name for this symbol (used in `extern`/`export` decls). See [SKILL-STORAGE.md](SKILL-STORAGE.md) *(planned)*.

### Type inference

```csl
const ten_b = ten_a;     // type inferred from initializer
```

Works wherever you'd otherwise write a `:type`. Doesn't work without an initializer.

## Numeric types

```
i8,  i16,  i32,  i64       // signed
u8,  u16,  u32,  u64       // unsigned
f16, f32                   // floating-point
bool                       // one bit, no integer coercion
```

`f16` arithmetic is restricted on some archs — when in doubt, do compute in `f32` and use `@fp16` to convert at boundaries. `bool` is **not** an integer; `if (1)` is a compile error.

## Arrays and pointers

```csl
var a: [10]f32;                    // fixed-size array
var m: [M*N]f32;                   // size can be a comptime expression

const p: *i16        = &x;         // single-item pointer
const c: *const i16  = &x;         // pointer to immutable
const arr_ptr: [*]f32 = &a;        // many-item pointer (unknown length)
```

Operators:

```csl
const addr = &x;          // address-of
const val  = addr.*;      // dereference (note: postfix .*  — not *addr)
const elem = arr_ptr[3];  // index a [*]T pointer
const elem = addr.*[1];   // index through *array pointer
```

`[*]T` is the type you'll see most often for host-visible arrays (`@export_name("y", [*]f32, false)`). It's a many-item pointer with no compile-time bound — the caller provides bounds.

## Functions vs tasks

```csl
fn add(a: i16, b: i16) i16 { return a + b; }       // ordinary callable
task rx(data: u32) void { result = data; }         // event-triggered; cannot be called
```

A `task` is bound by `@bind_*_task` to a hardware task ID and fired by the runtime — you cannot invoke it directly. See [SKILL-TASKS.md](SKILL-TASKS.md).

### Special function parameter kinds

```csl
fn pow(base: anytype, exp: @type_of(base)) @type_of(base) { ... }
fn copy(size: i16, comptime base_type: type, src: *const base_type, dst: *base_type) void { ... }
```

- **`anytype`** — generic over the actual argument's type.
- **`comptime T`** — the argument must be comptime-known; per-call specialization.
- See [SKILL-GENERICS.md](SKILL-GENERICS.md) *(planned)*.

### `inline` / `noinline`

```csl
inline fn small_helper(...) ... { ... }    // always inlined at call site
noinline fn cold_helper(...) ... { ... }
```

### Export and extern

```csl
export fn f(x: i16, y: i16) i16 { return x + y; }
extern fn g(a: f16, b: f16) f16;           // body lives elsewhere
```

## Control flow

### `if` — statement *and* expression

```csl
if (cond) { ... } else { ... }                          // statement
const x: i32 = if (cond) 0 else 1;                      // expression
```

`cond` must have type `bool`. No truthiness; `if (n)` for integer `n` is rejected.

### `for` — iterator-style

CSL's `for` is an iterator binding, not a counter loop. The thing in `(...)` is what you iterate; the thing in `|...|` is the binding(s):

```csl
for (my_array) |element| { ... }                        // walk an array
for (my_array) |element, index| { ... }                 // walk with index
for (@range(i32, 100)) |i| { ... }                      // 0..100
for (@range(i32, 0, 2, 100)) |i| { ... }                // start, step, end
```

The `@range` builtin produces an iterable of any integer type. Multi-arg forms:

```csl
@range(T, end)               // 0, 1, ..., end-1
@range(T, start, end)        // start, start+1, ..., end-1
@range(T, start, step, end)  // start, start+step, ..., < end
```

### `while` — with optional continuation

```csl
while (cond) { ... }                          // plain
while (cond) : (i += 1) { ... }               // continuation after each body
```

The continuation runs *after* the body and *before* the next condition check — useful when `continue` is involved (without a continuation, manual `i += 1` before `continue` is needed).

### Labels and labeled `break`/`continue`

```csl
outer: for (rows) |r| {
  for (cols) |c| {
    if (done(r, c)) break :outer;
    if (skip(c))   continue :outer;
  }
}
```

### Block expressions

A `{ ... }` block can be used as an expression with a labeled `break :label value`:

```csl
const result = blk: {
  y += 1;
  break :blk y * 2;
};
```

### `switch`

```csl
switch (input) {
  0, 1, 2 => small_branch(),
  3       => mid_branch(),
  else    => fallback(),
}
```

Cases are comma-separated values, `=>` separates from the branch, branches can be expressions or blocks. `else` is required if cases aren't exhaustive over the type.

### `return`, `break`, `continue`

Standard semantics. `return val;` from any function; `break;` / `break :label;` / `break :label value;`; `continue;` / `continue :label;`.

## Operators

| Category | Operators |
|---|---|
| Arithmetic | `+`, `-`, `*`, `/`, `%` |
| Bitwise | `&`, `|`, `^`, `~`, `<<`, `>>` |
| Comparison | `==`, `!=`, `<`, `>`, `<=`, `>=` |
| Logical | `and`, `or`, `!` |
| Address-of | `&` (prefix) |
| Dereference | `.*` (postfix) |
| Field access | `.field` |
| Index | `[idx]` |

Notes:

- Logical ops are **`and`/`or`/`!`** — not `&&`/`||`/`~`. (`!` is also logical-not; `~` is bitwise-not.)
- Bitwise `|` looks like Zig's pipe-as-payload (`|x|`). Context disambiguates.
- Order of evaluation of operands is **undefined** except for `and` and `or`, which short-circuit.
- No truthiness — `if (x)` requires `x: bool`.

## Anonymous struct literals

The single most common construct in real CSL — used for every `@get_dsd`, `@import_module` params, `@set_tile_code` params, async-op options, and so on:

```csl
.{ .field1 = value1, .field2 = value2 }
```

The leading `.` is required. Fields are named. The expected struct type is inferred from context (the parameter type, the LHS, etc.). They are **always** comptime-evaluated.

## Comptime block

A top-level `comptime { ... }` block runs at compile time and is where all `@bind_*_task`, `@export_symbol`, `@activate`, `@initialize_queue` calls live. It is **not** a function — it's a declaration that the contained statements happen during compilation:

```csl
comptime {
  @bind_local_task(main_task, main_task_id);
  @export_symbol(y_ptr, "y");
  @activate(main_task_id);
}
```

You can have multiple `comptime { }` blocks at the top level; they're concatenated. See [SKILL-COMPTIME.md](SKILL-COMPTIME.md) *(planned)*.

## The `layout` block

Exclusive to the entry-point `.csl` file passed to `cslc`. Declares the PE grid and binds code to each tile:

```csl
const memcpy = @import_module("<memcpy/get_params>", .{ .width = 4, .height = 1 });

layout {
  @set_rectangle(4, 1);
  for (@range(i16, 4)) |x| {
    @set_tile_code(x, 0, "pe_program.csl", .{ .memcpy_params = memcpy.get_params(x) });
  }
  @export_name("y", [*]f32, false);
  @export_name("compute", fn()void);
}
```

A non-layout PE program file (`pe_program.csl`) has no `layout { }` block — it's pure declarations + functions + tasks + comptime.

## Comments

```csl
// single-line comment
/// doc comment (currently informational; doc-gen support is planned)
//! file-level doc comment (must appear before any other code)
```

There is no `/* ... */` multi-line form. Doc comments do not affect compilation.

## Inline assembly

For inline assembly (rarely needed, but it's there):

```csl
asm volatile (
  "instruction template",
  : output_constraints
  : input_constraints
  : clobbers
);
```

Global assembly in a `comptime` block is also supported. Usage is niche — most users never touch this.

## Source file structure

A CSL file looks like:

```csl
// 1. Top-level doc comment (optional)
//! file purpose

// 2. param declarations — the file's compile-time interface
param memcpy_params;
param M: i16;
param N: i16 = 32;     // with default

// 3. const imports + library handles
const sys_mod = @import_module("<memcpy/memcpy>", memcpy_params);
const layout_mod = @import_module("<layout>");

// 4. const / var top-level declarations
var A: [M*N]f32;
const A_ptr: [*]f32 = &A;

// 5. fn / task definitions
fn compute() void { ... }
task on_data(d: f32) void { ... }

// 6. comptime { } block(s) for bindings and exports
comptime {
  @bind_data_task(on_data, ...);
  @export_symbol(A_ptr, "A");
  @export_symbol(compute);
}
```

Order matters only as far as forward references go: every identifier must be in scope at its use site. Within a top-level block, declarations can refer to each other in any order, but bringing `comptime` blocks before the entities they reference is bad style.

## Naming conventions (community-standard)

- `snake_case` for variables, functions, tasks.
- `SCREAMING_SNAKE_CASE` for constants meant to be public/configurable.
- Types are usually lowercase keywords (`f32`, `data_task_id`) — there's no PascalCase convention for user types.
- DSDs typically end in `_dsd` (`A_dsd`, `recv_in_dsd`).
- Task IDs typically end in `_task_id` or `_id`.

## Things that look like Zig but aren't (or aren't yet) in CSL

- **No `defer`** — there's no useful concept of scope-exit cleanup on a PE.
- **No error union types (`!T`)** — kernels don't propagate errors at runtime in the Zig sense. Use sentinel values or control wavelets.
- **No general `async`/`await`** — concurrency is via tasks and async DSD ops, not Zig's coroutine model.
- **No `try` keyword** for the same reason.
- **No `comptime` standalone expression** — `comptime` is a parameter qualifier and a top-level block, not an inline marker.

## Things in CSL not in Zig

- **`task`** keyword and event-triggered execution model.
- **`layout { }`** block for fabric topology.
- **`param`** as a declaration kind for compile-time inputs.
- **DSD types** (`mem1d_dsd`, `fabin_dsd`, ...) and the rich `@get_dsd(...)` constructor syntax with `tensor_access` lambdas.
- **Color/queue types** (`color`, `input_queue`, `output_queue`) and the binding builtins.
- **`@is_arch("wse2"|"wse3")`** comptime arch check.

## Gotchas

- **Forgetting the leading `.` in struct literals** — `{ .x = 1 }` is a block, not a struct literal. Compile error if used in expression position; subtle if used where a block would have worked too.
- **Missing initializer on `const`** — `const x: i16;` is a compile error. Use `var` if you intend to assign later.
- **Index variable in `for (array) |elem, index|` is `usize`-shaped**, not the array's index type. Compare with `@as(i16, index)` if needed.
- **`while (cond) : (continuation)` runs the continuation even on `continue`** — that's the whole point — but forgetting this leads to skipped updates.
- **No truthiness:** `if (count)` and `while (count)` both fail. Use `if (count > 0)`.
- **`.*` is postfix dereference**, not prefix. `*ptr` is a *type* (pointer-to type), not a deref.
- **`and`/`or` are spelled out**, not `&&`/`||`. `&&` is a syntax error.
- **`anytype` parameters can't be called recursively without specialization** — see [SKILL-GENERICS.md](SKILL-GENERICS.md) *(planned)*.
- **`param` defaults are evaluated in the *callee's* context**, not the caller's — so `param N: i16 = M;` works if `M` is declared in the same file but not if it lives in the caller.
- **`extern` declarations cannot have an initializer**, even a `0`.
- **Labels (`outer:`) must be declared before the loop/block** they label.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry.
- [SKILL-TYPES.md](SKILL-TYPES.md) *(planned)* — the full numeric/struct/union/enum/array/pointer type system.
- [SKILL-COMPTIME.md](SKILL-COMPTIME.md) *(planned)* — comptime semantics in depth.
- [SKILL-GENERICS.md](SKILL-GENERICS.md) *(planned)* — `anytype`, `comptime` params, type-level computation.
- [SKILL-STORAGE.md](SKILL-STORAGE.md) *(planned)* — `extern`/`export`/`linkname`/`linksection` interactions.
- [SKILL-TASKS.md](SKILL-TASKS.md) — `task` keyword, binding, activation.
- [SKILL-DSDS.md](SKILL-DSDS.md) — the dominant use of anonymous struct literals.
- Upstream syntax docs: <https://sdk.cerebras.net/csl/language/syntax>
