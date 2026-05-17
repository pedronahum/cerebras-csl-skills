---
name: csl-routes
description: CSL fabric routing — colors as logical channels, routes (NORTH/SOUTH/EAST/WEST/RAMP), per-color RX/TX direction control, switch tables and switch positions, advance_switch on fabout_dsd, control_transform for relaying control wavelets, color swapping (XOR-paired colors with axis-wise enable), CE Injection (WSE-2 only — color/4 queue rule, two priority modes), the layout-block intrinsics (@set_rectangle, @set_tile_code, @set_color_config, @set_local_color_config), and the host-side SdkLayout counterparts (Route, Edge, RoutingPosition). Covers what a "routable color" means on WSE-2 (0–23) vs WSE-3 (0–7 via input queues), and how the route configuration shapes data flow across PEs.
---

# Fabric Routing

A program on the WSE runs on a rectangle of PEs (tiles). PEs talk by exchanging *wavelets* over **colors** — logical wires assigned numeric ids. Each tile decides, per color, where wavelets come *from* and where they go *to*. That decision is the **route**.

Routes are configured at compile time inside the `layout { }` block, with `@set_color_config` and friends. The runtime sees the resolved switch tables; the program sources/sinks wavelets via `fabin_dsd` and `fabout_dsd` bound to the colors. The fabric does the rest.

