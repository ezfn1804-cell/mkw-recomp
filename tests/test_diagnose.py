"""Read-only Windows diagnostics: synthetic NSO headers, real log formats and private-data exclusion.

Usage: uv run pytest tests/test_diagnose.py
"""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/run/diagnose.py"
spec = importlib.util.spec_from_file_location("diagnose", SCRIPT)
diagnose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnose)

LOG = """[host] cfg: C:\\Users\\PrivateUser\\SecretFolder\\mkw.ini
[host] perf: frame 1800: interval avg 16.7 ms max 150.0 ms; world 12.0 s
[host] perf: frame 1800: gpu avg 12.00 ms (60 parts timed, 0 not); private suffix
[host] game: speed 0.99x over 5.0 s (300 frames, 0 interval changes)
[host] perf: slow frame 1742: 150.0 ms; blocked pipeline 0.0 texture 121.0 astc 20.0 fence 4.0 pacing 0.0
[host] frametime: exit: 1800 frames in 30.0 s, mean 60.0 fps, 1% low 40.0 fps, over 25 ms 18, 50 ms 3, 100 ms 1
[host] frametime:   worst frame 1742: 150.0 ms; pipeline build 0.0, texture upload 121.0 (astc 20.0), replay 125.0, fence/present wait 4.0, pacing 0.0
[host] FATAL: memory and assets should stay local
"""


def test_report_preserves_spikes_without_exporting_raw_log() -> None:
    report = diagnose.frame_report(LOG)
    assert "maximum 150.0 ms" in report  # an averaged 60-frame window must not hide its outlier
    assert "Image lente 1742: 150.0 ms" in report
    assert "Pic trace 1742: 150.0 ms" in report
    assert "textures 121.0 (ASTC 20.0)" in report
    assert ">100 ms 1" in report and "0.99x" in report
    for private in ("PrivateUser", "SecretFolder", "private suffix", "FATAL", "assets"):
        assert private not in report


@pytest.mark.parametrize("text", ["", "[host] launcher: quit", "[host] perf: frame broken: interval avg 1 ms"])
def test_no_measurements_is_an_error(text: str) -> None:
    with pytest.raises(ValueError, match="Aucune mesure"):
        diagnose.frame_report(text)


def test_gpu_loss_is_preserved_even_without_frame_timings() -> None:
    # Driver error metadata only; no shader code or raw fault-address dump is needed for the report.
    text = ("[host] vk: device fault: instruction pointer invalid at 0x123400 (precision 0x10)\n"
            "FATAL: vk: vkQueueSubmit2 of value 20522 failed (-4)\n")
    report = diagnose.frame_report(text)
    assert "VK_ERROR_DEVICE_LOST" in report and "pointeur d'instruction invalide" in report
    assert "0x123400" not in report


@pytest.mark.parametrize("kind, valid", [("base", True), ("other-version", False), ("encrypted", False), ("short", False)])
def test_version_gate_does_not_change_dump(tmp_path: Path, kind: str, valid: bool) -> None:
    (tmp_path / "romfs").mkdir()
    (tmp_path / "exefs").mkdir()
    # Synthetic bytes, not Nintendo code. Read the shared gate to detect drift if the supported version changes.
    sys.path.insert(0, str(SCRIPT.parents[1] / "prepare"))
    import prepare

    assert diagnose.MAIN_BUILD_ID == prepare.MAIN_BUILD_ID
    header = bytearray(0x48)
    header[:4] = b"NSO0"
    header[0x40:0x48] = bytes.fromhex(diagnose.MAIN_BUILD_ID)
    if kind == "other-version":
        header[0x40] ^= 0xFF
    if kind == "encrypted":
        header[:4] = b"????"
    if kind == "short":
        header = header[:4]
    for name in ("main", "sdk", "subsdk0"):
        (tmp_path / "exefs" / name).write_bytes(header)
    before = {p: p.read_bytes() for p in (tmp_path / "exefs").iterdir()}
    ok, report = diagnose.check_game(tmp_path)
    assert ok is valid
    assert str(tmp_path) not in report
    if valid:
        assert "Verification partielle" in report  # even an empty RomFS passes this structure/version check only
    assert {p: p.read_bytes() for p in before} == before


def test_missing_structure_reports_only_expected_names(tmp_path: Path) -> None:
    ok, report = diagnose.check_game(tmp_path)
    assert not ok and "exefs/main" in report and "romfs/" in report
    assert str(tmp_path) not in report


def test_cli_never_overwrites_existing_file(tmp_path: Path) -> None:
    log = tmp_path / "log with spaces.log"
    log.write_text(LOG, encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), str(log), "--out", str(log)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and "deja present" in result.stderr
    assert log.read_text(encoding="utf-8") == LOG


def test_cli_produces_report_from_bom_log(tmp_path: Path) -> None:
    log = tmp_path / "log with spaces.log"
    out = tmp_path / "report.txt"
    log.write_text(LOG, encoding="utf-8-sig")
    result = subprocess.run([sys.executable, str(SCRIPT), str(log), "--out", str(out)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "Image lente 1742" in out.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="requires the Windows cmd.exe interpreter")
def test_windows_collector_exports_existing_log_only(tmp_path: Path) -> None:
    port = tmp_path / "Copie C ñ"
    (port / "logs").mkdir(parents=True)
    log = port / "logs/mkw.log"
    log.write_text(LOG, encoding="utf-8")
    shutil.copy2(SCRIPT, port / SCRIPT.name)
    collector = SCRIPT.with_name("collect-diagnostic.cmd")
    shutil.copy2(collector, port / collector.name)
    environ = dict(os.environ, MKW_DIAG_PYTHON=sys.executable, MKW_DIAG_NO_PAUSE="1")
    result = subprocess.run(["cmd.exe", "/d", "/c", collector.name], cwd=port, env=environ,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    reports = list((port / "diagnostics").glob("*/fluidite.txt"))
    assert len(reports) == 1 and "Image lente 1742" in reports[0].read_text(encoding="utf-8")
    assert log.read_text(encoding="utf-8") == LOG
