# Vendored sparrow binary

`sparrow.exe` is the bundled offline nesting sidecar for the "Ultra" quality tier.
The engine locates it via `core/layout/separation._resolve_sparrow_path()`.

- **Upstream:** https://github.com/JeroenGar/sparrow (MIT)
- **Commit:** `a4bfbbe0bf864a7eaf136f9d06456155b1163195`
- **Built with:** `cargo build --release`, `rustc 1.89.0 (29483883e 2025-08-04)`
- **Target:** Windows x64
- **Built on:** 2026-06-08

## Why committed

Offline, one-click install: user machines have no Rust toolchain or network. The
binary ships with the app. Refresh deliberately on upgrade — rebuild from the pinned
commit, replace `sparrow.exe`, and update this file.

## Rebuild

```
git clone https://github.com/JeroenGar/sparrow tools/sparrow
cd tools/sparrow && git checkout a4bfbbe && cargo build --release
# copy tools/sparrow/target/release/sparrow.exe -> engine/vendor/sparrow/sparrow.exe
```

## Licenses

- **sparrow** — MIT (see the upstream `LICENSE`).
- **jagua-rs** v0.7.2 (the collision engine sparrow links) — MPL-2.0. We ship an
  UNMODIFIED binary, so the MPL-2.0 source-availability notice suffices:
  https://github.com/JeroenGar/jagua-rs
