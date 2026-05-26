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


# ---- Python → C++ type translation (for pybind return types) ---------------


def _split_top(s: str, sep: str = ",") -> list[str]:
    out, depth, last = [], 0, 0
    for i, c in enumerate(s):
        if c in "([<":
            depth += 1
        elif c in ")]>":
            depth -= 1
        elif c == sep and depth == 0:
            out.append(s[last:i].strip())
            last = i + 1
    out.append(s[last:].strip())
    return [p for p in out if p]


_PY_PREFIX = "cerebras.sdk.runtime.sdkruntimepybind."


def py_type_to_cpp(t: str) -> str:
    t = t.strip()
    if not t:
        return ""
    # Strip the Python pybind-module prefix (`cerebras.sdk.runtime.sdkruntimepybind.X` → `X`)
    # then re-namespace common classes back into cerebras::.
    if t.startswith(_PY_PREFIX):
        bare = t[len(_PY_PREFIX):]
        # The mod-level names: prefix back to cerebras::, with known nested ones routed.
        if bare in ("Color", "Edge", "Route", "RoutingPosition", "EdgeRouteInfo",
                    "CodeRegion", "PortHandle", "FP16TYPE"):
            return f"cerebras::SdkLayout::{bare}"
        if bare == "Task":
            return "cerebras::SdkRuntime::Task"
        return f"cerebras::{bare}"
    # Simple scalar mappings
    simple = {
        "None": "void",
        "int": "int",
        "bool": "bool",
        "float": "float",
        "str": "std::string",
        "bytes": "std::string",
        "object": "pybind11::object",
        "tuple": "pybind11::tuple",
    }
    if t in simple:
        return simple[t]
    if t.startswith("Optional[") and t.endswith("]"):
        return f"std::optional<{py_type_to_cpp(t[9:-1])}>"
    if t.startswith("List[") and t.endswith("]"):
        return f"std::vector<{py_type_to_cpp(t[5:-1])}>"
    if t.startswith("Tuple[") and t.endswith("]"):
        parts = _split_top(t[6:-1])
        return f"std::tuple<{', '.join(py_type_to_cpp(p) for p in parts)}>"
    if t.startswith("Dict[") and t.endswith("]"):
        parts = _split_top(t[5:-1])
        if len(parts) == 2:
            return f"std::map<{py_type_to_cpp(parts[0])}, {py_type_to_cpp(parts[1])}>"
    if t.startswith("Callable["):
        return "/*Callable*/ void*"
    if "numpy.ndarray" in t:
        return "pybind11::array"
    # Already-C++ names (have :: or template syntax) — keep verbatim.
    return t


_ENUM_REPR_RE = re.compile(r"<([A-Za-z_][\w]*)\.([A-Za-z_][\w]*):\s*\d+>")


def py_default_to_cpp(v: str | None) -> str | None:
    """Translate Python default-value reprs to C++ literals.

    `None`        → `std::nullopt`  (works for any std::optional<T>)
    `True/False`  → `true/false`
    `[]`/`{}`     → `{}`
    `<E.X: 0>`    → `E::X`           (pybind enum repr)
    `'foo'`       → `\"foo\"`
    rest         → verbatim
    """
    if v is None:
        return None
    v = v.strip()
    if v == "None":
        return "std::nullopt"
    if v == "True":
        return "true"
    if v == "False":
        return "false"
    if v == "[]":
        return "{}"
    if v == "{}":
        return "{}"
    # 'foo' → "foo"
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        inner = v[1:-1]
        return f'"{inner}"'
    m = _ENUM_REPR_RE.match(v)
    if m:
        return f"{m.group(1)}::{m.group(2)}"
    return v


def parse_pybind_sig(sig: str | None) -> dict:
    """Parse 'name(args) -> ret' into structured form.

    Returns {'args': [{name, type, default}], 'ret': str|None, 'kwarg_only': bool}.
    """
    if not sig:
        return {"args": [], "ret": None}
    # Skip leading 'name('
    m = re.match(r"^[A-Za-z_]\w*\(", sig)
    if not m:
        return {"args": [], "ret": None}
    inner = sig[m.end():]
    # Find matching ')' at depth 0
    depth = 0
    close = -1
    for i, c in enumerate(inner):
        if c in "([<":
            depth += 1
        elif c in ")]>":
            if depth == 0:
                close = i
                break
            depth -= 1
    if close < 0:
        return {"args": [], "ret": None}
    args_part = inner[:close]
    tail = inner[close + 1:].strip()
    ret = None
    if tail.startswith("->"):
        ret = tail[2:].strip()
    args = []
    for raw in _split_top(args_part):
        if not raw or raw.startswith("self:") or raw == "self":
            continue
        if raw.startswith("*"):
            # *args / **kwargs — preserved as informational sentinel
            args.append({"name": raw, "type": None, "default": None, "vararg": True})
            continue
        # Strip "*," sentinel that pybind sometimes emits for keyword-only.
        # name: type[ = default]
        default = None
        if "=" in raw:
            head, default = raw.split("=", 1)
            default = default.strip()
        else:
            head = raw
        if ":" in head:
            nm, typ = head.split(":", 1)
            args.append({"name": nm.strip(), "type": typ.strip(), "default": default, "vararg": False})
        else:
            args.append({"name": head.strip(), "type": None, "default": default, "vararg": False})
    return {"args": args, "ret": ret}


