---
name: csl-toolchain
description: Running the Cerebras SDK toolchain — cslc, cs_python, sdk_debug_shell — under Apptainer+Rosetta inside a Lima VM. CSL_IMPORT_PATH bind-mount semantics. Compile-flag reference (--arch, --fabric-dims, --fabric-offsets, --memcpy, --channels). Adding Python packages to cs_python via SINGULARITYENV_PYTHONPATH. Common error messages and what they actually mean.
---

# CSL Toolchain & Workflow

The Cerebras SDK on a Mac is **not a set of native binaries.** Every public command — `cslc`, `cs_python`, `csdb`, `sdk_debug_shell`, `cs_readelf` — is a thin host-side bash wrapper around `singularity exec <sdk-cbcore-*.sif>`. The actual toolchain runs inside a single Apptainer/Singularity image built for x86_64 Linux. On Apple Silicon this only works inside a Linux VM with Rosetta binfmt — Cerebras's recommended setup is Lima + Ubuntu ARM64 + Apptainer + Rosetta.

If a tool reports "command not found" outside the VM, that's expected. The wrappers live in your SDK directory and only resolve once you've entered the VM and put that directory on PATH.

## The wrappers, in one paragraph each

**`cs_python`** runs Python *inside* the SIF. It auto-detects the adjacent `*.sif`, sets `--pwd=$PWD`, bind-mounts `$PWD` and `$TMPDIR`, and execs `python "$@"` inside the container. Use it any time a `run.py` (or any Python that talks to the SDK runtime) needs the in-container `cerebras_*` packages.

**`cslc`** is the CSL compiler frontend. It delegates to `sdk_debug_shell compile "$@"`, which does the same singularity bind-and-exec dance as `cs_python` but additionally parses `CSL_IMPORT_PATH` (colon-separated) and adds a `--bind=<path>` for each entry. Output goes to the directory passed to `-o` (default `out/`).

**`sdk_debug_shell`** is the underlying multitool. `compile`, `debug`, and a handful of other subcommands route through it. `csdb` is a debugger frontend on top.

**Implication.** Inside the container, the only filesystem paths that exist are: `$PWD` (read-write), `/tmp` (read-write), and anything you bind via `CSL_IMPORT_PATH`. Code that reads files outside these paths — typically `@import_module("../../shared/foo.csl")` or a Python helper that opens `../data/x.bin` — will fail with "no such file or directory" even though the path exists on the host.

## CSL_IMPORT_PATH — the rule

```sh
export CSL_IMPORT_PATH=$(realpath path/to/parent1):$(realpath path/to/parent2)
```

- Each entry must be an **absolute realpath**. The wrappers feed each entry to `singularity --bind=`; relative paths or symlinks confuse the bind logic.
- Each entry adds a bind mount of *that exact directory* — not the cwd's ancestor. If your `@import_module` walks up two levels to `../../benchmark-libs/foo/`, you must export `realpath ../../benchmark-libs/` (or its parent), not `../..`.
- The same variable also gates non-CSL files the compiler may need to read (linker scripts, included headers) — so when in doubt, bind the project root.
- Composes additively: `export CSL_IMPORT_PATH=$CSL_IMPORT_PATH:$(realpath /some/other/dir)`.

Diagnostic: every `cslc` invocation prints `[INFO] User specified CSL_IMPORT_PATH=...` or `[INFO] CSL_IMPORT_PATH is not set`. If you see the latter and got a "no such file" error for a cross-directory import, that's your problem.

## Compile flags that matter

`cslc <entry>.csl [flags]`. Most flags are forwarded to `cslc-driver`; the wrapper accepts unknown options.

