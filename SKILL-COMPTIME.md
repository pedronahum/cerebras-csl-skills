---
name: csl-comptime
description: CSL comptime semantics — how the compile-time evaluation model works and where it's used. Covers comptime-known values (literals, params, const with comptime init, composite expressions), comptime variables (comptime var, mutable at compile time, no runtime footprint), the comptime keyword as a force-evaluation marker on function calls, comptime-only types (comptime_int, comptime_float, type, comptime_string, function types, imported_module), comptime control-flow pruning (untaken branches skipped during semantic analysis), the top-level comptime { } block for bindings and exports, related builtins (@comptime_assert, @comptime_print, @is_comptime), and the restrictions (no runtime addr-of, no runtime control flow, no calling non-comptime functions without explicit marking).
---

# Comptime: Compile-Time Computation

CSL inherits Zig's idea that a meaningful fraction of a program's logic can run at **compile time**, with the result baked into the binary at zero runtime cost. CSL leans on this hard — every DSD construction, module instantiation, task binding, fabric layout decision, and type computation is comptime. If you don't understand comptime, half the surface of CSL looks magical.

The hardware reasons: a PE has 48 KiB of memory and is intolerant of dynamic dispatch. Comptime turns metaprogramming into static specialization — the compiler does the work, the kernel runs the result.

## Three places `comptime` appears

| Form | Where | Effect |
|---|---|---|
| `comptime var x: T = ...;` | Declaration | Variable lives only at compile time. Mutable. No runtime storage. |
| `comptime fn_call(args)` | Expression | Forces this call to execute at compile time. |
| `comptime { ... }` | Top-level block | Container for compile-time statements (bindings, exports, asserts). |

Plus the implicit form: a *comptime parameter* on a function (`fn f(comptime T: type, x: T) ...`) — see below.

## Comptime-known values

A value is *comptime-known* if the compiler can determine it without running the program. The rules:

| This is comptime-known | Why |
|---|---|
| A numeric or string literal | Built into the source. |
| A `param`-declared name | Caller supplied it at compile time. |
| A `comptime var` | By construction. |
| A `const` whose initializer is itself comptime-known | Inherits the property. |
| A composite expression (`+`, `*`, struct lit, etc.) whose operands are all comptime-known | Combines. |

Function calls are an explicit exception: the compiler won't speculatively evaluate `f(...)` to see if it's comptime — you must mark `comptime f(...)` explicitly.

Example tour:

```csl
param N: i16 = 16;                    // comptime-known: it's a param
const M: i16 = 4;                     // comptime-known: literal initializer
const TOTAL: i16 = M * N;             // comptime-known: composite of comptime values

comptime var counter: u16 = 0;        // comptime-mutable
counter += 1;                         // OK at top level — compile time

fn double(x: u16) u16 { return x * 2; }
const D: u16 = comptime double(N);    // force-eval; D is comptime-known
const E: u16 = double(N);             // would error if used where comptime is required —
                                      // the call isn't marked comptime, so E is runtime-known
```

## `comptime var` — compile-time-mutable variables

A `comptime var` is unusual: it's mutable, but only the compiler ever observes the mutations. It doesn't occupy any runtime memory; you cannot take its address; you cannot read or write it from a runtime context.

```csl
comptime var flags: u16 = 0xffff;
flags &= 0x0400;            // mutation happens at compile time
const final_flags = flags;  // baked in
```

Typical use: an accumulator in a comptime loop that builds a config struct or DSD spec.

## Global `const` is implicitly comptime-initialized

Top-level `const x: T = init;` requires `init` to be comptime-known. The variable's *value* is therefore comptime-known too. So:

```csl
const N: i16 = 8;                       // comptime
const SQUARED: i16 = N * N;             // comptime composite
const HALF: i16 = SQUARED / 2;          // still comptime
```

This is why most top-level decls "just work" inside `@get_dsd` field positions and similar comptime slots.

Local `const` follows the same rule when nested inside a comptime context (like a `comptime { }` block), but in a runtime function body a `const` with a runtime initializer is fine — it's just not comptime-known.