This skill is the conceptual model for everything routing-related. For the *PE-side data plane* (DSDs bound to colors and queues), see [SKILL-DSDS.md](SKILL-DSDS.md). For the host-side topology DSL, see [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md#model-3--sdklayout-python-driven-layout--streams).

## Colors

A **color** is a logical channel id. The `color` type wraps a `u16`; construct one with `@get_color(N)`. Properties:

| Arch | Routable color ids | Notes |
|---|---|---|
| WSE-2 | 0..23 | All routable; ids 24–26 exist but aren't routable; >27 reserved by runtime. |
| WSE-3 | 0..7 (via input queues) | Only the lowest 8 colors connect to data-task input queues directly; higher colors still exist for routing but consume queues differently. |

```csl
const my_color: color = @get_color(12);
```

Some colors are **reserved** by memcpy and the runtime (see [SKILL-TASKS.md](SKILL-TASKS.md#reserved-task-ids-do-not-bind) for the full reservation map). Pick free ids for your own use:

- WSE-2: 0–20 (avoid 21–23 memcpy, 24–26 non-routable, ≥27 reserved).
- WSE-3: input queues 2–7 (queues 0–1 are memcpy).

## Routes

A **route** is the per-tile description of *which directions a color enters from and exits to*. The five directional codes:

```
NORTH, SOUTH, EAST, WEST    — fabric neighbours
RAMP                         — the compute element (the tile's own program)
```

Every color, on every tile that touches it, has:

- An **input route** — set of directions wavelets may arrive from.
- An **output route** — set of directions wavelets propagate to.

The input set and output set can be asymmetric, which is what makes corner turns and broadcasts possible:

```
A typical "send east, receive from west" forwarding tile:
  input route:  {WEST}
  output route: {EAST, RAMP}     // forward east AND deliver to local CE
```

## `@set_color_config` and friends

Inside the `layout { }` block:

```csl
layout {
  @set_rectangle(W, H);
  for (@range(i16, W)) |x| {
    for (@range(i16, H)) |y| {
      @set_tile_code(x, y, "pe_program.csl", .{ /* params */ });

      // Wire color `my_color` at tile (x, y): receive from WEST, send to EAST+RAMP
      @set_color_config(x, y, my_color, .{
        // ... route fields ...
      });
    }
  }
}
```

The companion `@set_local_color_config(color, .{...})` configures the calling PE's own routing — used inside a PE program file (not inside `layout`) when you want runtime / per-PE adjustment.

The exact field shape of the config struct is detailed in the upstream docs and depends on which submodule of `<tile_config>` you're going through (`<tile_config>.color_config.reset_routes`, `set_io_direction`, `toggle_io_direction`, `clear_io_direction`, etc. — see [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#tile_config)). For most use cases you'll be calling the library wrappers rather than `@set_color_config` directly.

## RX / TX direction control

Per color, two bitmasks decide which directions accept incoming wavelets (RX) and emit outgoing wavelets (TX). Asymmetric configurations are normal:

```
RX = {WEST, NORTH}    // receive from west and north
TX = {EAST}           // only send east
```

These are tweaked at runtime via `<tile_config>.color_config.set_io_direction(color, dir)` / `toggle_io_direction` / `clear_io_direction`.

## Switch tables and switch positions

The hardware switch on each tile holds a *table* of route configurations. A "position" indexes into the table; advancing the position lets a color use a sequence of different routes over time — essential for two-phase patterns like "first 10 wavelets to neighbour A, next 10 to neighbour B".

**Advancing the switch:**

- `fabout_dsd` with `.advance_switch = true` advances the switch one position per op completion.
- Control wavelets carrying switch-advance commands (via `<control>.encode_*`) advance the switch when they arrive.

```csl
const dsd = @get_dsd(fabout_dsd, .{
  .extent = 10, .fabric_color = c, .advance_switch = true,
});
@fmovs(dsd, src_dsd);    // each op completion bumps the switch
```

Switch-position config is also accessible directly via `<tile_config>.switch_config.set_switch_pos` / `set_current_switch_position` / `set_rxtx_switch_pos` (WSE-3+).

## Control wavelets and `control_transform`

Two related concepts:

- **Control wavelets** carry one of the `<control>.opcode` values (`NOP`, `SWITCH_ADV`, `SWITCH_RST`, `TEARDOWN`). They flow through the fabric just like data wavelets but trigger hardware behaviours rather than data tasks. Construct payloads with `<control>.encode_*`; send via a `fabout_dsd` with `.control = true`.

- **`control_transform`** on a `fabin_dsd` / `fabout_dsd` enables relaying control wavelets through a FIFO without consuming them as data. Used when a PE serves as a control-wavelet pass-through:

```csl
var in_dsd = @get_dsd(fabin_dsd, .{
  .fabric_color = recv_channel, .extent = 100,
  .input_queue = @get_input_queue(0), .control_transform = true,
});

const out_dsd = @get_dsd(fabout_dsd, .{
  .extent = 100, .fabric_color = send_channel,
  .output_queue = @get_output_queue(1), .control_transform = true,
});

var buf = @zeros([5]u32);
const fifo = @allocate_fifo(buf);

task relay() void {
  @mov32(fifo,    in_dsd,  .{ .async = true });
  @mov32(out_dsd, fifo,    .{ .async = true });
}
```

With `control_transform`, only the low 14 bits of the wavelet index are user-modifiable; the upper bits carry the control payload.

## Color swapping

A pair of colors whose ids differ only in the low bit (`x ^ y == 1`) can be configured to **swap**: wavelets arriving on one color route as if they arrived on the paired color, axis-wise (East-West or North-South enable independently).

Behaviours:

| Configuration | Effect |
|---|---|
| EW-swap enabled on one color of the pair | Horizontal-axis wavelets on either color route to **both** colors. |
| EW-swap enabled on both colors of the pair | Colors **exchange** horizontal-axis wavelets. |
| Both EW and NS enabled | CE injection data also participates in the swap. |

RX/TX masks still apply on top of swapping. Use this for symmetric multi-cast / broadcast patterns or to share routing infrastructure between two colors that have the same physical wire neighbours.

## CE Injection (WSE-2 only)

WSE-3 does **not** support CE Injection. On WSE-2, CE inject mode hard-wires a color directly to an output queue:

```
queue_index = color / 4    (integer division)
```

This means only one of every four colors can use CE inject simultaneously. The two priority modes determine arbitration between fabric traffic and the output queue:

| Mode | Behaviour |
|---|---|
| **Low priority** | Fabric traffic wins. Switch flips to the output queue only when the fabric buffers are empty. |
| **High priority** | Output queue wins. Switch flips back to fabric only when the queue empties. |

Control wavelets have **no** effect on CE inject mode — buffer and queue occupancy alone drive the switch.

## Host-side counterpart: `SdkLayout` primitives

When you build a layout in Python via `SdkLayout`, the same concepts appear as Python classes:

```python
from cerebras.sdk.runtime.sdkruntimepybind import Color, Edge, Route, RoutingPosition

rx_color = Color('rx')                  # name-keyed color
recv_routes = RoutingPosition().set_output([Route.RAMP])    # route table entry
send_routes = RoutingPosition().set_input ([Route.RAMP])

add2vec = layout.create_code_region('./add2vec.csl', 'add2vec', 1, 1)
add2vec.create_input_port (rx_color, Edge.RIGHT, [recv_routes], n_wavelets)
add2vec.create_output_port(tx_color, Edge.LEFT,  [send_routes], n_wavelets)
```

The mapping:

- `Route.RAMP/NORTH/SOUTH/EAST/WEST` ↔ CSL `RAMP/NORTH/SOUTH/EAST/WEST` enum codes.
- `Edge.LEFT/RIGHT/TOP/BOTTOM` ↔ the edges of the PE region, used to attach ports to the fabric boundary.
- `RoutingPosition` ↔ a single entry in the switch table; `set_input(...)`, `set_output(...)` configure the directions for that position.

See [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md#model-3--sdklayout-python-driven-layout--streams) for the full SdkLayout pipeline.

## Common patterns

### Linear chain (left-to-right pipeline)

Every interior PE: receive from WEST, send to EAST. End PEs: receive from RAMP or send to RAMP.

```
layout {
  for (@range(i16, W)) |x| {
    @set_tile_code(x, 0, "pe.csl", .{ .x = x, .last = (x == W-1) });
    // configure forward-color routing — covered by helper libs
  }
}
```

### Row/column broadcast

Configure the broadcast color to have output route `{ EAST }` and input route `{ WEST }` on all tiles in a row. The source tile injects from RAMP, every other tile receives from WEST and may also enable RAMP-output to deliver locally. The `<collectives_2d>` library does this for you (see [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#collectives_2d)).

### Two-phase routing via switch-advance

Phase 1: route color along EAST. Phase 2: route along SOUTH. Switch-table position 0 holds the EAST config; position 1 holds the SOUTH config; a control wavelet (or a `fabout_dsd` with `.advance_switch = true`) flips between them.

## Gotchas

- **Configuring an unroutable color id is a compile error.** Stick to 0–23 on WSE-2; 0–7 (or higher via fabric-only routing) on WSE-3.
- **Reserved colors silently break memcpy.** Don't bind your own routes to colors 21–23 / 27–31 on WSE-2 or queues 0–1 on WSE-3 unless you really know what you're doing.
- **RAMP appears in both input and output routes.** Including RAMP in input route means "deliver to local CE"; including RAMP in output route means "also forward to local CE". Asymmetric configs are common.
- **`advance_switch` advances per *op completion*, not per wavelet.** If your `extent` is 10, the switch advances once after all 10 wavelets, not 10 times.
- **Control wavelets are not data wavelets.** A `fabin_dsd` without `control_transform` won't see control wavelets; a `fabin_dsd` with it sees them but they don't appear in the value stream of data tasks. Plan binding accordingly.
- **Color swapping pairs are XOR-1-different (`x ^ y == 1`).** You can't pair color 7 with color 14, only with 6.
- **CE Injection's `queue_index = color / 4` is a one-way constraint.** Two colors with the same `color / 4` can't both be in CE inject mode simultaneously.
- **CE Injection doesn't react to control wavelets.** If your switching logic depends on control wavelets, don't use CE inject.
- **`@set_color_config` is layout-block-only.** `@set_local_color_config` is the runtime/PE-side counterpart.
- **The `<tile_config>.color_config` library wraps the raw config builtins.** Prefer the wrappers — they validate constraints the compiler can't always check.

## See also

- [SKILL.md](SKILL.md) — cheat sheet.
- [SKILL-DSDS.md](SKILL-DSDS.md) — `fabin_dsd` / `fabout_dsd`, `.advance_switch`, `.control_transform`, `.control`.
- [SKILL-TASKS.md](SKILL-TASKS.md) — data tasks, control tasks, queues bound to colors.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#tile_config) — `<tile_config>.color_config` / `switch_config` / `control_transform` submodules.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#control) — `<control>` for encoding control-wavelet payloads.
- [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md#collectives_2d) — pre-built collective routes.
- [SKILL-HOST-DEVICE.md](SKILL-HOST-DEVICE.md#model-3--sdklayout-python-driven-layout--streams) — Python-side `Color`, `Edge`, `Route`, `RoutingPosition`.
- Bundled tutorials grounded in routing: `topic-06-switches`, `topic-07-switches-entrypt`, `sdklayout-02-routing`, `sdklayout-03-ports-and-connections`.
- Upstream docs: <https://sdk.cerebras.net/csl/language/advanced-features>
