"""Content fingerprints for incremental preparation: invalidate generated output, not the player's assets.

Why: ABI-only keys missed generator fixes, and hashing translate.py alone missed changes in its imported modules.
No game bytes leave the machine. Called by prepare.py; unit tests use synthetic modules and tools.
"""

import ast
import hashlib
import json
import shutil
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def stamp(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


def files(root: Path, paths: list[Path]) -> str:
    return stamp(*(f"{p.relative_to(root).as_posix()}:{digest(p)}" for p in sorted(paths)))


def definitions(root: Path, rel: str, names: set[str]) -> str:
    """Track build recipes without recompiling the game for an unrelated launcher/setup change."""
    tree = ast.parse((root / rel).read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != names:
        raise ValueError(f"missing build recipe in {rel}")
    return stamp(*(ast.dump(n, include_attributes=False) for n in nodes))


def exefs_stamp(exefs: Path, modules: tuple[str, ...]) -> str:
    return stamp(*(name + ":" + digest(exefs / name) for name in modules))


def keys(root: Path, game: Path, exefs: Path, romfs: Path, mode: str, target: str,
         abi: str, cc: list[str], glslc: str, modules: tuple[str, ...]) -> dict[str, str]:
    source = exefs_stamp(exefs, modules)
    generator = list((root / "recomp").rglob("*.py")) + [root / "recomp/patches-mkw.txt"]
    shader = [root / "tools/shaders/extract.py", root / "tools/shaders/translate.py"]
    for folder in ("sm86/decode", "sm86/translate"):
        shader.extend((root / folder).rglob("*.py"))
    gen = stamp("generate-v2", source, files(root, generator))
    compiler = Path(shutil.which(cc[0]) or cc[0])
    shader_compiler = Path(shutil.which(glslc) or glslc)
    manifest = game / "setup/tool-inputs.json"
    tools = json.loads(manifest.read_text()) if manifest.is_file() else {}
    recipe = stamp(definitions(root, "tools/prepare/prepare.py", {"compile_game", "probe_link"}),
                   definitions(root, "tools/build/build.py", {"module_glue"}),
                   definitions(root, "tools/prepare/machine.py", {"crt_link", "crt_spec", "lld_link"}))
    crt = game / "setup/lib/crt"
    crt_key = ""
    if target == "windows" and crt.is_dir():
        spec = crt / "link.json"
        data = json.loads(spec.read_text()) if spec.is_file() else {}
        # Prebuilt CRT bytes may contain temporary build paths. Track their pinned inputs, not those incidental bytes.
        crt_key = data.get("inputs") or files(crt, [p for p in crt.rglob("*") if p.is_file()])
    compile_key = stamp("compile-v2", gen, abi, target, recipe, digest(compiler), *cc[1:], crt_key,
                        tools.get("compiler", ""))
    shader_recipe = definitions(root, "tools/prepare/prepare.py", {"shaders", "spec_command"})
    shader_key = stamp("shaders-v2", source, files(root, shader), shader_recipe, digest(shader_compiler),
                       json.dumps(tools.get("shaders", {}), sort_keys=True))
    exe = game / ("mkw.exe" if target == "windows" else "mkw")
    runtime = digest(exe) if exe.is_file() else "missing"
    return {"abi": abi, "exefs": stamp("exefs-v2", source), "romfs": f"{mode} {romfs}", "generate": gen,
            "compile": compile_key, "shaders": shader_key,
            "warm": stamp("warm-v2", compile_key, shader_key, runtime)}


def reusable(step: str, done: dict, wanted: dict, game: Path, work: Path, target: str) -> bool:
    """Generated C may have been cleaned up: recover it only when the library actually needs rebuilding."""
    lib = game / ("mkwgame.dll" if target == "windows" else "mkwgame.so")
    identity = game / "mkwgame.id"
    compiled = (done.get("compile") == wanted["compile"] and lib.is_file() and identity.is_file()
                and identity.read_text().strip() == wanted["abi"])
    if step == "generate":
        return done.get(step) == wanted[step] and (compiled or (work / "generated/layout.json").is_file())
    if step == "compile":
        return compiled
    if done.get(step) != wanted.get(step):
        return False
    if step == "shaders":
        return any((game / "spirv").glob("*.spv"))
    if step == "romfs":
        return wanted[step].startswith("link ") or (game / "romfs").is_dir()
    return step != "cleanup"


def compile_inputs(work: Path, key: str) -> None:
    """Resume objects only with the same inputs; their source mtimes alone cannot detect a new compiler/header."""
    obj = work / "obj"
    marker = obj / "inputs.sha256"
    if marker.is_file() and marker.read_text() == key:
        return
    shutil.rmtree(obj, ignore_errors=True)
    obj.mkdir(parents=True, exist_ok=True)
    marker.write_text(key)


def shader_inputs(game: Path, key: str) -> None:
    """translate.py's per-program shortcut does not include its compiler: invalidate verdicts when inputs change."""
    out = game / "spirv"
    marker = out / "setup-inputs.sha256"
    if marker.is_file() and marker.read_text() == key:
        return
    out.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.done", "*.glsl", "*.result"):
        for p in out.glob(pattern):
            p.unlink()
    # Keep existing SPIR-V until its replacement is built; an interrupted setup retains its matching resume markers.
    marker.write_text(key)
