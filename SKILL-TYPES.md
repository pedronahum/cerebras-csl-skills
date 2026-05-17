---
name: csl-types
description: CSL type system — void; integers (arbitrary-width iN/uN, ABI-sized requirement of 16/32 bit for export/extern/task params); floats (f16/cb16/bf16 controlled by --fp16-format, f32); comptime_int and comptime_float; the type Type; function types; struct (anonymous .{...}, named, extern struct for C ABI, packed struct); union (untagged only, extern, packed); enum with backing type; multi-dim array [N, M]T syntax; pointers (*T single-item, [*]T many-item, *const T, [*]const T); anyopaque + @ptrcast; comptime_string with embedded NULs; imported_module; direction; full coercion rules (integer/float widening, comptime → fixed, pointer coercions, anonymous-to-named struct, peer-type resolution).
---

# CSL Type System

This is the structural type reference. For the syntax of *declaring* values of these types, see [SKILL-SYNTAX.md](SKILL-SYNTAX.md). For comptime-only behaviour, see [SKILL-COMPTIME.md](SKILL-COMPTIME.md).

## `void`

Absence of a value. The default return type for tasks and for functions that don't return anything. The single value of type `void` is `{}`:

```csl
fn finalize() void {}
const v: void = {};
```

Often shows up implicitly — `task` bodies always return `void`.

## Integers

### Fixed-width

`iN` and `uN` for any width from 0 to 16,777,215 bits:

```csl
var small: u3  = 7;        // 3-bit unsigned (0..7)
var word:  i16 = -100;
var dword: u32 = 1_000;
```

**ABI restriction:** only integer types with bit widths of **16 or 32** are ABI-sized. Anything else cannot appear in `export`/`extern` declarations or as a task parameter. So while `u3` is a valid local type, you can't `@export_name("x", *u3, ...)` or `task f(d: u24) void { ... }`. Use `u16`/`u32`/`i16`/`i32` at all boundaries.

The standard friendly types you'll see in kernels: `i16`, `u16`, `i32`, `u32`, with `i64`/`u64` showing up occasionally for counters and bit-twiddling.

### Comptime-only: `comptime_int`

Arbitrary-precision integer for compile-time math:

```csl
const ten = 10;                              // type comptime_int
const trillion = 1000 * 1000 * 1000 * 1000;  // no overflow at comptime
```

Integer literals default to `comptime_int` and coerce to a fixed type at the use site.

## Floats

### Three FP16 formats

| Type | Exponent | Mantissa | Notes |
|---|---|---|---|
| `f16` | 5 bits | 10 bits | IEEE half-precision. |
| `cb16` | 6 bits (custom) | 9 bits | Cerebras-custom 16-bit format. |
| `bf16` | 8 bits | 7 bits | Brain-float. Largest range. |

Only **one** FP16 format is active at compile time, selected via `cslc --fp16-format=...`. Whichever format you've chosen, you write `f16` in source — the same name binds to whichever format the flag picked.

### `f32`

IEEE single-precision. The workhorse type for most compute on a PE.

### Comptime-only: `comptime_float`

IEEE double-precision used during compilation only:

```csl
const pi: comptime_float = 3.14159;
const f: f32 = pi;                  // coerces to f32 at use
```

Float literals default to `comptime_float` and coerce.

## `type` — the type of types

`type` itself is a value:

```csl
const my_type: type = i16;
const arr = @zeros([10]my_type);     // [10]i16
fn typed_zero(comptime T: type) T { return @as(T, 0); }
```

Values of type `type` are always comptime; you can't store one in a runtime variable. The defining idiom of CSL generics is `comptime T: type` parameters.

## Function types

```csl
fn add(a: i16, b: i16) i16 { return a + b; }
const f: fn(i16, i16) i16 = add;     // function values are comptime-known
const sum = f(1, 2);
```

Function types are not first-class runtime objects — you can't put one in a runtime variable. You *can* use them as `param` declarations and `comptime` values, which is how higher-order code is plumbed.

## Struct types

### Anonymous struct literals (`.{ ... }`)

The CSL idiom for ad-hoc records:

```csl
var s1 = .{ .a = 10, .b = 1.0 };         // named-field form
var s2 = .{ 10.0, 1.0 };                  // tuple form
const elem = s2[0];                       // tuple indexing
```

Two anonymous struct types are equal iff they have identical fields and types. Anonymous structs coerce into named struct types when fields match (see *Coercions* below).

This is the form passed to `@get_dsd`, `@import_module`, `@set_tile_code`, async-op options — every comptime configuration in CSL.

### Named structs

