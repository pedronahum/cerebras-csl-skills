---
name: csl-sdk-utils
description: Reference for `cerebras.sdk.sdk_utils` — the pure-Python helper module that ships alongside the pybind SDK runtime. Covers timestamp / cycle-counting helpers (`calculate_cycles`, `sub_ts`, `make_u48`, `float_to_hex`), memcpy data shaping (`memcpy_view`, `input_array_to_u32`, `cast_uint32`), host-callable RPC introspection (`get_api_info_dict`, `parse_host_callable_api`, `check_rpc_api`, `is_valid_primitive_type`), and compile-option parsing. Use when shaping numpy arrays for memcpy, decoding cycle counts from `<time>` buffers, or validating a `launch` against the compiled RPC schema. Pinned to SDK 2.10.0.
---

# `cerebras.sdk.sdk_utils` — Host-Side Helpers

Pure-Python helpers that complement the pybind runtime. Three families of utility:

1. **Timestamp / cycle counting** — decode the `uint16` words a `<time>`-stamped CSL kernel returns into elapsed cycles.
2. **Memcpy data shaping** — pack / view numpy arrays for the `MEMCPY_16BIT` and `MEMCPY_32BIT` paths.
3. **Host-callable RPC introspection** — parse the compiled RPC schema (`out_rpc.json`) and validate `launch` argument lists before they hit the device.

For the runtime methods that consume the outputs of these helpers, see [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md).

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

## Function index

| Group | Function | Purpose |
|---|---|---|
| Cycles | `calculate_cycles` | Convert a timestamp buffer to elapsed cycle count. |
| Cycles | `sub_ts` | Lower-level: cycle count from 6 processed uint16 words. |
| Cycles | `make_u48` | Pack 3 uint16 → uint48 (as int64). |
| Cycles | `float_to_hex` | float32 → hex string (used by `calculate_cycles`). |
| Memcpy | `memcpy_view` | View a uint32 numpy array as 8/16/32-bit elements. |
| Memcpy | `input_array_to_u32` | Pack a 16-bit tensor into uint32 wavelets. |
| Memcpy | `cast_uint32` | Cast any memcpy-compatible scalar/array to uint32. |
| RPC | `get_api_info_dict` | Parse compile dir → RPC API dict. |
| RPC | `get_api_info_dict_from_json` | Same but from `out_rpc.json` path. |
| RPC | `parse_host_callable_api` | Parse the raw RPC symbol list to a name → (vars, types) dict. |
| RPC | `check_rpc_api` | Validate an arg list against the API dict before `launch`. |
| RPC | `is_valid_primitive_type` | Predicate for the type strings the RPC layer accepts. |
| Compile | `getOutputNameFromCompileOptions` | Parse the `-o` arg out of a `cslc` command line. |

`Dict`, `List`, `Optional` are also re-exported from `typing` at module scope — they're not utilities, just convenience imports.

Naming note: every helper is `snake_case` *except* `getOutputNameFromCompileOptions`, which is `camelCase`. Don't typo it.

## Cycle counting

CSL kernels record timestamps via the `<time>` stdlib (`@get_timestamp(buf)`). What you get back via memcpy is a sequence of `uint16` words encoding 48-bit cycle counts in a specific way. These helpers turn that back into a human-readable elapsed-cycles number.

### `calculate_cycles(timestamp_buf)` → `numpy.int64`

```
calculate_cycles(timestamp_buf: numpy.ndarray) -> numpy.int64
```

Top-level helper. Pass the entire `uint32` (or `uint16`-as-`uint32`-words) buffer that your kernel produced; get back the elapsed cycle count as a single `int64`. Internally calls `sub_ts` after splitting the buffer into the two endpoints (start + end timestamps).

```python
ts_buf = np.zeros(6, dtype=np.uint32)
rt.memcpy_d2h(ts_buf, rt.get_id("timestamps"), 0, 0, 1, 1, 6,
              streaming=False, order=MemcpyOrder.ROW_MAJOR,
              data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False)
elapsed = calculate_cycles(ts_buf)
print(f"{int(elapsed)} cycles")
```

### `sub_ts(words)` → `numpy.int64`

```
sub_ts(words: numpy.ndarray) -> numpy.int64
```

Lower-level. `words` is a numpy array of *six* `uint16` values (three for the start timestamp, three for the end). Returns end - start as `int64`. Most user code prefers `calculate_cycles`.

### `make_u48(words)` → `numpy.int64`

