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

echo
echo "[refresh] done."
echo "  - ${OUT_DIR}/sdkruntime-surface.json"
echo "  - ${OUT_DIR}/SDK-VERSION.txt"
echo "  - ${OUT_DIR}/sdkruntime-symbols.txt"