| Flag | Purpose |
|---|---|
| `--arch=wse2` / `--arch=wse3` | Target architecture. WSE-3 adds microthreads, message-passing library, and some new builtins. Mostly source-compatible. |
| `-o <dir>` | Output directory. Created if missing. Contains the ELF, debug info, fabric maps, and host-side metadata that `cs_python` consumes via `--name <dir>`. |
| `--fabric-dims=W,H` | Total fabric region the program may use (PE grid + memcpy overhead). Must be ≥ your `@set_rectangle(w,h)` plus the memcpy halo. Typical small program: `--fabric-dims=8,3`. |
| `--fabric-offsets=COL,ROW` | Offset of your PE grid's origin within the fabric region. The space outside the offset is reserved for memcpy routing. Typical: `--fabric-offsets=4,1`. |
| `--memcpy` | Enable the host↔device memcpy infrastructure. Required if your program uses `<memcpy/get_params>` or `<memcpy/memcpy>`. |
| `--channels N` | Number of memcpy channels (parallel host↔device transfer streams). `--channels 1` is correct for almost everything; benchmarks may use 2-4. **`--channels 0` selects the deprecated CSELFRunner runtime** — don't do this. |
| `--params KEY=VALUE,KEY=VALUE` | Compile-time parameter values forwarded to `param` declarations in your layout. Same effect as `.{ .KEY = VALUE }` in `@set_tile_code`. |
| `--colors COLORS` | Reserve specific fabric colors. Most user code lets the compiler allocate them. |
| `--import-path` | Same effect as `CSL_IMPORT_PATH`, but on the command line. The env var is usually more ergonomic. |
| `--verbose` | Prints the underlying `cslc-driver` invocation and intermediate steps. First thing to add when something's mysteriously wrong. |

The fabric-dims/offsets math, in one line: **`fabric_dims_W ≥ rectangle_W + offset_COL + 1`** and similarly for H. The compiler will error out (clearly) if your numbers don't fit.

## Canonical compile-run cycle

Every bundled example ships a `commands_wse3.sh` containing exactly the canonical invocation. The template:

```sh
#!/usr/bin/env bash
set -e

cslc --arch=wse3 ./layout.csl \
     --fabric-dims=8,3 --fabric-offsets=4,1 \
     -o out --memcpy --channels 1

cs_python run.py --name out
```

For a new project, copy `commands_wse3.sh` from the closest bundled example. The WSE-2 variant (`commands_wse2.sh`) differs only in `--arch=wse2`; flip if needed.

## Installing extra Python packages for `cs_python`

The SIF's Python is isolated — `pip install numpy` on the host does nothing for `cs_python`. The SDK ships a helper script (`cs_pip_install.sh`, also reproduced in the install guide):

```sh
# 1. Install into a host-side target dir
./cs_pip_install.sh /Users/pedro/programming/cerebras/sdk-site-packages scipy

# 2. Make cs_python see it via the singularityenv pythonpath
export SINGULARITYENV_PYTHONPATH=/Users/pedro/programming/cerebras/sdk-site-packages
cs_python run.py --name out
```

`SINGULARITYENV_PYTHONPATH` becomes `PYTHONPATH` inside the container. Persist it in `/home/pedro.guest/.profile` if you'll use it across sessions.

## Where the bundled libraries live

When you `@import_module("<memcpy/memcpy>", ...)`, the angle-bracket name resolves inside the SIF — not from your host filesystem. The compiler ships with the entire CSL standard library baked in: `<memcpy/*>`, `<math>`, `<debug>`, `<simprint>`, `<collectives_2d>`, `<dsd_ops>`, `<random>`, `<string>`, `<time>`, `<timer>`, `<tile_config>`, `<types>`, `<kernels>`, `<complex>`, `<malloc>`, `<empty>`, `<layout>`, `<message_passing>` (WSE-3), `<control>`, `<directions>`, `<data_utils>`.

You don't need to set anything to use these — just import. The angle-bracket form *only* searches the in-container library directory; user code uses bare relative paths or `CSL_IMPORT_PATH`-bound absolute paths.

## Common error messages

### `error: Unable to open ./src/../../somewhere/foo.csl: no such file or directory`
The path resolves on the host but is outside the container's bind mounts. Fix: add the relevant ancestor to `CSL_IMPORT_PATH`.

### `RuntimeError: n_channels=0 corresponds to the deprecated runtime CSELFRunner. Please use n_channels>0 with SdkRuntime`
You ran `cslc ... --channels 0` (or omitted `--channels` so it defaulted to 0). Add `--channels 1` and (almost always) `--memcpy`.