```
make_u48(words: numpy.ndarray) -> numpy.int64
```

Pack 3 `uint16` values into a single 48-bit value (returned as `int64`). One half of what `sub_ts` does internally. Useful when you want the raw timestamp, not the delta.

### `float_to_hex(f)` → `str`

```
float_to_hex(f: numpy.float32) -> str
```

Hex string for a `float32` value. Used by `calculate_cycles` when reinterpreting the float-typed bytes the timestamp infrastructure may produce. Generally an internal helper; useful occasionally when debugging a single timestamp word.

## Memcpy data shaping

The memcpy infrastructure transports 32-bit words. When your kernel works in 16-bit (`f16` / `i16` / `u16`), the host has to pack two 16-bit values into each 32-bit wavelet — or extract them after the fact. These helpers do that without you reaching for bit-shifts in numpy.

### `input_array_to_u32(np_arr, sentinel, fast_dim_sz)` → `numpy.ndarray`

```
input_array_to_u32(
    np_arr: numpy.ndarray,
    sentinel: Optional[int],
    fast_dim_sz: int,
) -> numpy.ndarray
```

Pack a 16-bit tensor into a `uint32` array suitable for `MEMCPY_32BIT` transport. Two modes via `sentinel`:

| `sentinel` value | Behavior |
|---|---|
| `None` | Zero-extend each 16-bit value into the low 16 bits of a `uint32`. Upper 16 bits are `0`. |
| an `int` | Upper 16 bits carry the **index** of the array element (0, 1, 2, …) up to `fast_dim_sz`, then reset. Useful when the kernel needs to know which input wavelet it just received. |

`fast_dim_sz` is the size of the innermost dimension you're sweeping over; the indexed mode wraps every `fast_dim_sz` elements.

### `memcpy_view(arr, dtype)` → `numpy.ndarray` view

```
memcpy_view(arr: numpy.ndarray, dtype: numpy.dtype) -> numpy.ndarray
```

Returns a view of a `uint32` numpy array reinterpreted as the given `dtype`. The output `dtype.itemsize` must be 1, 2, or 4 bytes. For sub-32-bit dtypes, only the low bits of each 32-bit word are exposed.

Typical use — read a 16-bit kernel output that came back through `MEMCPY_32BIT`:

```python
raw = np.zeros(N, dtype=np.uint32)
rt.memcpy_d2h(raw, rt.get_id("out16"), 0, 0, 1, 1, N,
              streaming=False, order=MemcpyOrder.ROW_MAJOR,
              data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False)
out_f16 = memcpy_view(raw, np.float16)   # view, not a copy
```

### `cast_uint32(x)` → `numpy.uint32` / `numpy.ndarray[uint32]`

```
cast_uint32(x) -> numpy.uint32 | numpy.ndarray[uint32]
```

Cast a memcpy-compatible scalar or array to `uint32`. Convenience for scalar RPC arguments that the kernel expects as `u32` — wraps `np.uint32(x)` for scalars and `arr.astype(np.uint32)` for arrays, with a couple of guard rails for invalid types.

## Host-callable RPC introspection

Every compile produces `out_rpc.json` (next to `out.json`) — a schema describing every `@export_name`'d host-callable function. These helpers parse it so your host script can validate `launch` calls programmatically.

### `get_api_info_dict(app_path)` → `Dict`

```
get_api_info_dict(app_path: str) -> Dict
```

