#!/usr/bin/env python3
"""Extract the pybind11 surface of the Cerebras SDK runtime modules.

Designed to be run *inside the SDK Apptainer/Singularity SIF* via `cs_python`.
Walks every public pybind module that ships with the SDK and emits a single
JSON file describing every class, enum, method, free function, and constant
on the public surface — together with provenance metadata (SDK semver, SIF
filename, SIF sha256, build id, git short, extraction timestamp, Python
version) so the resulting documentation can be pinned to a specific build.

Usage (typical, inside Lima):

    cs_python scripts/extract_sdk_surface.py --out _generated/sdkruntime-surface.json

Optional flags:

    --sif PATH         path to the SDK SIF (default: auto-detect via $CB_SDK_SIF
                       or sibling SIF next to $CS_PYTHON wrapper).
    --sha256-manifest  path to a sha256sum.txt that already lists the SIF;
                       avoids recomputing the hash. Falls back to live hashing.

The output is intentionally JSON (not YAML) so this script can run under any
cs_python build without depending on PyYAML being present in the SIF.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib
import inspect
import json
import os
import platform
import re
import sys
from pathlib import Path

# Pybind modules we want to introspect. Add new ones here as the SDK grows.
MODULES = [
    "cerebras.sdk.runtime.sdkruntimepybind",
    "cerebras.sdk.runtime.routepybind",
    "cerebras.sdk.debug.lib.symbol.csldebugpybind",
    "cerebras.sdk.debug.lib.instruction_trace.sdkinstrtracepybind",
    "cerebras.sdk.debug.lib.rectangleopspybind",
    "cerebras.sdk.debug.lib.wavelet_trace.wavelettracepybind",
]

# Pure-Python shims that complement the pybind modules. We capture their
# public function signatures too — they're part of the documented surface.
PY_MODULES = [
    "cerebras.sdk.sdk_utils",
    # Memcpy-infrastructure routing prototype (consumers of routepybind).
    "cerebras.sdk.runtime.cslwsenetlist",
    "cerebras.sdk.runtime.cslwsepintable",
    "cerebras.sdk.runtime.cslwserouter",
    "cerebras.sdk.runtime.cslwserouteasm",
]


_SIG_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(.*\)\s*(?:->\s*.+)?\s*$")


def split_pybind_doc(doc: str | None) -> tuple[list[str], str | None]:
    """Pybind11 stores the call signature(s) on the first lines of __doc__.

    Two shapes show up in this SDK:

      single:
        name(self: ..., arg0: ..., ...) -> ret
        <optional body docstring>

      overloaded:
        name(*args, **kwargs)
        Overloaded function.

        1. name(...) -> ret

        2. name(...) -> ret

        <optional body docstring>

    Return (signatures, body_doc).
    """
    if not doc:
        return [], None
    lines = doc.splitlines()
    sigs: list[str] = []
    body_start = 0

    # Detect "Overloaded function." marker anywhere in the first few lines.
    overload_marker = -1
    for i, line in enumerate(lines[:5]):
        if line.strip().lower().startswith("overloaded function"):
            overload_marker = i
            break

    if overload_marker >= 0:
        # Pybind11 sometimes interleaves descriptive prose between numbered
        # overload signatures. Scan to the end of the docstring and collect
        # every numbered-signature line, treating non-numbered lines as
        # either blank separators or per-overload prose (we drop the prose).
        i = overload_marker + 1
        body_lines: list[str] = []
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            m = re.match(r"^\d+\.\s+(.*)", stripped)
            if m:
                sigs.append(m.group(1).strip())
            else:
                body_lines.append(line)
            i += 1
        # Compact body: drop leading/trailing blank lines.
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        body = "\n".join(body_lines).strip() or None
        return sigs, body
    else:
        first = lines[0].strip()
        if _SIG_RE.match(first):
            sigs.append(first)
            body_start = 1

    body = "\n".join(lines[body_start:]).strip() or None
    return sigs, body


def describe_callable(obj) -> dict:
    """Describe a function / method / builtin."""
    doc = getattr(obj, "__doc__", None) or ""
    sigs, body = split_pybind_doc(doc)
    info: dict = {"kind": "callable"}
    if sigs:
        info["signatures"] = sigs
    # Also try inspect.signature for pure-Python callables — pybind ones
    # usually raise ValueError here, which is fine.
    try:
        info["python_signature"] = str(inspect.signature(obj))
    except (TypeError, ValueError):
        pass
    if body:
        info["doc"] = body
    return info


def describe_attribute(name: str, obj) -> dict:
    """Describe a non-callable class/module attribute (property, constant)."""
    if isinstance(obj, (bool, int, float, str)):
        return {"kind": "value", "type": type(obj).__name__, "value": obj}
    if isinstance(obj, property):
        return {"kind": "property", "doc": obj.__doc__}
    # Pybind enum member: has `.name` and `.value` attributes
    if hasattr(obj, "name") and hasattr(obj, "value") and not callable(obj):
        try:
            return {"kind": "enum_member", "name": obj.name, "value": int(obj.value)}
        except Exception:
            return {"kind": "enum_member", "name": str(obj.name), "value": repr(obj.value)}
    return {"kind": "attribute", "repr": repr(obj)[:200]}


def describe_class(cls) -> dict:
    members: dict[str, dict] = {}
    for name in sorted(dir(cls)):
        if name.startswith("_") and name != "__init__":
            continue
        try:
            attr = inspect.getattr_static(cls, name)
        except AttributeError:
            continue
        # Resolve descriptors to the actual value where reasonable
        try:
            live = getattr(cls, name)
        except Exception:
            live = attr
        if callable(live) and not inspect.isclass(live):
            members[name] = describe_callable(live)
        elif inspect.isclass(live):
            members[name] = {"kind": "nested_class", "qualname": live.__qualname__}
        else:
            members[name] = describe_attribute(name, live)

    info: dict = {
        "qualname": cls.__qualname__,
        "module": cls.__module__,
        "bases": [b.__qualname__ for b in cls.__bases__ if b is not object],
        "doc": (cls.__doc__ or None),
        "members": members,
    }

    # Pybind11 enums expose `__members__` mapping name -> enum value.
    if hasattr(cls, "__members__"):
        info["kind"] = "enum"
        values: dict[str, int | str] = {}
        for k, v in cls.__members__.items():
            try:
                values[k] = int(v)
            except (TypeError, ValueError):
                values[k] = repr(v)
        info["values"] = values
    else:
        info["kind"] = "class"
    return info


def describe_module(mod) -> dict:
    classes: dict[str, dict] = {}
    free_functions: dict[str, dict] = {}
    constants: dict[str, dict] = {}
    for name in sorted(dir(mod)):
        if name.startswith("_") and name != "__init__":
            continue
        try:
            attr = getattr(mod, name)
        except AttributeError:
            continue
        if inspect.isclass(attr):
            classes[name] = describe_class(attr)
        elif callable(attr):
            free_functions[name] = describe_callable(attr)
        else:
            constants[name] = describe_attribute(name, attr)
    return {
        "file": getattr(mod, "__file__", None),
        "doc": (mod.__doc__ or None),
        "classes": classes,
        "free_functions": free_functions,
        "constants": constants,
    }


# ---------- provenance ----------

_SIF_RE = re.compile(
    r"^sdk-cbcore-(?P<version>[\d.]+)-sdk-(?P<build>\d+)-(?P<git>[0-9a-f]+)\.sif$"
)


def parse_sif_filename(name: str) -> dict:
    m = _SIF_RE.match(name)
    if not m:
        return {"version": None, "build": None, "git": None}
    return {
        "version": m.group("version"),
        "build": m.group("build"),
        "git": m.group("git"),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lookup_sha256_in_manifest(manifest: Path, target_name: str) -> str | None:
    if not manifest.exists():
        return None
    with open(manifest) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == target_name:
                return parts[0]
    return None


def detect_sdk_meta(sif: Path | None, manifest: Path | None) -> dict:
    meta: dict = {
        "version": None,
        "build": None,
        "git": None,
        "sif_filename": None,
        "sif_sha256": None,
        "sif_sha256_source": None,
    }

    # Preferred path: provenance was resolved on the host (outside the SIF)
    # and passed in via env vars. Inside the SIF, the host SDK dir isn't
    # bind-mounted so we can't see the .sif file ourselves.
    env_keys = {
        "version": "CB_SDK_VERSION",
        "build": "CB_SDK_BUILD",
        "git": "CB_SDK_GIT",
        "sif_filename": "CB_SDK_SIF_NAME",
        "sif_sha256": "CB_SDK_SIF_SHA256",
        "sif_sha256_source": "CB_SDK_SIF_SHA256_SOURCE",
    }
    env_hit = False
    for k, ev in env_keys.items():
        v = os.environ.get(ev)
        if v:
            meta[k] = v
            env_hit = True
    if env_hit:
        return meta

    # Fallback: try to see the SIF directly (only works on the host).
    if sif is None:
        return meta
    if not sif.exists():
        meta["sif_filename"] = sif.name
        return meta
    parsed = parse_sif_filename(sif.name)
    meta.update(parsed)
    meta["sif_filename"] = sif.name
    if manifest is not None:
        s = lookup_sha256_in_manifest(manifest, sif.name)
        if s:
            meta["sif_sha256"] = s
            meta["sif_sha256_source"] = str(manifest)
    if meta["sif_sha256"] is None:
        meta["sif_sha256"] = sha256_file(sif)
        meta["sif_sha256_source"] = "computed"
    return meta


def autodetect_sif() -> Path | None:
    env = os.environ.get("CB_SDK_SIF") or os.environ.get("CSDK_SIF")
    if env:
        p = Path(env)
        if p.exists():
            return p
    # cs_python wrapper sets SINGULARITY_NAME but not the path; fall back to
    # the conventional locations on this machine.
    candidates = [
        Path("/Users/pedro/programming/cerebras/sdk"),
        Path(os.path.expanduser("~/programming/cerebras/sdk")),
    ]
    for d in candidates:
        if d.exists():
            sifs = sorted(d.glob("sdk-cbcore-*.sif"))
            if sifs:
                return sifs[-1]
    return None


# ---------- main ----------


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="output JSON path")
    p.add_argument("--sif", default=None, help="path to the SDK SIF (default: auto)")
    p.add_argument(
        "--sha256-manifest",
        default=None,
        help="sha256sum.txt that lists the SIF (avoids recomputing)",
    )
    # Provenance can be passed in directly when we can't see the SIF from
    # inside the container (the usual case: cs_python invokes singularity -C
    # which strips env and unmounts host paths). These override autodetect.
    p.add_argument("--sdk-version", default=None)
    p.add_argument("--sdk-build", default=None)
    p.add_argument("--sdk-git", default=None)
    p.add_argument("--sif-name", default=None)
    p.add_argument("--sif-sha256", default=None)
    p.add_argument("--sif-sha256-source", default=None)
    args = p.parse_args()

    sif = Path(args.sif) if args.sif else autodetect_sif()
    manifest = Path(args.sha256_manifest) if args.sha256_manifest else None
    if manifest is None and sif is not None:
        cand = sif.parent / "sha256sum.txt"
        if cand.exists():
            manifest = cand
    sdk_meta = detect_sdk_meta(sif, manifest)

    # CLI overrides win — these survive the SIF boundary where env vars don't.
    for k, v in (
        ("version", args.sdk_version),
        ("build", args.sdk_build),
        ("git", args.sdk_git),
        ("sif_filename", args.sif_name),
        ("sif_sha256", args.sif_sha256),
        ("sif_sha256_source", args.sif_sha256_source),
    ):
        if v:
            sdk_meta[k] = v

    modules_out: dict[str, dict] = {}
    for modname in MODULES + PY_MODULES:
        try:
            mod = importlib.import_module(modname)
        except Exception as e:
            modules_out[modname] = {"error": f"{type(e).__name__}: {e}"}
            continue
        modules_out[modname] = describe_module(mod)

    out = {
        "schema_version": 1,
        "sdk": {
            **sdk_meta,
            "extracted_at": _dt.datetime.utcnow()
            .replace(microsecond=0)
            .isoformat()
            + "Z",
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "modules": modules_out,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str, sort_keys=False)

    print(f"Wrote {out_path}")
    print(f"  SDK version : {sdk_meta.get('version')}")
    print(f"  SDK build   : {sdk_meta.get('build')}")
    print(f"  SDK git     : {sdk_meta.get('git')}")
    print(f"  SIF sha256  : {sdk_meta.get('sif_sha256')}")
    print(f"  Source      : {sdk_meta.get('sif_sha256_source')}")
    print(f"  Modules OK  : {sum(1 for v in modules_out.values() if 'error' not in v)}"
          f" / {len(modules_out)}")
    for name, val in modules_out.items():
        if "error" in val:
            print(f"    ! {name}: {val['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
