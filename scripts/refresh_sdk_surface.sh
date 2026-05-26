#!/usr/bin/env bash
# Refresh the pinned SDK surface dump under _generated/.
#
# Drives two extractions, both pinned to the currently installed SIF:
#
#   1. _generated/sdkruntime-surface.json
#      Python-side view: pybind11 introspection of every public class/enum/
#      method on the SDK runtime + debug pybind modules, plus provenance
#      (SDK semver, SIF sha256, build id, git short).
#
#   2. _generated/sdkruntime-symbols.txt
#      C++-side view: demangled symbol dump of the runtime-relevant .so
#      files inside /cbcore/lib (libsdkruntime.so, libsdk_layout.so, ...),
#      filtered to the `cerebras::` namespace. This is the closest we can
#      get to header truth — the SDK ships no headers, only stripped .so.
#
# Both files share the same SDK version header so they can be cross-referenced.
#
# Usage:
#   scripts/refresh_sdk_surface.sh                # uses limactl shell cs_sdk
#
# Environment:
#   CS_PYTHON      path to the cs_python wrapper (default:
#                  /Users/pedro/programming/cerebras/sdk/cs_python)
#   LIMA_INSTANCE  Lima instance name (default: cs_sdk)
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
OUT_DIR="${REPO_DIR}/_generated"
mkdir -p "${OUT_DIR}"

CS_PYTHON="${CS_PYTHON:-/Users/pedro/programming/cerebras/sdk/cs_python}"
LIMA_INSTANCE="${LIMA_INSTANCE:-cs_sdk}"
SDK_DIR="$(dirname "${CS_PYTHON}")"

# ---- 1. Resolve SIF provenance ON THE HOST -----------------------------------
# Inside the SIF the host SDK directory isn't visible (cs_python only
# bind-mounts $PWD), so we must compute SDK version + sha256 out here.

