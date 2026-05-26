---
name: csl-sdkruntime-route
description: Reference for the low-level Cerebras WSE routing pipeline — `cerebras.sdk.runtime.routepybind.CslIoRouting` plus the Python wrappers (`CslWseNetlist`, `CslWsePinTable`, `CslWseRouter`, `CslWseRouterAssembler`) that build memcpy-infrastructure route ELFs. Use only when debugging memcpy bring-up, porting the routing prototype, or reading internal SDK scripts. End-user CSL/SdkLayout programs do not call this surface. Pinned to SDK 2.10.0.
---

# SDK Runtime: Low-Level Routing Internals

> **You probably don't need this file.** End-user CSL programs and SdkLayout programs never touch the surface documented here. The high-level fabric-routing types — `Color`, `Route`, `Edge`, `RoutingPosition` — live in `sdkruntimepybind` and are covered in [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md). This file documents the layer *underneath* — the memcpy infrastructure's routing prototype that the SDK uses internally to wire ingress/egress tiles to PE rectangles.
>
> Reach for this file only when (a) debugging a memcpy bring-up hang, (b) porting the routing prototype to a new fabric topology, or (c) reading internal SDK scripts that import `cslwserouter` / `cslwseroutea sm` / `cslwsenetlist` / `cslwsepintable`.

## SDK pinning

```
version              2.10.0
build                202604101435
git                  4586d3f0d8
sif_filename         sdk-cbcore-2.10.0-sdk-202604101435-4586d3f0d8.sif
sif_sha256           4700f1f4544e0e30b7751840394c517b18ceaf6f35847790ac0bf46f0bfa6b6a
```

The module docstring of `cerebras.sdk.runtime.cslwsenetlist` explicitly labels itself "a prototype library for memcpy." Treat all surface in this file as **prototype scope** — subject to change without notice across SDK versions. The pin above is the only build for which the specifics below are known good.

## Module map

| Module | Kind | Role |
|---|---|---|
| `cerebras.sdk.runtime.routepybind` | pybind11 (`.so`) | Low-level C++ routing primitive (`CslIoRouting`). |
| `cerebras.sdk.runtime.cslwsenetlist` | Python | Netlist construction — fabric dims + ingress/egress `Tile` lists. |
| `cerebras.sdk.runtime.cslwsepintable` | Python | LVDS pin-table assignment. |
| `cerebras.sdk.runtime.cslwserouter` | Python | Top-level `route()` orchestrator. |
| `cerebras.sdk.runtime.cslwserouteasm` | Python | Emits `MEMCPY_XY_ROUTES.elf` from a routed netlist. |

Plus two shared utility types pulled in from sibling packages:

| Type | Module | Constructor |
|---|---|---|
| `Tile` | `cerebras.sdk.streamer.lib.streamerpybind` | `Tile(x: int, y: int, color: int)` |
| `Coordinate` | `cerebras.das_common.das_commonpybind` | `Coordinate(x: int, y: int)` |
| `Dimensions` | `cerebras.das_common.das_commonpybind` | `Dimensions(width: int, height: int)` |

## The memcpy routing pipeline

```
  ┌───────────────────────────────────────────────────────┐
  │  CslWseNetlist(width, height, ingress, egress)        │
  │    fabric dims + lists of streamer Tiles              │
  └───────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌───────────────────────────────────────────────────────┐
  │  CslWsePinTable(netlist)                              │
  │    .create_pin_assignments()                          │
  │    .ingress_index_list / .egress_index_list           │
  │    .get_lvds_index_list()                             │
  └───────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌───────────────────────────────────────────────────────┐
  │  CslWseRouter(netlist).route()                        │
  │    "Route the ingress to PE and PE to egress."        │
  │    populates per-PE CslIoRouting entries internally   │
  └───────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌───────────────────────────────────────────────────────┐
  │  CslWseRouterAssembler(netlist)                       │
  │    .generate_route_elf()                              │
  │    emits MEMCPY_XY_ROUTES.elf                         │
  └───────────────────────────────────────────────────────┘
                            │
                            ▼
                    poke_data(filename, ...)
            (lowest-level binary writer used by the assembler)
```

The user-facing payoff is the `MEMCPY_XY_ROUTES.elf` file that `SdkRuntime.load()` consumes as part of memcpy bring-up. End-user code never invokes this pipeline directly — the runtime / `cslc` invokes it transparently when `--memcpy` is on.

## `cerebras.sdk.runtime.routepybind`

The pybind11 surface for the C++ routing primitive. One class:

### `CslIoRouting(src_point, dst_point, traffic_id, fabric_rect)`

```python
CslIoRouting(
    src: cerebras::Point<unsigned int>,
    dst: cerebras::Point<unsigned int>,
    traffic_id: int,
    fabric_rect: cerebras::AbstractRectangle<unsigned int>,
) -> CslIoRouting
```

