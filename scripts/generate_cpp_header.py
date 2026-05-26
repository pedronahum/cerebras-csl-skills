#!/usr/bin/env python3
"""Generate a reconstructed C++ header for the user-facing SDK runtime API.

Reads the pinned dumps under _generated/ — both the demangled C++ symbol
surface and the pybind11 introspection JSON — and emits a single .hpp file
that mirrors the public surface of `cerebras::SdkRuntime`, `cerebras::SdkLayout`,
and their supporting types.

THE OUTPUT IS DOCUMENTATION, NOT A BUILD ARTIFACT.

- Method signatures come from `nm -D --demangle`.
- Enum names and values come from pybind11 introspection.
- Struct field layouts (`MemcpyOptions`, `SimfabConfig`) are inferred from
  pybind kwargs / Python class introspection; field order is best-guess.
- Default arguments, inline/template-only functions, member visibility,
  virtual/final, and method bodies are absent.
- Cerebras does not ship this header. They could rename or refactor the
  underlying ABI between releases without notice.

Regenerate after refreshing _generated/ via scripts/refresh_sdk_surface.sh.
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYMS_PATH = REPO / "_generated" / "sdkruntime-symbols.txt"
SURFACE_PATH = REPO / "_generated" / "sdkruntime-surface.json"
OUT_PATH = REPO / "_generated" / "cerebras_sdkruntime.hpp"


# Scopes that we surface in the header. Order here is the order they appear
# in the output. Nested classes are emitted after their enclosing class.
USER_SCOPES = [
    "cerebras::SimfabConfig",
    "cerebras::SdkExecutionPlatform",
    "cerebras::SdkCompileArtifacts",
    "cerebras::SdkRuntime",
    "cerebras::SdkRuntime::Task",
    "cerebras::SdkLayout",
    "cerebras::SdkLayout::Color",
    "cerebras::SdkLayout::RoutingPosition",
    "cerebras::SdkLayout::EdgeRouteInfo",
    "cerebras::SdkLayout::PortHandle",
    "cerebras::SdkLayout::CodeRegion",
]

# Members on these scopes that the pybind layer does NOT expose. We keep
# them in the header but tag them /* internal */ so the reader can see they
# exist in the .so but are not part of the API surface pybind commits to.
# Populated automatically by intersecting with the surface JSON.


# ---- type cleanup ----------------------------------------------------------

_BASIC_STRING_RE = re.compile(
    r"std::__cxx11::basic_string<\s*char\s*,\s*std::char_traits<char>\s*,"
    r"\s*std::allocator<char>\s*>"
)
_ABI_TAG_RE = re.compile(r"\[abi:cxx11\]")
_NLOHMANN_RE = re.compile(
    r"nlohmann::json_abi_v3_11_3::basic_json<[^()]*?, void>"
)
_FILESYSTEM_PATH_RE = re.compile(r"std::filesystem::__cxx11::path")
_CXX11_NS_RE = re.compile(r"std::__cxx11::")


def _strip_alloc_suffix(t: str, container: str) -> str:
    """Strip ", std::allocator<...>>" from std::vector / std::set / std::list."""
    needle = f"std::{container}<"
    out = []
    i = 0
    while i < len(t):
        idx = t.find(needle, i)
        if idx == -1:
            out.append(t[i:])
            break
        out.append(t[i:idx])
        # Find the matching closing > for this template
        depth = 0
        j = idx + len(needle)
        start_args = j
        while j < len(t):
            c = t[j]
            if c == "<":
                depth += 1
            elif c == ">":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        inner = t[start_args:j]   # arguments of std::container<...>
        # Strip the trailing ", std::allocator<...>" — walk from the right,
        # find the comma at depth 0 before the allocator.
        cleaned = _strip_last_allocator(inner)
        out.append(f"std::{container}<{cleaned}>")
        i = j + 1
    return "".join(out)


def _strip_last_allocator(s: str) -> str:
    """Given the inside of std::vector<X, std::allocator<Y>>, return X."""
    # Find the LAST top-level ',' followed by ' std::allocator<'.
    depth = 0
    last_comma = -1
    for i, c in enumerate(s):
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif c == "," and depth == 0:
            last_comma = i
    if last_comma == -1:
        return s.strip()
    head = s[:last_comma].strip()
    tail = s[last_comma + 1:].strip()
    if tail.startswith("std::allocator<"):
        return head
    return s.strip()


def clean_type(t: str) -> str:
    t = _BASIC_STRING_RE.sub("std::string", t)
    t = _ABI_TAG_RE.sub("", t)
    t = _FILESYSTEM_PATH_RE.sub("std::filesystem::path", t)
    t = _NLOHMANN_RE.sub("nlohmann::json", t)
    t = _CXX11_NS_RE.sub("std::", t)
    # Strip the allocator on std::vector and the comparator + allocator on
    # std::set / std::map (we lose some precision on map, but it's never
    # what the user wants to see anyway).
    t = _strip_alloc_suffix(t, "vector")
    t = _strip_alloc_suffix(t, "set")
    t = _strip_alloc_suffix(t, "list")
    # ` > ` → `>` (CRT-style template-close spacing)
    t = re.sub(r"\s+>", ">", t)
    # `const&` is the GNU dump style; switch to canonical `const &` if you prefer,
    # but the GNU style is more common in code, so keep it compact:
    t = t.replace("const &", "const&")
    t = t.replace(" const&", " const&")
    return t.strip()


# ---- parsing the symbols file ---------------------------------------------


def split_func(sig: str) -> tuple[list[str], list[str], bool] | None:
    """Split a demangled symbol into (qualified_parts, params, is_const).

    Returns None if the line doesn't look like a function signature.
    """
    sig = sig.strip()
    # Strip `[abi:cxx11]` attribute tag wherever it appears (function name,
    # nested template arg, etc.). pybind doesn't put it in the user-visible
    # name, so we shouldn't either.
    sig = _ABI_TAG_RE.sub("", sig)
    if not sig or not sig.endswith(")") and not sig.endswith(" const"):
        return None
    is_const = False
    if sig.endswith(" const"):
        sig = sig[:-len(" const")]
        is_const = True
    if not sig.endswith(")"):
        return None
    # Find the '(' at angle-bracket depth 0 that opens the outermost call.
    depth = 0
    open_paren = -1
    for i, c in enumerate(sig):
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif c == "(" and depth == 0:
            open_paren = i
            break
    if open_paren < 0:
        return None
    qualname = sig[:open_paren].strip()
    args_str = sig[open_paren + 1 : -1]
    parts = _split_qualname(qualname)
    params = _split_params(args_str)
    return parts, params, is_const


def _split_qualname(q: str) -> list[str]:
    """Split namespace::class::method on `::` at angle-bracket depth 0."""
    parts: list[str] = []
    depth = 0
    last = 0
    i = 0
    while i < len(q):
        c = q[i]
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif depth == 0 and q.startswith("::", i):
            parts.append(q[last:i])
            i += 2
            last = i
            continue
        i += 1
    parts.append(q[last:])
    return parts


def _split_params(s: str) -> list[str]:
    if not s.strip():
        return []
    params: list[str] = []
    depth = 0
    last = 0
    for i, c in enumerate(s):
        if c == "<" or c == "(":
            depth += 1
        elif c == ">" or c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            params.append(s[last:i].strip())
            last = i + 1
    params.append(s[last:].strip())
    return [p for p in params if p]


def parse_symbols(path: Path) -> dict[str, list[dict]]:
    """Return scope -> list of {name, params, const, lib, raw} dicts."""
    out: dict[str, list[dict]] = defaultdict(list)
    current_lib = "?"
    for line in path.read_text().splitlines():
        if line.startswith("## /cbcore/lib/"):
            current_lib = line.split("/")[-1]
            continue
        if not line or line.startswith("#"):
            continue
        res = split_func(line)
        if res is None:
            continue
        parts, params, is_const = res
        if len(parts) < 2:
            scope = ""
            name = parts[0] if parts else ""
        else:
            scope = "::".join(parts[:-1])
            name = parts[-1]
        out[scope].append({
            "name": name,
            "params": [clean_type(p) for p in params],
            "const": is_const,
            "lib": current_lib,
            "raw": line,
        })
    return out


# ---- pybind surface --------------------------------------------------------


def load_surface() -> dict:
    return json.loads(SURFACE_PATH.read_text())


def pybind_methods(surface: dict, py_class: str) -> dict:
    """name -> first signature string (or None)."""
    mod = surface["modules"]["cerebras.sdk.runtime.sdkruntimepybind"]
    cls = mod["classes"].get(py_class)
    if not cls:
        return {}
    out = {}
    for mname, m in cls["members"].items():
        if m.get("kind") != "callable":
            continue
        out[mname] = (m.get("signatures") or [None])[0]
    return out


def pybind_enum(surface: dict, py_class: str) -> dict:
    mod = surface["modules"]["cerebras.sdk.runtime.sdkruntimepybind"]
    cls = mod["classes"].get(py_class, {})
    return cls.get("values", {})


# ---- rendering -------------------------------------------------------------


SCOPE_TO_PY = {
    "cerebras::SdkRuntime": "SdkRuntime",
    "cerebras::SdkRuntime::Task": "Task",
    "cerebras::SdkLayout": "SdkLayout",
    "cerebras::SdkLayout::CodeRegion": "CodeRegion",
    "cerebras::SdkLayout::Color": "Color",
    "cerebras::SdkLayout::RoutingPosition": "RoutingPosition",
    "cerebras::SdkLayout::EdgeRouteInfo": "EdgeRouteInfo",
    "cerebras::SdkLayout::PortHandle": "PortHandle",
    "cerebras::SdkCompileArtifacts": "SdkCompileArtifacts",
    "cerebras::SdkExecutionPlatform": "SdkExecutionPlatform",
    "cerebras::SimfabConfig": "SimfabConfig",
}


def is_special(name: str, scope_last: str) -> str | None:
    if name == scope_last:
        return "ctor"
    if name == "~" + scope_last:
        return "dtor"
    if name.startswith("operator"):
        return "operator"
    return None


def render_member(m: dict, scope: str, in_pybind: set[str]) -> str:
    name = m["name"]
    params = m["params"]
    const_suffix = " const" if m["const"] else ""
    scope_parts = scope.split("::")
    scope_last = scope_parts[-1] if scope_parts else ""
    kind = is_special(name, scope_last)

    indent = "    "
    tag = "" if name in in_pybind or kind in ("ctor", "dtor", "operator") else "  /* internal — not in pybind */"

    pretty_params = ", ".join(params)
    if kind == "ctor":
        return f"{indent}{name}({pretty_params}){tag};"
    if kind == "dtor":
        return f"{indent}{name}({pretty_params}){tag};"
    if kind == "operator":
        # No return type recoverable from nm — write `auto` and move on.
        return f"{indent}auto {name}({pretty_params}){const_suffix}{tag};"
    # Regular method — return type not recoverable from nm. Use `auto`.
    return f"{indent}auto {name}({pretty_params}){const_suffix}{tag};"


def render_enum(name: str, values: dict) -> str:
    lines = [f"enum class {name} : int {{"]
    for k, v in values.items():
        lines.append(f"    {k} = {v},")
    lines.append("};")
    return "\n".join(lines)


def render_provenance(surface: dict) -> str:
    sdk = surface["sdk"]
    return textwrap.dedent(f"""\
        // ===========================================================================
        //  cerebras_sdkruntime.hpp — RECONSTRUCTED FROM SDK {sdk['version']}
        //  =====================  NOT CEREBRAS-AUTHORITATIVE  =====================
        //
        //  This header is a documentation artifact. Cerebras does not ship it.
        //  Treat it as the readable form of the SDK runtime's symbol surface, not
        //  as something you can build against.
        //
        //  Pinned to:
        //    SDK version : {sdk['version']}
        //    Build       : {sdk['build']}
        //    Git short   : {sdk['git']}
        //    SIF         : {sdk['sif_filename']}
        //    SIF sha256  : {sdk['sif_sha256']}
        //    Extracted   : {sdk['extracted_at']}
        //
        //  Sources used to reconstruct:
        //    (a) `nm -D --demangle` against 10 .so libraries in /cbcore/lib/ — for
        //        every member-function signature (parameter types, const-ness,
        //        overload set). See _generated/sdkruntime-symbols.txt.
        //    (b) pybind11 introspection of cerebras.sdk.runtime.sdkruntimepybind —
        //        for enum names+values, the user-facing-method subset, and the
        //        kwarg names that pybind splats from `MemcpyOptions`. See
        //        _generated/sdkruntime-surface.json.
        //
        //  Things this header DOES NOT recover:
        //    - Return types (nm carries the mangled parameter types but not the
        //      return; we use `auto` everywhere as a placeholder).
        //    - Default argument values (mangled symbols don't preserve them).
        //    - Struct field layouts (`MemcpyOptions`, internal helpers) —
        //      the field set is inferred from pybind kwargs; the ORDER is a
        //      best guess and may not match the actual ABI.
        //    - Member visibility (everything appears as `public`).
        //    - `virtual` / `final` / `inline` / `template` qualifiers.
        //    - Templates and inline functions that never produced a symbol.
        //
        //  Regenerate via `scripts/generate_cpp_header.py` after the dump is
        //  refreshed with `scripts/refresh_sdk_surface.sh`.
        // ===========================================================================
        """)


# ---- main ------------------------------------------------------------------


def main() -> int:
    if not SYMS_PATH.exists() or not SURFACE_PATH.exists():
        print(f"Missing _generated inputs. Run scripts/refresh_sdk_surface.sh first.",
              file=sys.stderr)
        return 1
    surface = load_surface()
    sym_groups = parse_symbols(SYMS_PATH)

    # Pre-compute the in-pybind set per scope.
    in_pybind_per_scope: dict[str, set[str]] = {}
    for scope, py_name in SCOPE_TO_PY.items():
        in_pybind_per_scope[scope] = set(pybind_methods(surface, py_name).keys())

    lines: list[str] = []
    lines.append(render_provenance(surface))
    lines.append("")
    lines.append("#pragma once")
    lines.append("")
    lines.append("#include <cstdint>")
    lines.append("#include <filesystem>")
    lines.append("#include <memory>")
    lines.append("#include <optional>")
    lines.append("#include <string>")
    lines.append("#include <tuple>")
    lines.append("#include <vector>")
    lines.append("")
    lines.append("// Forward declarations for types referenced in signatures but whose")
    lines.append("// definitions never make it into the .so symbol table (templates,")
    lines.append("// internal headers, etc.). Documented opaquely.")
    lines.append("namespace cerebras {")
    lines.append("    template <typename T> struct Point;")
    lines.append("    template <typename T> struct AbstractRectangle;")
    lines.append("    struct IntVector;       // (x, y) pair; from das_common")
    lines.append("    struct IntRectangle;    // ((x0,y0),(x1,y1)) rect; from das_common")
    lines.append("    class  MemcpyTask;      // internal — Task holds shared_ptr<MemcpyTask>")
    lines.append("")
    lines.append("    // RECONSTRUCTED. The field SET is inferred from pybind kwargs that")
    lines.append("    // get splatted into this struct on every memcpy_*/call call. The")
    lines.append("    // field ORDER and any padding/alignment is a GUESS — do not")
    lines.append("    // construct directly until layout is probed against a real SIF.")
    lines.append("    struct MemcpyOptions {")
    lines.append("        bool                  streaming;    // pybind kwarg")
    lines.append("        /*MemcpyOrder*/ int   order;        // pybind kwarg")
    lines.append("        /*MemcpyDataType*/ int data_type;   // pybind kwarg")
    lines.append("        bool                  nonblock;     // pybind kwarg")
    lines.append("    };")
    lines.append("} // namespace cerebras")
    lines.append("")
    lines.append("namespace nlohmann { class json; } // forward decl for SdkCompileArtifacts ctor")
    lines.append("")
    lines.append("namespace cerebras {")
    lines.append("")
    # Enums at cerebras:: scope
    for ename in ("SdkTarget", "MemcpyDataType", "MemcpyOrder"):
        values = pybind_enum(surface, ename)
        if values:
            lines.append(render_enum(ename, values))
            lines.append("")

    # Order of class blocks. We open the enclosing class, declare nested
    # classes/enums inline, then close. Nested-class member definitions go
    # out-of-line afterwards.
    def render_pybind_fallback(scope: str) -> list[str]:
        """For nested classes whose methods are inline (no .so symbol), fall
        back to the pybind-visible method list as comments inside the class
        body. Better than emitting an empty class."""
        py_class = SCOPE_TO_PY.get(scope)
        if not py_class:
            return []
        out = ["    // No C++ symbols for this class in the .so dump.",
               "    // The class is either header-only / inline or the runtime",
               "    // never emits standalone symbols for its members. Below are",
               "    // the methods pybind11 exposes — return types and arg names",
               "    // come from the pybind signature, not from C++ truth."]
        pyb = pybind_methods(surface, py_class)
        for mname, sig in sorted(pyb.items()):
            out.append(f"    //   {mname:<20} {sig or ''}")
        return out

    def emit_scope(scope: str) -> None:
        members = sym_groups.get(scope, [])
        scope_parts = scope.split("::")
        scope_last = scope_parts[-1]
        in_pyb = in_pybind_per_scope.get(scope, set())
        lines.append(f"// ---- {scope} {'-' * (60 - len(scope))}")
        # Class header
        if scope_last in ("Task",):
            # nested — emit out-of-line definition
            lines.append(f"class SdkRuntime::Task {{")
        elif scope == "cerebras::SdkLayout::CodeRegion":
            lines.append(f"class SdkLayout::CodeRegion {{")
        elif scope.startswith("cerebras::SdkLayout::"):
            inner = scope.split("::")[-1]
            lines.append(f"class SdkLayout::{inner} {{")
        elif scope.startswith("cerebras::"):
            inner = scope.split("::")[-1]
            lines.append(f"class {inner} {{")
        else:
            lines.append(f"class {scope_last} {{")
        lines.append("public:")
        # Special-case enums inside SdkLayout (Edge, Route, FP16TYPE) and inner
        # forward declarations.
        if scope == "cerebras::SdkLayout":
            for ename in ("Edge", "Route", "FP16TYPE"):
                values = pybind_enum(surface, ename)
                if values:
                    rendered = render_enum(ename, values)
                    for ln in rendered.splitlines():
                        lines.append("    " + ln)
                    lines.append("")
            for inner in ("Color", "RoutingPosition", "EdgeRouteInfo",
                          "PortHandle", "CodeRegion"):
                lines.append(f"    class {inner};")
            lines.append("")

        # Render members. If we have no nm-visible members, fall back to
        # pybind-visible methods as comments inside the class body.
        if members:
            for m in members:
                lines.append(render_member(m, scope, in_pyb))
        else:
            lines.extend(render_pybind_fallback(scope))
        lines.append("};")
        lines.append("")

    # SimfabConfig — pybind reveals its fields; nm has no ctor symbol.
    lines.append("// ---- cerebras::SimfabConfig (fields from pybind; no nm signature) ----")
    lines.append("struct SimfabConfig {")
    lines.append("    int  num_threads     = 16;     // pybind default")
    lines.append("    bool suppress_trace  = false;  // pybind default")
    lines.append("    bool dump_core       = false;  // pybind default")
    lines.append("    std::optional<std::filesystem::path> core_path = std::nullopt;")
    lines.append("};")
    lines.append("")

    for scope in (
        "cerebras::SdkExecutionPlatform",
        "cerebras::SdkCompileArtifacts",
        "cerebras::SdkRuntime",
        "cerebras::SdkRuntime::Task",
        "cerebras::SdkLayout",
        "cerebras::SdkLayout::Color",
        "cerebras::SdkLayout::RoutingPosition",
        "cerebras::SdkLayout::EdgeRouteInfo",
        "cerebras::SdkLayout::PortHandle",
        "cerebras::SdkLayout::CodeRegion",
    ):
        emit_scope(scope)

    # Free functions: pybind exposes get_platform/get_simulator/get_system/
    # get_edge_routing — these have NO C++ symbols in the .so dump, so they
    # live entirely inside the pybind module. Note this explicitly.
    lines.append("// ---- pybind-only free functions -----------------------------------")
    lines.append("// These appear in cerebras.sdk.runtime.sdkruntimepybind but have no")
    lines.append("// corresponding C++ symbols in the runtime .so libs — they exist only")
    lines.append("// inside the pybind binding code. Listed here for reference; they are")
    lines.append("// not part of the C++ API.")
    lines.append("//")
    lines.append("//   SdkExecutionPlatform get_platform(")
    lines.append("//       std::optional<std::string> addr = std::nullopt,")
    lines.append("//       SimfabConfig config = {},")
    lines.append("//       SdkTarget target = SdkTarget::WSE3);")
    lines.append("//   SdkExecutionPlatform get_simulator(")
    lines.append("//       SimfabConfig config = {},")
    lines.append("//       SdkTarget target = SdkTarget::WSE3);")
    lines.append("//   SdkExecutionPlatform get_system(std::string addr);")
    lines.append("//   SdkLayout::EdgeRouteInfo get_edge_routing(")
    lines.append("//       SdkLayout::Edge edge,")
    lines.append("//       std::vector<SdkLayout::RoutingPosition> routes);")
    lines.append("")
    lines.append("} // namespace cerebras")
    lines.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines))

    print(f"wrote {OUT_PATH}")
    print(f"  classes emitted: {len([s for s in USER_SCOPES])}")
    print(f"  total members  : {sum(len(sym_groups.get(s, [])) for s in USER_SCOPES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
