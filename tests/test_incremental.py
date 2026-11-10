"""Exercise prepare.py's real resume state with synthetic files and fake expensive tools; never needs a game.

Runtime-only updates must not compile the game, while generator changes, missing output and interrupted builds
must not silently retain stale code. Usage: uv run pytest tests/test_incremental.py
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/prepare"))
import prepare  # noqa: E402


@pytest.fixture
def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, source, game = (tmp_path / name for name in ("package sources", "dump source", "Port C ñ"))
    for p in (root, source / "exefs", source / "romfs", game):
        p.mkdir(parents=True)
    for name in prepare.build.MODULES:
        (source / "exefs" / name).write_bytes(b"synthetic module " + name.encode())
    (source / "romfs/asset").write_bytes(b"synthetic resource")
    (game / "mkw.exe").write_bytes(b"synthetic runtime v1")
    (game / "saves").mkdir()
    (game / "saves/keep").write_text("player save")
    compiler = tmp_path / "fake cc.exe"
    compiler.write_bytes(b"synthetic compiler v1")
    glslc = tmp_path / "fake glslc.exe"
    glslc.write_bytes(b"synthetic shader compiler v1")
    for rel, text in {
        "recomp/gen.py": "GENERATOR = 1\n", "recomp/patches-mkw.txt": "synthetic patch list\n",
        "sm86/translate/glsl/alu.py": "ALU = 1\n", "sm86/decode/decoder.py": "DECODER = 1\n",
        "tools/shaders/extract.py": "EXTRACT = 1\n", "tools/shaders/translate.py": "TRANSLATE = 1\n",
        "tools/prepare/prepare.py": "def compile_game(): return 1\ndef probe_link(): return 1\n",
        "tools/build/build.py": "def module_glue(): return 1\n",
        "tools/prepare/machine.py": "def crt_link(): pass\ndef crt_spec(): pass\ndef lld_link(): pass\n",
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    calls = []
    fail_compile = [False]
    copy_tree = prepare.copy_tree

    def copy(src, dst, total, **kwargs):
        calls.append(dst.name)
        copy_tree(src, dst, total, **kwargs)

    def generate(exefs, work, jobs):
        calls.append("generate")
        (work / "generated").mkdir(parents=True, exist_ok=True)
        (work / "generated/layout.json").write_text("[]")

    def compile_game(game, exefs, work, cc, target, jobs):
        calls.append("compile")
        if fail_compile[0]:
            raise prepare.Failed("simulated interrupted compile")
        assert (work / "generated/layout.json").is_file()
        (game / "mkwgame.dll").write_bytes(b"synthetic compiled library")
        (game / "mkwgame.id").write_text("test-abi")

    def shaders(exefs, romfs, game, work, glslc, jobs, cc):
        calls.append("shaders")
        (game / "spirv").mkdir(exist_ok=True)
        (game / "spirv/synthetic.spv").write_bytes(b"synthetic shader placeholder")

    def warm(game, work):
        calls.append("warm")

    def check(src):
        return prepare.find_game(src)  # synthetic fixture: real version/count checks are exercised separately

    monkeypatch.setattr(prepare, "ROOT", root)
    monkeypatch.setattr(prepare, "own_children", lambda: None)
    monkeypatch.setattr(prepare, "mem_gb", lambda: 16)
    monkeypatch.setattr(prepare, "shader_jobs", lambda: 2)
    monkeypatch.setattr(prepare, "default_cc", lambda *_: [str(compiler)])
    monkeypatch.setattr(prepare, "default_glslc", lambda *_: str(glslc))
    monkeypatch.setattr(prepare.build, "game_id", lambda: "test-abi")
    monkeypatch.setattr(prepare, "check", check)
    for name, func in (("copy_tree", copy), ("generate", generate), ("compile_game", compile_game),
                       ("shaders", shaders), ("warm", warm)):
        monkeypatch.setattr(prepare, name, func)

    def run(resume=False):
        calls.clear()
        argv = ["prepare.py", "--game", str(game), "--target", "windows"]
        if not resume:
            argv += ["--source", str(source)]
        monkeypatch.setattr(sys, "argv", argv)
        stderr = sys.stderr
        try:
            prepare.main()
        finally:
            if sys.stderr is not stderr:
                sys.stderr.close()
                sys.stderr = stderr
        return calls.copy()

    run()
    assert (game / "saves/keep").read_text() == "player save"
    return root, source, game, compiler, calls, fail_compile, run


def test_runtime_only_update_skips_game_and_shader_compilation(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    library = (game / "mkwgame.dll").stat().st_mtime_ns
    asset = (game / "romfs/asset").stat().st_mtime_ns
    assert not (game / "setup-work").exists()  # cleanup must not force a fresh generate/compile
    assert run(resume=True) == []
    (game / "mkw.exe").write_bytes(b"synthetic runtime v2")
    assert run(resume=True) == ["warm"]
    assert (game / "mkwgame.dll").stat().st_mtime_ns == library
    assert (game / "romfs/asset").stat().st_mtime_ns == asset
    assert (game / "saves/keep").read_text() == "player save"


def test_imported_shader_change_rebuilds_only_shaders_and_warmup(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    (root / "sm86/translate/glsl/alu.py").write_text("ALU = 2\n")
    assert run() == ["shaders", "warm"]


def test_generator_fix_rebuilds_library_even_with_identical_abi(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    (root / "recomp/gen.py").write_text("GENERATOR = 2\n")
    assert run() == ["generate", "compile", "warm"]
    assert run() == []


def test_compiler_update_recovers_cleaned_generated_sources(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    compiler.write_bytes(b"synthetic compiler v2")
    assert run() == ["generate", "compile", "warm"]


def test_resume_after_compile_failure_keeps_finished_generation(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    (root / "recomp/gen.py").write_text("GENERATOR = 2\n")
    fail[0] = True
    with pytest.raises(SystemExit) as e:
        run()
    assert e.value.code == 1 and calls == ["generate", "compile"]
    assert (game / "mkwgame.dll").read_bytes() == b"synthetic compiled library"
    fail[0] = False
    assert run(resume=True) == ["compile", "warm"]


def test_missing_library_is_rebuilt_without_recopying_game(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    (game / "mkwgame.dll").unlink()
    assert run() == ["generate", "compile"]


def test_missing_library_identity_is_repaired(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    (game / "mkwgame.id").unlink()
    assert run() == ["generate", "compile"]
    assert (game / "mkwgame.id").read_text() == "test-abi"


def test_interrupted_objects_survive_resume_but_not_a_compiler_change(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    (game / "mkwgame.dll").unlink()
    fail[0] = True
    with pytest.raises(SystemExit):
        run()
    obj = game / "setup-work/obj/old.o"
    obj.write_bytes(b"partially completed compilation")
    with pytest.raises(SystemExit):
        run(resume=True)
    assert obj.read_bytes() == b"partially completed compilation"
    compiler.write_bytes(b"synthetic compiler v2")
    fail[0] = False
    assert run(resume=True) == ["compile", "warm"]
    assert not obj.exists()


def test_legacy_state_keeps_assets_and_refreshes_unverifiable_output_once(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    p = game / "setup-state.json"
    state = json.loads(p.read_text())
    state["done"].update(exefs=str(source / "exefs"), generate="legacy ABI-only key", compile="legacy ABI-only key",
                         shaders="legacy wrapper-only key", warm="legacy warm key")
    p.write_text(json.dumps(state))
    assert run() == ["generate", "compile", "shaders", "warm"]
    assert run() == []
    assert (game / "saves/keep").read_text() == "player save"


def test_original_dump_removed_uses_the_installed_copy(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    shutil.rmtree(source)
    assert run(resume=True) == []


def test_modified_installed_exefs_is_repaired_without_touching_source(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    p = game / "exefs/main"
    original = p.read_bytes()
    p.write_bytes(b"X" * len(original))
    assert run() == ["exefs"]
    assert p.read_bytes() == original == (source / "exefs/main").read_bytes()


def test_shader_tool_update_does_not_compile_the_game(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    tools = game / "setup/tool-inputs.json"
    tools.parent.mkdir(exist_ok=True)
    tools.write_text(json.dumps({"shaders": {"shaderc": "new verified tool input"}}))
    assert run() == ["shaders", "warm"]


def test_equivalent_prebuilt_crt_on_another_runner_does_not_recompile(install) -> None:
    root, source, game, compiler, calls, fail, run = install
    crt = game / "setup/lib/crt"
    crt.mkdir(parents=True)
    (crt / "link.json").write_text(json.dumps({"inputs": "pinned recipe and toolchain stamp"}))
    (crt / "library.lib").write_bytes(b"object with incidental build path A")
    run()  # adopt this toolchain
    (crt / "library.lib").write_bytes(b"object with incidental build path B")
    (game / "mkw.exe").write_bytes(b"runtime-only update from another runner")
    assert run() == ["warm"]