def merge_nm_with_pybind(nm_params: list[str], py_args: list[dict]) -> list[dict]:
    """Zip nm C++ types with pybind arg metadata. Returns list of {type, name, default}.

    The C++ side is the source of truth for types and arity. Pybind only
    contributes argument NAMES and DEFAULTS for positions that line up; any
    trailing pybind args without a matching nm position are dropped (those
    are pybind-wrapper-only kwargs like read_symbol's `dtype`).

    If pybind has fewer named positional args than nm has, the trailing nm
    args remain unnamed.
    """
    # Only consider non-vararg pybind args for zipping.
    py_named = [a for a in py_args if not a.get("vararg") and a.get("name")]
    out = []
    for i, cpp_t in enumerate(nm_params):
        name = None
        default = None
        if i < len(py_named):
            cand = py_named[i]
            # Skip pybind names like 'arg0', 'arg1', ... (auto-generated)
            if cand["name"] and not re.match(r"^arg\d+$", cand["name"]):
                name = cand["name"]
            default = py_default_to_cpp(cand.get("default"))
        out.append({"type": cpp_t, "name": name, "default": default})
    return out


def render_param(p: dict) -> str:
    s = p["type"]
    if p["name"]:
        s += f" {p['name']}"
    if p["default"] is not None:
        s += f" = {p['default']}"
    return s