```csl
const Point = struct {
  x: i16,
  y: i16,
};
var p = Point{ .x = 5, .y = 10 };
const elem = p.x;
```

**Identity rule:** two named struct types are the same iff they have identical fields **and** are defined at the same source location. Two struct definitions that look identical but appear in two files are distinct types.

### `extern struct` — C ABI layout

Forces the C ABI memory layout. Required for use in `export`/`extern` declarations because the host needs to know the layout:

```csl
const S = extern struct {
  x: i16,
  y: f32,
};
```

### `packed struct` — bit-packed

Bit-packed layout with an implicit backing integer:

```csl
const PS = packed struct {
  x: i16,    // 16 bits
  y: f32,    // 32 bits
};
// Total: 48-bit backing integer
```

All fields must be *bit-quantifiable*: fixed-width integers, floats, bools, enums, other packed structs/unions, or pointers.

## Union types

CSL supports **untagged unions only** — the program is responsible for tracking which variant is active. Reading an inactive variant is undefined at runtime; the compiler checks comptime accesses.

```csl
const Value = union {
  i: i16,
  f: f16,
};
var v = Value{ .i = 42 };
```

### `extern union` / `packed union`

Same C-ABI and bit-packed forms as for structs. `packed union` requires all variants to have the same bit width.

```csl
const PU = packed union {
  x: i16,
  y: i16,
};
```

## Enum types

```csl
const Color = enum(u16) {
  red,                  // 0 (auto)
  white = 1,
  blue,                 // 2 (auto, continues from previous)
};

const fav = Color.red;
const red_val: u16 = @as(u16, Color.red);    // 0
```

The backing type is declared explicitly (`enum(u16)`). Values can be auto-assigned or explicit; auto-assignment continues from the previous explicit value.

**Identity rule:** two enums are the same iff they have the same shape *and* the same definition site. Same idea as named structs.

## Array types

```csl
var a:    [10]u16 = undefined;
var grid: [10, 10]i32 = undefined;        // 2D — note COMMA separator
var inited = [3]i16{ 1, 2, 3 };

a[0]      = 1;
grid[2,3] = 99;
```

Two notes:

- Multi-dimensional arrays use **comma** between dimensions: `[10, 10]i32`, not `[10][10]i32`. Indexing uses `[i, j]`.
- Sizes can be any comptime expression: `[M*N]f32`, `[N+1]f32`.

## Pointer types

| Form | Meaning |
|---|---|
| `*T` | Single-item pointer; deref with `ptr.*`. |
| `[*]T` | Many-item pointer (unknown length); index with `ptr[i]`, no `.*`. |
| `*const T` | Pointer to immutable; cannot write through. |
| `[*]const T` | Many-item pointer to immutable. |

Single-item:

```csl
var x: i32 = 42;
const ptr: *i32 = &x;
ptr.* = 100;          // dereference + assign
```

Many-item:

```csl
var arr: [10]i32 = undefined;
const many: [*]i32 = &arr;     // *[10]i32 coerces to [*]i32
many[5] = 99;                  // no .* — index directly
```

**Configuration memory:** pointers into the PE configuration address range cannot be dereferenced or indexed normally — use `@get_config`/`@set_config` builtins. The compiler enforces this.

## `anyopaque`

Type-erased pointer target. Cannot be a non-pointer value:

```csl
var x: i32 = 42;
const op: *anyopaque = &x;             // type-erase
const back: *i32 = @ptrcast(*i32, op); // recover
```

Use for FFI-like situations and library helpers that accept "pointer to anything".

## `comptime_string`

Immutable comptime-only string. Stored without a NUL terminator; NUL bytes can appear *inside*:

```csl
const hello = "abc";                                    // type comptime_string
@comptime_assert(@strlen("abc\x00xyz") == 7);           // counts the inner NUL
```

Use `@strcat`, `@strlen`, etc. (see [SKILL-BUILTINS.md](SKILL-BUILTINS.md) *(planned)*). String literals never carry runtime cost — they are folded into the binary at the use site.

## `imported_module`

The type of the value returned by `@import_module(...)`. Comptime-only — you cannot store a module in a runtime variable. Module field access (`mod.fn(...)`, `mod.CONST`) is a comptime operation that resolves to the named entity in the imported file:

```csl
const sys_mod: imported_module = @import_module("<memcpy/memcpy>", memcpy_params);
sys_mod.unblock_cmd_stream();
```