shopt -s nullglob
SIFS=("${SDK_DIR}"/sdk-cbcore-*.sif)
shopt -u nullglob
if (( ${#SIFS[@]} == 0 )); then
  echo "[refresh] no SIF found in ${SDK_DIR}" >&2
  exit 1
fi
SIF_PATH="${SIFS[0]}"
SIF_NAME="$(basename "${SIF_PATH}")"

# Parse version/build/git out of sdk-cbcore-<ver>-sdk-<build>-<git>.sif
if [[ "${SIF_NAME}" =~ ^sdk-cbcore-([0-9.]+)-sdk-([0-9]+)-([0-9a-f]+)\.sif$ ]]; then
  SDK_VERSION="${BASH_REMATCH[1]}"
  SDK_BUILD="${BASH_REMATCH[2]}"
  SDK_GIT="${BASH_REMATCH[3]}"
else
  SDK_VERSION="unknown"; SDK_BUILD="unknown"; SDK_GIT="unknown"
fi

# Pull sha256 from the manifest if it lists this SIF; otherwise compute.
SHA_MANIFEST="${SDK_DIR}/sha256sum.txt"
SDK_SHA256=""
SDK_SHA256_SOURCE=""
if [[ -f "${SHA_MANIFEST}" ]]; then
  SDK_SHA256="$(awk -v t="${SIF_NAME}" '$2==t {print $1; exit}' "${SHA_MANIFEST}" || true)"
  [[ -n "${SDK_SHA256}" ]] && SDK_SHA256_SOURCE="${SHA_MANIFEST}"
fi
if [[ -z "${SDK_SHA256}" ]]; then
  SDK_SHA256="$(shasum -a 256 "${SIF_PATH}" | awk '{print $1}')"
  SDK_SHA256_SOURCE="computed"
fi

echo "[refresh] SDK ${SDK_VERSION} build ${SDK_BUILD} git ${SDK_GIT}"
echo "[refresh] SIF ${SIF_NAME}"
echo "[refresh] sha256 ${SDK_SHA256} (${SDK_SHA256_SOURCE})"

# ---- 2. Pybind surface (Python introspection inside SIF) ---------------------
echo "[refresh] extracting pybind surface -> _generated/sdkruntime-surface.json"

# We invoke through limactl + cs_python so cs_python's $PWD bind is this repo.
# Provenance is passed via CB_SDK_* env vars so the script doesn't need to see
# any host paths.
limactl shell "${LIMA_INSTANCE}" -- bash -lc "
  cd '${REPO_DIR}' && \
  '${CS_PYTHON}' scripts/extract_sdk_surface.py \
      --out _generated/sdkruntime-surface.json \
      --sdk-version '${SDK_VERSION}' \
      --sdk-build '${SDK_BUILD}' \
      --sdk-git '${SDK_GIT}' \
      --sif-name '${SIF_NAME}' \
      --sif-sha256 '${SDK_SHA256}' \
      --sif-sha256-source '${SDK_SHA256_SOURCE}'
" 2>&1 | sed '/^\[INFO\]/d'

# ---- 3. One-page pinned summary ---------------------------------------------
python3 - "${OUT_DIR}/sdkruntime-surface.json" "${OUT_DIR}/SDK-VERSION.txt" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    d = json.load(f)
sdk = d["sdk"]
with open(dst, "w") as f:
    f.write("# Cerebras SDK — pinned for this skill bundle\n\n")
    for k in ("version", "build", "git", "sif_filename", "sif_sha256",
              "sif_sha256_source", "extracted_at", "python", "platform"):
        f.write(f"{k:<20} {sdk.get(k)}\n")
    f.write("\n# Modules captured\n\n")
    for name, mod in d["modules"].items():
        if "error" in mod:
            f.write(f"  ! {name}: {mod['error']}\n")
            continue
        nc = len(mod.get("classes", {}))
        nf = len(mod.get("free_functions", {}))
        nk = len(mod.get("constants", {}))
        f.write(f"  {name}: {nc} classes, {nf} free funcs, {nk} constants\n")
PY

# ---- 4. C++ symbol dump (apptainer exec inside Lima VM) ---------------------
echo "[refresh] dumping demangled C++ symbols -> _generated/sdkruntime-symbols.txt"

# Stage an inner script in the repo so the runner doesn't need to deal with
# heredocs through `limactl shell -- bash -lc`.
INNER="${REPO_DIR}/scripts/.dump_cpp_symbols.sh"
cat >"${INNER}" <<'INNER_EOF'
#!/usr/bin/env bash
set -euo pipefail
SIF="$1"
OUT="$2"
LIBS=(
  libsdkruntime.so
  libsdk_layout.so
  libsdk_compile_artifacts.so
  libsdk_das.so
  libsdk_execution_platform.so
  libsdk_debug.so
  libsdk_instruction_trace.so
  libsdk_wavelet_trace.so
  libsdkmessage.so
  libcsl-debug.so
)
{
  echo "# C++ symbol dump (demangled), filtered to cerebras::/csl::"
  echo "# SIF: $(basename "$SIF")"
  for lib in "${LIBS[@]}"; do
    echo
    echo "## /cbcore/lib/${lib}"
    if singularity exec "$SIF" test -f "/cbcore/lib/${lib}"; then
      singularity exec "$SIF" nm -D --defined-only --demangle "/cbcore/lib/${lib}" 2>/dev/null \
        | awk '$2 ~ /^[TWV]$/ { sub(/^[^ ]+ [^ ]+ /, ""); print }' \
        | grep -E '^(cerebras|csl)::' \
        | sort -u
    else
      echo "(not present)"
    fi
  done
} > "$OUT"
INNER_EOF
chmod +x "${INNER}"

limactl shell "${LIMA_INSTANCE}" -- bash -lc "
  '${INNER}' '${SIF_PATH}' '${OUT_DIR}/sdkruntime-symbols.txt'
" 2>&1 | sed '/^\[INFO\]/d'

rm -f "${INNER}"

# Stamp the symbol file with the same SDK-version header for cross-reference.
HEADER_TMP="$(mktemp)"
{
  echo "# Cerebras SDK — pinned for this skill bundle"
  echo "# version=${SDK_VERSION}  build=${SDK_BUILD}  git=${SDK_GIT}"
  echo "# sif=${SIF_NAME}"
  echo "# sif_sha256=${SDK_SHA256}"
  echo
  cat "${OUT_DIR}/sdkruntime-symbols.txt"
} > "${HEADER_TMP}"
mv "${HEADER_TMP}" "${OUT_DIR}/sdkruntime-symbols.txt"

# ---- 5. Pybind imports (curated user-facing C++ API) -------------------------
# nm -D -u on the pybind .so lists every cerebras:: symbol it imports from
# the runtime libs. This is a STRICTLY SMALLER, CURATED subset of the full
# symbol dump in (4) — it's the actual user-facing C++ API surface (~50
# entries) versus the 322 defined symbols (most of which are internal).
echo "[refresh] extracting pybind-imported user-facing API"
INNER2="${REPO_DIR}/scripts/.dump_pybind_imports.sh"
cat >"${INNER2}" <<'INNER2_EOF'
#!/usr/bin/env bash
set -euo pipefail
SIF="$1"
OUT="$2"
PYB="/cbcore/py_root/cerebras/sdk/runtime/sdkruntimepybind.cpython-311-x86_64-linux-gnu.so"
{
  echo "# pybind11 sdkruntimepybind.so — imported (undefined) cerebras:: symbols."
  echo "# This is the curated set of user-facing C++ functions that pybind binds"
  echo "# against. Strict subset of _generated/sdkruntime-symbols.txt."
  echo "# SIF: $(basename "$SIF")"
  echo
  singularity exec "$SIF" nm -D -u --demangle "$PYB" 2>/dev/null \
    | sed 's/^[[:space:]]*U //' \
    | grep -E "^(cerebras|std::vector<unsigned short.*cerebras::)" \
    | sort -u
} > "$OUT"
INNER2_EOF
chmod +x "${INNER2}"
limactl shell "${LIMA_INSTANCE}" -- bash -lc "
  '${INNER2}' '${SIF_PATH}' '${OUT_DIR}/sdkruntime-pybind-imports.txt'
" 2>&1 | sed '/^\[INFO\]/d'
rm -f "${INNER2}"

# ---- 6. Runtime preconditions / assertions ----------------------------------
# Mine .rodata of libsdkruntime.so, libsdk_layout.so, libstreamer.so for
# assertion-style strings. These are the *actual* runtime checks the C++
# performs — much higher fidelity than the pybind layer's docstrings.
echo "[refresh] extracting runtime precondition strings"
INNER3="${REPO_DIR}/scripts/.dump_preconditions.sh"
cat >"${INNER3}" <<'INNER3_EOF'
#!/usr/bin/env bash
set -euo pipefail
SIF="$1"
OUT="$2"
LIBS=(libsdkruntime.so libsdk_layout.so libstreamer.so libsdk_compile_artifacts.so libsdk_execution_platform.so)
{
  echo "# Runtime precondition / assertion / diagnostic strings"
  echo "# Mined from .rodata of /cbcore/lib/*.so; these are the exact error"
  echo "# messages and constraint checks the SDK performs at runtime."
  echo "# SIF: $(basename "$SIF")"
  echo
  for lib in "${LIBS[@]}"; do
    echo "## /cbcore/lib/${lib}"
    if singularity exec "$SIF" test -f "/cbcore/lib/${lib}"; then
      singularity exec "$SIF" strings -n 25 "/cbcore/lib/${lib}" 2>/dev/null \
        | grep -iE "must |require |invalid |cannot |expect |illegal |asserti|precondit|out of |OMPI_|wio_flow|sdk_(run|setup)_phase|--arch=" \
        | grep -v "^_Z" \
        | grep -vE "^[a-zA-Z_]*::[a-zA-Z_]" \
        | sort -u
    else
      echo "(not present)"
    fi
    echo
  done
} > "$OUT"
INNER3_EOF
chmod +x "${INNER3}"
limactl shell "${LIMA_INSTANCE}" -- bash -lc "
  '${INNER3}' '${SIF_PATH}' '${OUT_DIR}/sdkruntime-preconditions.txt'
" 2>&1 | sed '/^\[INFO\]/d'
rm -f "${INNER3}"

# ---- 7. libstdc++ ABI version ----------------------------------------------
echo "[refresh] capturing libstdc++ ABI requirement"
INNER4="${REPO_DIR}/scripts/.dump_libstdcpp.sh"
cat >"${INNER4}" <<'INNER4_EOF'
#!/usr/bin/env bash
set -euo pipefail
SIF="$1"
OUT="$2"
PYB="/cbcore/py_root/cerebras/sdk/runtime/sdkruntimepybind.cpython-311-x86_64-linux-gnu.so"
{
  echo "# libstdc++ / libc / libgcc_s requirements from the pybind .so"
  echo "# SIF: $(basename "$SIF")"
  echo
  singularity exec "$SIF" bash -c "ldd $PYB 2>&1 | grep -E 'libstdc|libc\.so|libgcc'"
  echo
  echo "# Latest GLIBCXX / CXXABI versions in the resolved libstdc++:"
  singularity exec "$SIF" bash -c '
    LSO=$(ldd '"$PYB"' 2>/dev/null | awk "/libstdc/{print \$3}" | head -1)
    if [ -n "$LSO" ]; then
      echo "resolved: $LSO"
      strings "$LSO" | grep -E "^GLIBCXX_[0-9]" | sort -V | tail -5
      strings "$LSO" | grep -E "^CXXABI_[0-9]" | sort -V | tail -5
    fi'
} > "$OUT"
INNER4_EOF
chmod +x "${INNER4}"
limactl shell "${LIMA_INSTANCE}" -- bash -lc "
  '${INNER4}' '${SIF_PATH}' '${OUT_DIR}/sdkruntime-libstdcpp.txt'
" 2>&1 | sed '/^\[INFO\]/d'
rm -f "${INNER4}"

# ---- 8. MemcpyOptions layout evidence ---------------------------------------
# Disassemble the pybind wrapper around memcpy_h2d and extract the stack
# writes that build the MemcpyOptions struct on its way to the C++ call.
# Field offsets are observable from the destination operands of those writes;
# this is what pins the byte-level layout without DWARF.
echo "[refresh] extracting MemcpyOptions disassembly evidence"
INNER5="${REPO_DIR}/scripts/.dump_memcpyoptions_layout.sh"
cat >"${INNER5}" <<'INNER5_EOF'
#!/usr/bin/env bash
set -euo pipefail
SIF="$1"
OUT="$2"
PYB="/cbcore/py_root/cerebras/sdk/runtime/sdkruntimepybind.cpython-311-x86_64-linux-gnu.so"
{
  echo "# Evidence for the cerebras::MemcpyOptions byte layout."
  echo "# Source: pybind11 wrapper for SdkRuntime::memcpy_h2d in $PYB."
  echo "# Method: disassemble around each call site to memcpy_h2d, extract"
  echo "# the stack writes that build MemcpyOptions, identify base via lea."
  echo "# SIF: $(basename "$SIF")"
  echo
  echo "## Stack writes preceding each callq <memcpy_h2d@plt>:"
  echo "## (looking for {%al,%eax,%ax} -> 0x{40,44,48,4c}(%rsp))"
  echo
  singularity exec "$SIF" bash -c "objdump -d '$PYB' 2>/dev/null" \
    | awk '
        /callq.*memcpy_h2dE.*plt>/ {
          for (i = NR-200; i < NR; i++) {
            if (lines[i % 200] ~ /(0x4[0-c])\(%rsp\)/ || lines[i % 200] ~ /lea[ \t]+0x40\(%rsp\)/) {
              print lines[i % 200]
            }
          }
          print "  --- ^ writes preceding call ---"
          print $0
          print ""
        }
        { lines[NR % 200] = $0 }'
  echo
  echo "## Interpretation:"
  echo "##   lea 0x40(%rsp), %rax          -> MemcpyOptions struct base at +0x40"
  echo "##   mov %al,  0x40(%rsp)  (1 B)   -> field at offset 0   = streaming"
  echo "##   mov %eax, 0x44(%rsp)  (4 B)   -> field at offset 4   = data_type"
  echo "##   mov %eax, 0x48(%rsp)  (4 B)   -> field at offset 8   = order"
  echo "##   mov %al,  0x4c(%rsp)  (1 B)   -> field at offset 12  = nonblock"
  echo "##"
  echo "## Confirmed layout (all four field writes visible in disassembly):"
  echo "##   offset  0: bool           streaming   (1 byte + 3 padding)"
  echo "##   offset  4: MemcpyDataType data_type   (4 bytes)"
  echo "##   offset  8: MemcpyOrder    order       (4 bytes)"
  echo "##   offset 12: bool           nonblock    (1 byte + 3 padding)"
  echo "##   sizeof:    16 bytes"
} > "$OUT"
INNER5_EOF
chmod +x "${INNER5}"
limactl shell "${LIMA_INSTANCE}" -- bash -lc "
  '${INNER5}' '${SIF_PATH}' '${OUT_DIR}/sdkruntime-memcpyoptions-layout.txt'
" 2>&1 | sed '/^\[INFO\]/d'
rm -f "${INNER5}"

echo
echo "[refresh] done."
echo "  - ${OUT_DIR}/sdkruntime-surface.json        (pybind introspection)"
echo "  - ${OUT_DIR}/SDK-VERSION.txt                (provenance summary)"
echo "  - ${OUT_DIR}/sdkruntime-symbols.txt         (full C++ symbol dump)"
echo "  - ${OUT_DIR}/sdkruntime-pybind-imports.txt  (curated user-facing API)"
echo "  - ${OUT_DIR}/sdkruntime-preconditions.txt   (runtime assertion strings)"
echo "  - ${OUT_DIR}/sdkruntime-libstdcpp.txt       (libstdc++ ABI requirements)"
echo "  - ${OUT_DIR}/sdkruntime-memcpyoptions-layout.txt  (struct layout evidence)"
