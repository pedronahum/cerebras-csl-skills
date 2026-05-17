---
name: csl-generics
description: CSL generics — type-level programming via comptime. Covers explicit `comptime T: type` function parameters and the lighter-weight `anytype` form (with @type_of for related typing), monomorphization semantics (each instantiation compiles independently — invalid ops in dead branches don't error), constraining type parameters via @comptime_assert + type-introspection predicates from <types> (is_numeric, is_float, is_signed, etc.), specializing function logic with `if (comptime ...)` branches, computing new types from old (functions returning `type`, conditional types via if/else, deriving widths via @element_type/@rank), generic data structures (struct-returning functions), and how generics compose with module parameters (`param T: type` instantiated differently per @import_module call).
---

# Generics

CSL has no special "generics" syntax. It has something more powerful: `type` is a first-class comptime value. Functions can take types as arguments, functions can return types, types can branch on other types — all at compile time.

The two surface forms are `comptime T: type` parameters (explicit) and `anytype` parameters (inferred). Both result in *monomorphization* — the compiler emits a separately specialized copy of the function per distinct type combination. No runtime dispatch, no allocation, no boxing.

## `comptime T: type` — explicit type parameters

```csl
fn identity(comptime T: type, x: T) T {
  return x;
}

const a = identity(i16, 42);
const b = identity(f32, 3.14);
```

`comptime T: type` says: at every call site, `T` must be a comptime-known value of type `type`. The compiler then specializes the function body per concrete `T`. See [SKILL-COMPTIME.md](SKILL-COMPTIME.md#comptime-parameters-on-functions).

## `anytype` — inferred type parameters

For symmetric / "use the argument's type" patterns, `anytype` is shorter:

```csl
fn ignore_x(x: anytype, y: @type_of(x)) @type_of(x) {
  return y;
}

const r = ignore_x(@as(i32, 1), @as(i32, 99));
```

`anytype` specializes per *argument type*, not per argument *value*. You can ask what type was inferred with `@type_of(arg)` — that's how the second argument and return type lock to the first.

**`anytype` vs `comptime T: type`:**

| | `anytype` | `comptime T: type` |
|---|---|---|
| Value required to be comptime? | Argument value can be runtime. | Argument value (a type) must be comptime. |
| Specialization driver | Argument's type. | The type value passed in. |
| Best for | Position-symmetric APIs (`add(a, b)`). | Cases where the type isn't otherwise visible from arguments. |

Many functions use both: `comptime T: type` for the principal type, `anytype` for incidentals.

## Monomorphization — selective compilation

The compiler emits one body per type combination. Crucially, **only the code paths that the specific instantiation reaches are semantically checked.** This is what makes `if (comptime ...)` type-branching work:

```csl
fn negate(x: anytype) @type_of(x) {
  if (comptime is_signed_type(@type_of(x))) {
    return -x;             // checked only when T is signed
  } else {
    return @as(@type_of(x), 0) - x;   // checked only when T is unsigned
  }
}
```

Calling `negate(@as(i32, 5))` instantiates the signed branch; the unsigned branch is never semantically analysed for `i32`. Similarly, calling `negate(@as(u32, 5))` analyses only the unsigned branch — even though `-x` on a `u32` wouldn't compile if it weren't behind a comptime guard.

The same dead-code-not-checked rule applies to `@is_arch("...")`, `comptime expr`, and any other comptime-known `if`.

## Constraining type parameters

Without constraints, error messages bubble up from deep inside the function body. Add a `@comptime_assert` at the top to fail at the call site with a clear message:

```csl
const types = @import_module("<types>");

fn fp_abs(x: anytype) @type_of(x) {
  const T = @type_of(x);
  @comptime_assert(types.is_float(T), "fp_abs expects a float type");
  if (x < @as(T, 0)) return -x;
  return x;
}
```

The `<types>` library exposes the canonical predicates (see [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#types)): `is_unsigned_int`, `is_signed_int`, `is_float16`, `is_float`, `is_enabled_float`, `is_signed`, `is_numeric`, `is_dsd`, `is_dsr`. Use them in `@comptime_assert` checks at the top of generic bodies.

You can also hand-roll predicates with `T == f32 or T == f16` syntax, but the library predicates handle edge cases (e.g., the multiple FP16 formats) you may forget.

## Returning `type` — type-level functions

A function whose return type is `type` constructs a new type from its inputs:

```csl
fn Point(comptime T: type) type {
  return struct {
    x: T,
    y: T,
  };
}

const Pf = Point(f32);
const Pi = Point(i16);

const origin: Pf = .{ .x = 0.0, .y = 0.0 };
const tile: Pi = .{ .x = 3, .y = 7 };
```

This is how generic data structures are built — no template syntax, just functions of types.

## Conditional types

Combine `if`/`else` with `type` to choose between alternatives:

```csl
fn bits_type(comptime T: type) type {
  return if (T == f16)
    u16
  else if (T == f32)
    u32
  else {
    @comptime_assert(false, "bits_type expects f16 or f32");
    unreachable;
  };
}

const u: bits_type(f32) = @bitcast(u32, my_f32);
```

The `<math>` library uses exactly this pattern for `isNaN`/`isInf`/`isFinite`, which need to operate on the bit representation of any IEEE-flavoured float.

## Deriving types from values

Builtins let you extract types from values at comptime:

| Builtin | Returns |
|---|---|
| `@type_of(x)` | The type of `x`. |
| `@element_type(arr_T)` | The element type of an array type. |
| `@rank(arr_T)` | Dimensionality (1, 2, 3, 4...). |
| `@dimensions(arr_T)` | Tuple of per-dim sizes. |
| `@element_count(arr_T)` | Total element count. |

```csl
fn sum(arr: anytype) @element_type(@type_of(arr)) {
  const T = @type_of(arr);
  const E = @element_type(T);
  var acc: E = @as(E, 0);
  for (@range(u16, @element_count(T))) |i| {
    acc += arr[i];
  }
  return acc;
}
```

## Module-level generics

Module parameters can be types too (see [SKILL-MODULES.md](SKILL-MODULES.md#parameterization)):

```csl
// vec.csl
param T: type;
param N: i16;

fn zero() [N]T {
  return @zeros([N]T);
}
```

```csl
// caller.csl
const vec_f32 = @import_module("./vec.csl", .{ .T = f32, .N = 16 });
const vec_i16 = @import_module("./vec.csl", .{ .T = i16, .N = 8 });

const a = vec_f32.zero();   // [16]f32
const b = vec_i16.zero();   // [8]i16
```

Each `@import_module` with a different `(T, N)` pair instantiates a separately specialized module value.

## Patterns

### Type-polymorphic copy

```csl
fn copy(comptime T: type, size: u16, src: *const T, dst: *T) void {
  for (@range(u16, size)) |i| {
    dst[i] = src[i];
  }
}

copy(f32, N, &src_f32, &dst_f32);
copy(i16, M, &src_i16, &dst_i16);
```

### Specialized DSD op via `<dsd_ops>`

```csl
const ops = @import_module("<dsd_ops>");

fn axpy(comptime T: type, alpha: T, x_dsd: dsd, y_dsd: dsd) void {
  // y_dsd = alpha*x_dsd + y_dsd, regardless of T
  ops.fmac(T, y_dsd, x_dsd, alpha, .{});
}
```

The `<dsd_ops>` library is the canonical way to write element-type-generic DSD code without manually switching between `@fmacs` and `@fmach`.

### Generic struct + method (`struct` literal returned by a fn)

```csl
fn Stack(comptime T: type, comptime N: i16) type {
  return struct {
    data: [N]T,
    top: i16,
  };
}

const S32 = Stack(f32, 64);
var s: S32 = .{ .data = @zeros([64]f32), .top = 0 };
```

Methods don't auto-attach in CSL the way they do in some languages; you write a separate `fn push(s: *Stack(f32, 64), v: f32) void { ... }` per-instantiation, or generic over the instance type:

```csl
fn push(comptime T: type, comptime N: i16, s: *Stack(T, N), v: T) void {
  s.*.data[s.*.top] = v;
  s.*.top += 1;
}
```

The pattern works but gets verbose. For lots of operations, a *module*-as-class (parameterised module exposing `fn`s) is usually cleaner than a struct-returning function.

## Gotchas

- **`anytype` arguments must be plain values, not types.** To pass a type, use `comptime T: type`.
- **`comptime T: type` arguments must be comptime-known at the call site.** Passing a runtime variable is a compile error.
- **Monomorphization can blow up code size.** A function called with 10 different types compiles 10 copies. For huge bodies, factor the non-generic parts out.
- **Dead-branch checking is type-sensitive.** Code that's invalid for the *current* instantiation passes the compiler if it's behind `if (comptime ...)` — but if you ever instantiate with a type where the branch becomes live, you'll see errors. Test the generic with each intended type.
- **`@type_of(x)` returns the *declared* type, not the dynamic type.** CSL has no inheritance / runtime polymorphism — `@type_of` is purely a compile-time mirror.
- **Generic modules don't share state across instantiations.** Two `@import_module("./vec.csl", .{ .T = f32, .N = 16 })` calls give independent modules.
- **`unreachable` is the standard "this comptime branch can't fire" marker.** Use after `@comptime_assert(false, ...)` so the surrounding type makes sense to the compiler.
- **No method-call syntax on user structs.** `mystack.push(v)` doesn't work — call `push(&mystack, v)` (or wrap with a module).

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-COMPTIME.md](SKILL-COMPTIME.md) — the `comptime` parameter mechanism that underpins generics.
- [SKILL-TYPES.md](SKILL-TYPES.md) — the `type` Type, comptime-only types, and what makes types first-class.
- [SKILL-MODULES.md](SKILL-MODULES.md) — module-level type parameters.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#types) — `<types>` predicate library.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#dsd_ops) — `<dsd_ops>` generic DSD-op wrappers.
- [SKILL-BUILTINS.md](SKILL-BUILTINS.md#type--comptime) — `@type_of`, `@element_type`, `@rank`, `@dimensions`, `@element_count`, `@is_same_type`.
- Upstream docs: <https://sdk.cerebras.net/csl/language/generics>