(The explicit type annotation is unusual; you'll see `const sys_mod = @import_module(...);` without the annotation in real code.) See [SKILL-MODULES.md](SKILL-MODULES.md) *(planned)*.

## `direction`

Compass direction (NORTH, SOUTH, EAST, WEST) for fabric routing. Used heavily in route declarations and `<directions>` library. Comptime-only-ish; concrete uses come from the `<directions>` library. See [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)*.

## Coercions

CSL performs **widening** coercions automatically; **narrowing** requires an explicit `@as(T, ...)` or `@bitcast(T, ...)`.

### Integer widening

Same signedness, wider width is automatic:

```csl
var small: i8 = 42;
var big:   i32 = small;     // i8 → i32 OK
```

Unsigned widens to a strictly wider signed type:

```csl
var u: u16 = 1234;
var s: i32 = u;             // u16 → i32 OK
```

Width-narrowing is rejected; use `@as(u8, big)` (which traps/wraps based on type, see builtins).

### Float widening

```csl
var h: f16 = 3.14;
var f: f32 = h;             // f16 → f32 OK
```

### Comptime numeric → fixed

`comptime_int` and `comptime_float` coerce to *any* fixed type, provided the value fits:

```csl
const lit = 42;
var x: i32 = lit;            // OK
var y: i16 = 100_000;        // compile error — doesn't fit
```

### Pointer coercions

| From | To | Notes |
|---|---|---|
| `*T` | `*const T` | Add `const`. |
| `*[N]T` | `[*]T` | Decay array pointer to many-item pointer. |
| `*T` | `*[1]T` | Single → array-of-1. |
| `[*]T` | `[*]const T` | Add `const`. |

### Anonymous → named struct

```csl
const Point = struct { x: i32, y: i32 };
var p: Point = .{ .y = 20, .x = 10 };   // OK: fields reordered, types match
```

The order of fields in the literal need not match the struct's declaration order.

### Peer type resolution

When multiple branches need to unify (e.g., the arms of an `if` expression, the arms of a `switch`, both sides of a binary op), CSL finds a common type using the widening rules:

```csl
var x: i32 = 10;
const r = if (cond) x else 20;          // 20 (comptime_int) widens to i32
```

If no common widening exists, you'll get a compile error and need explicit casts.

## Explicit casts

For type changes that aren't automatic:

```csl
@as(T, value)                  // coerce — fails if narrowing or unsafe
@bitcast(T, value)             // reinterpret bits, same size
@ptrcast(T, ptr)               // cast pointer to a different pointee type
```

`@as` is the primary cast — use it whenever you'd hand-write a coercion. See [SKILL-BUILTINS.md](SKILL-BUILTINS.md) *(planned)*.

## Gotchas

- **Non-ABI-sized integers can't cross task or export boundaries.** A task with `task f(d: u24)` is a compile error; `@export_name("x", *u3, ...)` is rejected. Use `u16`/`u32`.
- **Multi-dim arrays use commas: `[N, M]T`, not `[N][M]T`.** Same for indexing: `arr[i, j]`.
- **Anonymous struct field ordering doesn't matter; named struct declaration ordering does** for tuple-form initializers.
- **Two structurally identical named structs declared in two files are not equal.** Pass struct *values* through interfaces, or share the struct declaration via an imported module.
- **Reading from the wrong variant of a union is UB.** No tag means the compiler can't tell you've crossed the line — only your own discipline can.
- **`f16` source-name binds to whichever format the `--fp16-format` flag selected.** The same source can mean different bits in different builds.
- **`*T` and `[*]T` differ at the language level**, not just by convention. A function expecting `[*]f32` won't take a `*f32` without explicit decay (`@as([*]f32, &x)` or pass `&arr` where `arr: [N]f32`).
- **Comptime strings keep embedded NULs.** `@strlen("a\x00b") == 3`, not 1.
- **`peer type resolution` only widens.** `if (cond) some_i16 else 0.5` won't unify; the literal `0.5` widens but `i16` doesn't widen to `f32`.
- **`@ptrcast` is `@ptrcast(*T, ptr)`** — the type goes first. Compiler errors here are extremely confusing if you swap them.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-SYNTAX.md](SKILL-SYNTAX.md) — variable declarations, pointer-deref syntax.
- [SKILL-COMPTIME.md](SKILL-COMPTIME.md) — comptime_int, comptime_float, type, imported_module.
- [SKILL-STORAGE.md](SKILL-STORAGE.md) *(planned)* — ABI-sized constraint with `extern`/`export`.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md) *(planned)* — `@as`, `@bitcast`, `@ptrcast`, `@type_of`, `@is_same_type`, string builtins.
- [SKILL-MODULES.md](SKILL-MODULES.md) *(planned)* — the `imported_module` type and parametric instantiation.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) *(planned)* — `direction` type usage.
- Upstream docs: <https://sdk.cerebras.net/csl/language/types>