def render_member(m: dict, scope: str, in_pybind: set[str], pybind_sigs: dict) -> str:
    name = m["name"]
    params = m["params"]
    const_suffix = " const" if m["const"] else ""
    scope_parts = scope.split("::")
    scope_last = scope_parts[-1] if scope_parts else ""
    kind = is_special(name, scope_last)

    indent = "    "
    tag = "" if name in in_pybind or kind in ("ctor", "dtor", "operator") else "  /* internal — not in pybind */"

    # Pull pybind sig if available (for ctor we look up __init__; for ops, no).
    sig_key = "__init__" if kind == "ctor" else name
    parsed = parse_pybind_sig(pybind_sigs.get(sig_key))

    merged = merge_nm_with_pybind(params, parsed["args"])
    pretty = ", ".join(render_param(p) for p in merged)

    if kind == "ctor":
        return f"{indent}{name}({pretty}){tag};"
    if kind == "dtor":
        return f"{indent}{name}({pretty}){tag};"
    if kind == "operator":
        return f"{indent}auto {name}({pretty}){const_suffix}{tag};"
    ret = parsed["ret"]
    ret_cpp = py_type_to_cpp(ret) if ret else None
    if not ret_cpp:
        ret_cpp = "auto"
    return f"{indent}{ret_cpp} {name}({pretty}){const_suffix}{tag};"


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

    # Pre-compute the in-pybind set + full pybind sigs per scope.
    in_pybind_per_scope: dict[str, set[str]] = {}
    pybind_sigs_per_scope: dict[str, dict] = {}
    for scope, py_name in SCOPE_TO_PY.items():
        pyb = pybind_methods(surface, py_name)
        in_pybind_per_scope[scope] = set(pyb.keys())
        pybind_sigs_per_scope[scope] = pyb

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
    lines.append("namespace nlohmann { class json; } // forward decl for SdkCompileArtifacts ctor")
    lines.append("namespace pybind11 { class object; class array; } // for pybind wrapper-returning methods")
    lines.append("")
    lines.append("namespace cerebras {")
    lines.append("")
    lines.append("// Forward declarations for types referenced in signatures but whose")
    lines.append("// definitions never make it into the .so symbol table (templates,")
    lines.append("// internal headers, etc.).")
    lines.append("template <typename T> struct Point;")
    lines.append("template <typename T> struct AbstractRectangle;")
    lines.append("struct IntVector;       // (x, y) pair; from das_common")
    lines.append("struct IntRectangle;    // ((x0,y0),(x1,y1)) rect; from das_common")
    lines.append("class  MemcpyTask;      // internal — Task holds shared_ptr<MemcpyTask>")
    lines.append("")
    lines.append("// Internal logging globals (visible as imported symbols in pybind .so):")
    lines.append("namespace detail { class MessagePipe; }")
    lines.append("extern int mSdkWarning;     // logging tag")
    lines.append("")
    # Enums at cerebras:: scope — must come BEFORE MemcpyOptions uses them
    for ename in ("SdkTarget", "MemcpyDataType", "MemcpyOrder"):
        values = pybind_enum(surface, ename)
        if values:
            lines.append(render_enum(ename, values))
            lines.append("")
    lines.append("// RECONSTRUCTED. Field SET is from pybind kwargs that get splatted")
    lines.append("// into this struct. Field ORDER is recovered from pybind's py::arg")
    lines.append("// declaration order, which is embedded contiguously in the pybind")
    lines.append("// .so .rodata at offsets [streaming, data_type, order, nonblock].")
    lines.append("// Padding/alignment is still a GUESS; do not memcpy into this until")
    lines.append("// layout is ABI-probed against a real SIF.")
    lines.append("struct MemcpyOptions {")
    lines.append("    bool           streaming;    // pybind kwarg #1")
    lines.append("    MemcpyDataType data_type;    // pybind kwarg #2")
    lines.append("    MemcpyOrder    order;        // pybind kwarg #3")
    lines.append("    bool           nonblock;     // pybind kwarg #4")
    lines.append("};")
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
        # Special-case: SdkRuntime is PIMPL — declare the Impl forward decl
        # and document the four reverse-engineered ctor kwargs not in pybind's
        # __doc__ but accepted by the runtime (see SKILL-SDKRUNTIME-CPP.md).
        if scope == "cerebras::SdkRuntime":
            lines.append("    // PIMPL: opaque Impl handles wio_flow generation, simulator")
            lines.append("    // coordination, etc. Visible in nm via methods like")
            lines.append("    // cerebras::SdkRuntime::Impl::generate_wio_flow().")
            lines.append("    class Impl;")
            lines.append("    class Task;")
            lines.append("")
            lines.append("    // Documented pybind **kwargs that map to ctor positional args 3-8:")
            lines.append("    //   cmaddr               : str | None     — \"host:port\" or None (sim)")
            lines.append("    //   msg_level            : str             — DEBUG/INFO/WARNING/ERROR")
            lines.append("    //   suppress_simfab_trace: bool")
            lines.append("    //   simfab_numthreads    : int             — max 64")
            lines.append("    //   memcpy_required      : bool            — false only with SdkLayout")
            lines.append("    // Reverse-engineered kwargs (not in pybind __doc__; recovered from")
            lines.append("    // runtime .rodata; see SKILL-SDKRUNTIME-CPP.md):")
            lines.append("    //   setup_phase_only     : bool            — refuses run() if true")
            lines.append("    //   run_phase_only       : bool            — refuses load() if true")
            lines.append("    //   wio_flows            : str             — path to wio_flows.json")
            lines.append("    //   worker               : bool|int        — MPI worker mode")
            lines.append("")
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
        pyb_sigs = pybind_sigs_per_scope.get(scope, {})
        if members:
            for m in members:
                lines.append(render_member(m, scope, in_pyb, pyb_sigs))
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

    # Template helpers that ARE real exports — used by pybind to power the
    # typed runtime.send(name, np.float32) overloads.
    lines.append("// ---- cerebras::to_words<T> template helpers -----------------------")
    lines.append("// Exported instantiations (visible in libsdkruntime.so). Pack a host")
    lines.append("// vector<T> into a vector of 16-bit wavelet words. The pybind layer")
    lines.append("// calls these from its typed send(name, ndarray[T]) overloads.")
    lines.append("template <typename T>")
    lines.append("std::vector<unsigned short> to_words(std::vector<T> const&);")
    lines.append("")
    lines.append("// Explicit instantiations the runtime ships:")
    lines.append("extern template std::vector<unsigned short> to_words<float>         (std::vector<float>          const&);")
    lines.append("extern template std::vector<unsigned short> to_words<int>           (std::vector<int>            const&);")
    lines.append("extern template std::vector<unsigned short> to_words<unsigned int>  (std::vector<unsigned int>   const&);")
    lines.append("extern template std::vector<unsigned short> to_words<short>         (std::vector<short>          const&);")
    lines.append("extern template std::vector<unsigned short> to_words<unsigned short>(std::vector<unsigned short> const&);")
    lines.append("")
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
