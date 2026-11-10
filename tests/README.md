# tests

Tests that need neither the game nor a GPU, run by the CI on Linux and Windows (`.github/workflows/ci.yml`). The back
end's regression test runs over captures instead (`tools/test/`).

| File | What it checks |
|---|---|
| `test_setup.py` | The setup's command lines and files from folders with spaces and accents: the compiler's path on its way to the shader step (issue #29), the resume without `--source` after an update, the update's version order and its clean-up of `*.old` files |
| `test_defaults.py` | The memory caps a player gets with nothing set (`runtime/gfx/vk/device/vk_defaults.c`), built alone and checked on the GPUs players reported: the Radeon 660M keeps its measured caps, a large discrete GPU is not held to them (issue #31) |
| `test_diagnose.py` | Numeric diagnostics preserve slow-frame measurements while excluding private log lines, reject absent measurements, check synthetic dump headers without modifying them, and never overwrite a log |
| `test_incremental.py` | Preparation/resume with synthetic modules and tools: runtime-only, shader, generator and compiler updates; invalidation of per-program shader shortcuts, interrupted compilation, old-state migration and preserved game/save files |
| `test_update.py` | Published custom-version selection, checksum-verified staging, protected installation files, invalid ZIP paths and cleanup that preserves user backups; synthetic release responses only |

Usage: `uv run pytest tests`
