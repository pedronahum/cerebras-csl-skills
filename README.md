# cerebras-csl-skills

Claude Code skills for developing in **CSL** (Cerebras Software Language) — the kernel language for the Cerebras Wafer-Scale Engine.

Modeled after [`avsm/ocaml-claude-marketplace`'s oxcaml skills](https://github.com/avsm/ocaml-claude-marketplace/tree/main/plugins/ocaml-dev/skills/oxcaml): a router `SKILL.md` plus one `SKILL-<TOPIC>.md` per language domain.

## Layout

- `SKILL.md` — entry-point router. Frontmatter, language overview, cheat sheet, and a table of cross-references to the specialized files.
- `SKILL-<TOPIC>.md` — deep dives. Each file is self-contained for one language domain (syntax, DSDs, tasks, type system, etc.).
- `install.sh` — symlinks the skill files into `~/.claude/skills/csl/` so Claude Code can discover and load them.

## Install

```sh
./install.sh
```

This creates `~/.claude/skills/csl/` as a symlink to this repo, so edits here apply immediately to the loaded skill.

## Source of truth

Authoritative reference for everything in here: <https://sdk.cerebras.net/csl/language_index>. When a skill file disagrees with the upstream docs, the upstream docs win — open an issue / PR.

## SDK version

Skills are written against SDK **2.10.0** (build `sdk-202604101435`). Targeting `--arch=wse3`.