Parse the compiled output directory at `app_path` (the same string you'd pass to `SdkRuntime`) and return a dict mapping function-name → `(var_list, type_list)`.

Example return structure:

```python
{
  "GEMV": (["alpha", "beta", "M", "N"], ["f32", "f32", "i16", "i16"]),
  "NRM":  (["M"], ["i16"]),
}
```

### `get_api_info_dict_from_json(json_path)` → `Dict`

```
get_api_info_dict_from_json(json_path: str) -> Dict
```

Same as above but reads `out_rpc.json` directly. Use when you've moved the rpc-json file or want to validate before constructing an `SdkRuntime`.

### `parse_host_callable_api(rpc_symbols)` → `Dict`

```
parse_host_callable_api(rpc_symbols) -> Dict
```

Lower-level: takes the raw list of RPC-symbol entries (the JSON's `symbols` field) and produces the same `name → (vars, types)` mapping. Most user code uses `get_api_info_dict` instead.

A snippet of the JSON shape this consumes (from the docstring):

```json
{
  "id": 7,
  "inputs": [
    {"name": "x",     "type": "f32"},
    {"name": "alpha", "type": "u16"},
    {"name": "beta",  "type": "i32"}
  ],
  "kind": "Func",
  "name": "foo",
  "sym_name": "foo",
  "type": "void"
}
```

### `check_rpc_api(name, arg_list, api_info_dict)` → `bool`

```
check_rpc_api(name: str, arg_list: List, api_info_dict: Dict) -> bool
```

Pre-flight check before `launch`. Returns `True` iff the function `name` exists in `api_info_dict` and the types of values in `arg_list` line up with the kernel's declared signature.

```python
api = get_api_info_dict("out")
args = [1.5, 2.5, 64, 64]   # alpha, beta, M, N
assert check_rpc_api("GEMV", args, api), "argument schema mismatch"
rt.launch("GEMV", *args, nonblock=False)
```

### `is_valid_primitive_type(para_type)` → `bool`

```
is_valid_primitive_type(para_type: str) -> bool
```

True iff `para_type` is one of the type strings the RPC layer understands (`"i8"`, `"u8"`, `"i16"`, `"u16"`, `"i32"`, `"u32"`, `"f16"`, `"f32"`, `"bool"`, …). Used internally by `check_rpc_api`; surface-level user code rarely needs it.

## Compile-option parsing

### `getOutputNameFromCompileOptions(option_list)` → `str`

```
getOutputNameFromCompileOptions(option_list: List[str]) -> str
```

Given the full `cslc` command line split into tokens, return the value passed to `-o` (the compile output directory name). Convenience for harnesses that build the command line dynamically and want to feed the same name to `SdkRuntime`.

```python
cmd = ["cslc", "--arch=wse3", "./layout.csl",
       "--fabric-dims=8,3", "--fabric-offsets=4,1",
       "-o", "out", "--memcpy", "--channels", "1"]
name = getOutputNameFromCompileOptions(cmd)
assert name == "out"
```

## Worked example — full timestamp round-trip

```python
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import (
    SdkRuntime, MemcpyDataType, MemcpyOrder,
)
from cerebras.sdk.sdk_utils import (
    calculate_cycles, get_api_info_dict, check_rpc_api,
)

rt  = SdkRuntime("out")
api = get_api_info_dict("out")

rt.load(); rt.run()

# Validate before launching
args = [1.5, 64, 64]
assert check_rpc_api("compute", args, api), "schema mismatch"
rt.launch("compute", *args, nonblock=False)

# Read the timestamp buffer the kernel wrote
ts = np.zeros(6, dtype=np.uint32)
rt.memcpy_d2h(ts, rt.get_id("timestamps"), 0, 0, 1, 1, 6,
              streaming=False, order=MemcpyOrder.ROW_MAJOR,
              data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False)

print(f"kernel ran in {int(calculate_cycles(ts))} cycles")

rt.stop()
```

## Gotchas

- **`input_array_to_u32` with `sentinel != None` indexes per `fast_dim_sz`.** If you pass a flat array but mean to index over an outer dimension, the indices wrap unexpectedly. Set `fast_dim_sz` to the actual inner-dim length you want indexed.
- **`memcpy_view` is a view, not a copy.** Writing to the returned array mutates the underlying `uint32` buffer. If you need an independent buffer, `.copy()` after viewing.
- **`check_rpc_api` doesn't catch all errors.** It validates type compatibility but cannot detect arity mismatches against C++-side RPC packing rules. A green `check_rpc_api` does not guarantee a successful `launch`.
- **`calculate_cycles` expects a specific buffer layout** — the size and shape that a `<time>` library call produces. Hand-rolled timestamp buffers can produce nonsensical values silently.
- **`getOutputNameFromCompileOptions` is camelCase.** All other helpers are snake_case; copy-pasting from `cslc` recipes is the easiest way to get the spelling right.

## See also

- [SKILL-SDKRUNTIME-API.md](SKILL-SDKRUNTIME-API.md) — `launch` / `memcpy_*` / `read_symbol` that consume the arrays / values these helpers prepare.
- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — overview; lifecycle, when to use what.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) — CSL-side `<time>`, `<timer>` libraries that produce the buffers `calculate_cycles` decodes.
- `_generated/sdkruntime-surface.json` — every signature in this file, machine-readable.
- Bundled `csl-extras-*/examples/tutorials/` — many tutorials use `calculate_cycles`; `gemv-09-streaming/run.py` is a good reference for the timestamp round-trip pattern.