### `singularity: command not found` (inside the VM)
The VM was provisioned without Apptainer/SingularityCE. With the official Rosetta config, Apptainer is installed by the `provision: system` script and ships `/usr/bin/singularity` as a compatibility shim. Check `dpkg -l | grep apptainer`; re-provision the VM if missing.

### `cs_python` works but `import cerebras_sdk` fails
You're running the *host* Python, not `cs_python`. The wrapper logs `[INFO] === Calling container-hosted python ===` when it actually entered the container — if you don't see that line, you bypassed the wrapper.

### `Permission denied` for the SIF
Check `chmod +x sdk-cbcore-*.sif` — the SDK tarball extracts the executable bits, but `tar` invocations that strip permissions (e.g., across some network filesystems) can leave it non-executable. The wrappers will detect a missing SIF, not a non-executable one.

### Compile succeeds, simulation crashes immediately with no useful message
Three usual suspects:
1. `--fabric-dims` too small for the `@set_rectangle` + memcpy overhead. Try increasing both dimensions by 2.
2. You forgot `sys_mod.unblock_cmd_stream()` at the end of a host-callable function. The next memcpy hangs forever.
3. `@export_symbol` is outside a `comptime { }` block, so the host can't find the symbol by name. Look for `Could not find symbol` in the host-side log.

## Running multiple compilations / smoketesting

The repo ships a host-side `run_smoketests.sh` (under `/Users/pedro/programming/cerebras/`) that iterates `commands_wse3.sh` for every example with a per-test timeout and PASS/FAIL line per test. Use it after any toolchain-affecting change (new SDK version, VM rebuild, mount path change). Last validated run: 50/50 passing (32 tutorials + 18 benchmarks; the 5 sparse-solver benchmarks need `CSL_IMPORT_PATH` set to the bundled `benchmark-libs/`).

## Lima VM specifics (Apple Silicon)

The full install path is documented in [Cerebras's official installation guide](https://sdk.cerebras.net/installation-guide). One-paragraph recap:

```sh
brew install lima
sudo softwareupdate --install-rosetta --agree-to-license
cd /path/to/cerebras && limactl start ./config.yml --name cs_sdk
```

`config.yml` uses Ubuntu 24.04 ARM64, Apptainer from the official PPA, and `vmOpts.vz.rosetta.{enabled,binfmt}=true`. The Mac home is virtiofs-mounted at the *same* path inside the VM (`/Users/pedro` → `/Users/pedro`), so absolute paths under your home work in both contexts. The VM's own user home is `/home/pedro.guest` — that's where `~/.profile` (the canonical place for PATH/CSL_IMPORT_PATH exports) lives.

**Use `.profile`, not `.bashrc`, for env exports** that need to be visible to `limactl shell ... -- bash -lc '...'` automation. Ubuntu's default `.bashrc` early-returns for non-interactive shells, so exports placed there work for interactive sessions but vanish for scripted ones.

Health check from the host:

```sh
limactl list                                                          # cs_sdk: Running
limactl shell cs_sdk -- bash -lc 'which cslc && cslc --help | head'   # PATH + container plumbing
```

## Debugging

- `csdb` — interactive debugger. Same wrapper pattern.
- `cslc --verbose` — full driver invocation, useful when args aren't being passed through correctly.
- `<debug>` and `<simprint>` libraries — in-kernel printing during simulation. See [SKILL-LIBRARIES.md](SKILL-LIBRARIES.md) *(planned)*.
- `out/cerebras_sim.log` — produced by `cs_python run.py --name out`. Most simulation errors land here, not on stderr.

## Real hardware vs. simulator

`cs_python run.py --name out` runs the **simulator** by default. To target a real wafer, you pass `--cmaddr <ip>` (and a few other args) to your `run.py`; SdkRuntime then routes commands over the network to a real CS-2/CS-3. The compiled artifact in `out/` is identical — only the host-side runtime invocation changes.

## See also

- [SKILL.md](SKILL.md) — the cheat sheet and topic index.
- Cerebras installation guide: <https://sdk.cerebras.net/installation-guide>
- Lima config reference: <https://lima-vm.io/docs/config/>
- Apptainer bind mounts: <https://apptainer.org/docs/user/main/bind_paths_and_mounts.html>