## Comptime parameters on functions

```csl
fn copy(size: i16, comptime base_type: type, src: *const base_type, dst: *base_type) void {
  // body specialized per base_type
}
```

The `comptime` prefix marks an argument that must be comptime-known *at the call site*. The function is specialized once per distinct value passed in:

```csl
copy(N, f32, &src_f32, &dst_f32);   // generates one specialization
copy(N, i16, &src_i16, &dst_i16);   // generates another
```

The most common use is `comptime T: type` for type-level generics. See [SKILL-GENERICS.md](SKILL-GENERICS.md) *(planned)*.

`anytype` is a related but distinct mechanism — it forces specialization based on the argument's *type*, without requiring the argument's *value* to be comptime-known. `comptime T: type` requires the value (a type itself) to be comptime-known.

## Forcing evaluation: `comptime expr`

Prefix any expression with `comptime` to demand compile-time evaluation:

```csl
const big_table: [N]f32 = comptime build_table(N);

const sqrt_2_const: f32 = comptime math.sqrt(2.0);    // not built into math?, no problem
```

Restrictions on what a comptime-evaluated function can do:

- It can't call non-comptime functions (unless those calls are themselves `comptime`-marked).
- It can't read non-comptime globals.
- It can't modify global runtime state.
- It can use any control flow on comptime values; the compiler unrolls loops.

If the body tries to do something runtime-only (an indirect call, a read from a fabric DSD, etc.), the compiler errors.

## Comptime-only types

Some types **only** exist at compile time:

| Type | Notes |
|---|---|
| `comptime_int` | Arbitrary-precision integer; used implicitly when you write `42` and don't bind to a sized type. |
| `comptime_float` | Arbitrary-precision float. |
| `type` | The type of *types*. A `param T: type;` is the standard generic-by-type pattern. |
| `comptime_string` | Compile-time string literal type. |
| Function types | A `fn(i32) i32` value cannot be stored runtime. |
| `imported_module` | The result of `@import_module(...)`. Modules are not first-class runtime values. |

You cannot:

- Declare a non-comptime variable of these types.
- Take pointers to them.
- Place them in arrays as runtime elements.

You *can* pass them as `param` or `comptime` arguments, and you *can* declare them as `comptime var` or top-level `const`.

```csl
// Top-level const of a comptime-only type — fine, the value is comptime-known
const T: type = f32;

// Comptime-only type as a parameter — fine
fn typed_zero(comptime T: type) T { return @as(T, 0); }

// Runtime variable of a comptime-only type — ERROR
var bad: type = f32;        // compile error: type is comptime-only
```

## Comptime control-flow pruning

If an `if`'s condition is comptime-known, the compiler picks the taken branch and **does not semantically check the other branch.** This is what lets a single function body handle multiple architectures or types:

```csl
const sum: f32 =
  if (@is_arch("wse3"))
    fast_wse3_path()         // checked
  else
    fallback_wse2_path();    // not checked if @is_arch returns true at compile time
```

The same applies to `comptime`-known loops in a `comptime { }` block or whose induction variable comes from a comptime range:

```csl
comptime {
  var i: u16 = 0;
  while (i < N) : (i += 1) {        // unrolled at compile time
    @export_symbol(arr_ptrs[i], "channel_" ++ @as_string(i));
  }
}
```

Because the compiler erases the untaken branch, it's the standard trick for arch-specific code paths whose syntax wouldn't even parse on the other arch (e.g., WSE-3-only DSDs).

## Top-level `comptime { }` block

```csl
comptime {
  @bind_data_task(main_task, main_task_id);
  @export_symbol(y_ptr, "y");
  @activate(start_task_id);
  @comptime_assert(N > 0);
  if (@is_arch("wse3")) {
    @initialize_queue(rx_iq, .{ .color = rx_color });
  }
}
```

Statements inside execute *during compilation*. The block isn't a function — it has no parameters, no return value, no scope variables that persist to runtime. Multiple top-level `comptime { }` blocks are allowed and concatenate in source order.

What you put in a comptime block:

- All `@bind_*_task` calls.
- All `@export_symbol` calls.
- `@activate` for startup tasks.
- `@initialize_queue` (WSE-3).
- Comptime assertions and prints for debugging the compile.
- Arch-conditional setup wrapped in `if (@is_arch(...)) { ... }`.

## Comptime support builtins

```csl
@comptime_assert(cond)                   // compile error if cond is false
@comptime_assert(cond, "error message")  // optional message

@comptime_print(value)                   // print value during compilation
@comptime_print(value, "label")          // optional label

@is_comptime(expr)                       // returns true iff expr is comptime-known
@is_comptime(@type_of(x))                // works on types too
```

`@comptime_assert` is the right way to enforce invariants on `param` values:

```csl
param N: i16;
comptime @comptime_assert(N > 0 and N % 2 == 0, "N must be a positive even integer");
```

`@comptime_print` is invaluable for debugging compile-time logic; it prints to the compile log, not the kernel runtime.

`@is_comptime` lets you branch on whether something is statically known — usually a sign that the API is over-clever, but occasionally what you want.

## Comptime in @import_module parameters

Every `@import_module` parameter is comptime. The struct literal you pass is itself comptime:

```csl
const stencil = @import_module("../../benchmark-libs/stencil_3d_7pts/layout.csl", .{
  .M = M, .N = N, .DTYPE = f32,    // all comptime-known
});
```

This is why instantiating a module with two different parameter sets gives you two *distinct* module values — they're separately specialized at compile time.

## DSD `tensor_access` lambdas are comptime

```csl
const A_col = @get_dsd(mem1d_dsd, .{
  .tensor_access = |i|{M} -> A[i*N]   // the lambda body and bounds are evaluated at compile time
});
```

The induction variable bounds (`{M}`) and the index expression (`i*N`) must be comptime-known. Anything runtime-known has to go through `base_address`/`extent`/`stride` fields.

## Memory-and-cycle effects, in one paragraph

Top-level `const` and `param` initializers run during compilation and bake their results into the ELF. A `const identity_matrix: [N][N]f16 = comptime build(N);` materializes into a baked-in array — no runtime initialization cycles, but it does cost PE memory. `comptime var` and `comptime { }` blocks cost zero runtime cycles and zero runtime memory; they purely shape the binary.

## Gotchas

- **A function call is not implicitly comptime.** `const x = f(N);` where both `f` and `N` are comptime-friendly will still produce a runtime call unless you write `comptime f(N)`.
- **Calling a non-comptime function from a comptime context errors.** Mark the call site `comptime` or refactor the function.
- **Comptime variables cannot have their addresses taken.** `&comptime_var` is a compile error.
- **The unchecked-branch behaviour is friend and foe.** A typo in the untaken branch sleeps until you flip the arch flag.
- **`param T: type;` with no default isn't comptime-known until the caller passes it.** Internal uses are still comptime-valid because params are always comptime, but the type is only *concrete* per call site.
- **`@comptime_assert(0)` in a generic function can fire only after a specific call site instantiates it** — the error message will point at the call, not the assertion.
- **Comptime evaluation is hermetic** — no I/O, no global mutation, no access to compile-time files. Don't try to read configuration from `comptime` code.

## See also

- [SKILL.md](SKILL.md) — cheat sheet and toolchain entry.
- [SKILL-SYNTAX.md](SKILL-SYNTAX.md) — `param` / `const` / `var` declarations and where each lives.
- [SKILL-TYPES.md](SKILL-TYPES.md) *(planned)* — `comptime_int`, `comptime_float`, `type`, `comptime_string`, `imported_module`.
- [SKILL-GENERICS.md](SKILL-GENERICS.md) *(planned)* — `comptime T: type` and `anytype` parameters.
- [SKILL-MODULES.md](SKILL-MODULES.md) *(planned)* — `@import_module` parameter specialization.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `tensor_access` lambdas and other comptime-only DSD fields.
- [SKILL-TASKS.md](SKILL-TASKS.md) — `comptime { @bind_*_task(...) }`.
- Upstream docs: <https://sdk.cerebras.net/csl/language/comptime>