**Constructor positional args:** source point, destination point, an integer traffic identifier, and the fabric extent. `Point` and `AbstractRectangle` are internal C++ types — they're not exposed as constructible Python classes; you obtain them by indirection (typically from a netlist).

**Members:**

```python
routing.has_x_route()         -> bool
routing.has_y_route()         -> bool
routing.has_receiver_route()  -> bool

routing.x_route()             -> tuple
routing.y_route()             -> tuple
routing.receiver_route()      -> tuple

routing.route_pe_to_egress  (egress_dir: CardinalDirection, flag: bool)                   -> int
routing.route_ingress_to_pe (ingress_dir: CardinalDirection, flag: bool)                  -> int
routing.route_directly_pe_to_pe(
    from_dir: CardinalDirection,
    to_dir:   CardinalDirection,
    flag:     bool,
    third:    Optional[CardinalDirection],
) -> int

routing.traffic_map_address() -> int
```

The three `route_*` methods are *setters* that record routing legs and return an integer (status code or installed-leg count — the docstring doesn't disambiguate). The six accessors return either a `tuple` of route coordinates or a boolean presence flag.

`traffic_map_address()` returns the address inside the traffic map where this routing's entry lives. Used by the assembler when emitting the ELF.

## `cerebras.sdk.runtime.cslwsenetlist`

Pure-Python netlist builder.

### `CslWseNetlist(width, height, ingress, egress, debug_level=0)`

```python
CslWseNetlist(
    width: int,
    height: int,
    ingress: List[Tile],
    egress:  List[Tile],
    debug_level: int = 0,
) -> CslWseNetlist
```

> "CslWseNetlist is library that stores LVDS tiles, user PE input and output PE tiles, and routes. This library is an prototype library for memcpy."

`ingress` and `egress` are lists of `streamerpybind.Tile`. Each `Tile(x, y, color)` records a streamer-tile location on the fabric boundary that traffic enters or leaves through.

**Members:**

```python
netlist.streamer_tile_index           -> int
netlist.add_streamer_tile_to_used(...)
netlist.is_streamer_tile_used(...)    -> bool
netlist.is_sufficient_streamer(...)   -> bool
```

`add_streamer_tile_to_used` and the predicates track which streamer tiles have been consumed by routing so far — the netlist maintains a usage map as routing progresses.

### Helper value types (re-exported)

```python
Tile(x: int, y: int, color: int)         # from streamerpybind
Tile.x   Tile.y   Tile.color             # accessors
Tile.set_color(c)   Tile.set_direction(d)
Tile.direction

Dimensions(width: int, height: int)      # from das_commonpybind
Dimensions.width   Dimensions.height
Dimensions.area    Dimensions.empty
```

## `cerebras.sdk.runtime.cslwsepintable`

```python
CslWsePinTable(netlist: CslWseNetlist, debug_level: int = 0) -> CslWsePinTable

table.create_pin_assignments()    -> None
table.ingress_index_list          -> List[int]
table.egress_index_list           -> List[int]
table.get_lvds_index_list()       -> List[int]
```

Builds LVDS pin assignments for the netlist. After construction call `create_pin_assignments()` once; the three index lists then carry the result. The assembler reads these out when emitting the ELF.

### `CardinalDirection` enum (lives here)

```python
CardinalDirection.NORTH          = 0
CardinalDirection.SOUTH          = 1
CardinalDirection.WEST           = 2
CardinalDirection.EAST           = 3
CardinalDirection.NUM_DIRECTIONS = 4
```

**Important — this is NOT the same enum as `sdkruntimepybind.Route`.** The two have different orderings:

| Direction | `cslwsepintable.CardinalDirection` | `sdkruntimepybind.Route` |
|---|---|---|
| NORTH | `0` | `3` |
| SOUTH | `1` | `4` |
| WEST  | `2` | `2` |
| EAST  | `3` | `1` |
| RAMP  | (absent)        | `0` |

`Route` has the additional `RAMP` member (the local-PE handle); `CardinalDirection` only describes fabric edges. Mixing them with integer casts produces wrong routing silently. **Reference by name; never by numeric value.**

## `cerebras.sdk.runtime.cslwserouter`

```python
CslWseRouter(netlist: CslWseNetlist, debug_level: int = 0) -> CslWseRouter
router.route() -> None
```

> "Route the ingress to PE and PE to egress."

One operation. After `route()` returns, the netlist's per-PE `CslIoRouting` entries are populated; the assembler can run.

### Bundled helpers

```python
CslRuntimeContext      # namespace alias — exposes CslIoRouting under it
PEPort.INPUT
PEPort.OUTPUT
Coordinate(x, y)       # from das_commonpybind, x/y attrs
```

`CslRuntimeContext.CslIoRouting` is a re-export of `routepybind.CslIoRouting`; the alias exists so callers can import everything from the `cslwserouter` module.

`PEPort` is a small enum distinguishing input vs output ports during pin assignment.

## `cerebras.sdk.runtime.cslwserouteasm`

```python
CslWseRouterAssembler(netlist: CslWseNetlist, debug_level: int = 0) -> CslWseRouterAssembler
asm.generate_route_elf() -> None
```

> "Generates MEMCPY_XY_ROUTES.elf from routes in netlist."

After `CslWseRouter.route()` has populated the netlist, call `generate_route_elf()` to materialize the ELF. The output filename is fixed (`MEMCPY_XY_ROUTES.elf`); pass the netlist with the right working directory if you need to control where it lands.

### `poke_data(filename, data_list, x, y, regions, masks, values)` → `None`

```python
poke_data(
    filename: str,
    data:     List[bytes],
    arg2:     int,
    arg3:     int,
    regions:  List[Tuple[Tuple[int, int], Tuple[int, int]]],
    masks:    List[int],
    values:   List[int],
) -> None
```

The low-level binary writer the assembler uses. Writes `data` chunks into the named ELF, at offsets / coordinates encoded by `regions` (each is a `((x0, y0), (x1, y1))` rectangle), with the per-region `masks` / `values` controlling which bits to update.

Most user code never calls this directly. Documented for completeness because internal scripts that hand-patch routing tables sometimes do.

## Pipeline sketch (no end-to-end example — internals)

The shape of an internal driver looks roughly like:

```python
from cerebras.sdk.runtime.cslwsenetlist  import CslWseNetlist
from cerebras.sdk.runtime.cslwsepintable import CslWsePinTable, CardinalDirection
from cerebras.sdk.runtime.cslwserouter   import CslWseRouter
from cerebras.sdk.runtime.cslwserouteasm import CslWseRouterAssembler
from cerebras.sdk.streamer.lib.streamerpybind import Tile

ingress = [Tile(x=0, y=4, color=0), ...]
egress  = [Tile(x=7, y=4, color=0), ...]

netlist = CslWseNetlist(width=8, height=8, ingress=ingress, egress=egress)

pintbl  = CslWsePinTable(netlist)
pintbl.create_pin_assignments()

CslWseRouter(netlist).route()
CslWseRouterAssembler(netlist).generate_route_elf()
# MEMCPY_XY_ROUTES.elf is now in the working directory
```

No worked tutorial example here on purpose — the parameters that make this *produce a valid* routing ELF are tied to specific fabric configurations and not something this skill should fabricate. Consult the SDK's own internal scripts (`${SDK}/cs_sdk/py_root/cerebras/sdk/...` — look for callers of `CslWseRouter` and `generate_route_elf`) for a working invocation against a known fabric.

## Gotchas

- **`CardinalDirection` ≠ `Route`.** Different values, different scope. NORTH is `0` in `CardinalDirection`, `3` in `Route`. The compiler won't warn you if you confuse them.
- **`CslWseNetlist` is a "prototype" library** per its own docstring. Treat the surface as unstable across SDK versions. The pinning header is your audit trail.
- **`Tile` lives in `streamerpybind`, not in `cslwsenetlist`.** Importing from the wrong module gives an `ImportError`.
- **`generate_route_elf()` writes to the current working directory.** No path argument. `chdir` before calling, or your output ELF lands in the wrong place.
- **`CslIoRouting` constructor is not for users.** Its `Point` / `AbstractRectangle` arguments aren't Python-constructible — the runtime builds them indirectly via `CslWseNetlist` / `CslWseRouter`. Trying to instantiate it standalone is a dead end.
- **Don't mix `CslIoRouting` with `RoutingPosition`.** They live in different layers — `CslIoRouting` is the C++ routing primitive (one per source-destination pair); `RoutingPosition` is the SdkLayout-side per-PE switch-table row. Both describe routing but the data shapes don't interconvert.
- **`route_*` methods return `int`** — the pybind doc doesn't disambiguate whether that's a status code, a leg count, or something else. Inspect the return for completeness checks; don't depend on the specific value beyond "non-negative on success."

## See also

- [SKILL-SDKRUNTIME.md](SKILL-SDKRUNTIME.md) — entry-point overview; the user-facing API map.
- [SKILL-SDKLAYOUT.md](SKILL-SDKLAYOUT.md) — the *high-level* routing types end-users use (`Color`, `Route`, `Edge`, `RoutingPosition`). Completely separate from what's documented here.
- [SKILL-ROUTES.md](SKILL-ROUTES.md) — CSL-side fabric routing (colors, color swapping, CE injection).
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md) — how memcpy uses the ELF produced by this pipeline.
- [SKILL-TOOLCHAIN.md](SKILL-TOOLCHAIN.md) — `cslc --memcpy --channels N` and the fabric-dim arithmetic that ties to the netlist `width` × `height`.
- `_generated/sdkruntime-surface.json` — every signature documented here, machine-readable. The `cerebras.sdk.runtime.routepybind` and the four `cslwse*` modules are all captured.
- `_generated/sdkruntime-symbols.txt` — demangled C++ symbols including the `cerebras::SdkLayout::Color` / `Route` / `RoutingPosition` symbols *not* in this scope.
