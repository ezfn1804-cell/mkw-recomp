"""Export numeric frame timings, or check a local decrypted dump's version, without sharing game files.

Why: a Windows tester can return useful stutter measurements without uploading paths, memory dumps or assets.
This standalone standard-library tool only reads files. Timings include menus/loading; worst frames are samples,
not a complete per-frame trace. Texture/ASTC/replay measurements may overlap and must not be added together.

Usage: python diagnose.py LOG [--out REPORT.txt]
       python diagnose.py --check-game GAME_FOLDER
"""

import argparse
import re
import sys
from pathlib import Path

# Same version gate as tools/prepare/prepare.py; this check never prepares or modifies the game.
MAIN_BUILD_ID = "9e244438c3d8ef1c"
NUMBER = r"\d+(?:\.\d+)?"
PERIOD = re.compile(
    rf"^\[host\] frametime: (60 s|exit): (\d+) frames in ({NUMBER}) s, mean ({NUMBER}) fps, "
    rf"1% low ({NUMBER}) fps, over 25 ms (\d+), 50 ms (\d+), 100 ms (\d+)$"
)
WORST = re.compile(
    rf"^\[host\] frametime:   worst frame (\d+): ({NUMBER}) ms; pipeline build ({NUMBER}), "
    rf"texture upload ({NUMBER}) \(astc ({NUMBER})\), replay ({NUMBER}), "
    rf"fence/present wait ({NUMBER}), pacing ({NUMBER})$"
)
SLOW = re.compile(
    rf"^\[host\] perf: slow frame (\d+): ({NUMBER}) ms; blocked pipeline ({NUMBER}) texture ({NUMBER}) "
    rf"astc ({NUMBER}) fence ({NUMBER}) pacing ({NUMBER})$"
)
WINDOW = re.compile(rf"^\[host\] perf: frame (\d+): interval avg ({NUMBER}) ms max ({NUMBER}) ms(?:[;\s]|$)")
GPU = re.compile(rf"^\[host\] perf: frame (\d+): gpu avg ({NUMBER}) ms(?:\s|$)")
SPEED = re.compile(
    rf"^\[host\] game: speed ({NUMBER})x over ({NUMBER}) s \((\d+) frames, (\d+) interval changes"
)
SUBMIT_ERROR = re.compile(r"^FATAL: vk: vkQueueSubmit2 of value (\d+) failed \((-?\d+)\)$")
INVALID_GPU_PC = re.compile(
    r"^\[host\] vk: device fault: instruction pointer invalid at 0x[0-9a-fA-F]+ \(precision 0x[0-9a-fA-F]+\)$"
)


def frame_report(text: str) -> str:
    """Whitelist measured numbers; never echo an unrecognised log line or its suffix."""
    rows = []
    for line in text.splitlines():
        if m := PERIOD.fullmatch(line):
            tag, frames, seconds, fps, low, over25, over50, over100 = m.groups()
            rows.append(f"Periode {tag}: {frames} images, {seconds} s; moyenne {fps} fps; "
                        f"indicateur 1% low du moteur {low} fps; >25 ms {over25}, >50 ms {over50}, >100 ms {over100}.")
        elif m := WORST.fullmatch(line):
            frame, total, pipeline, texture, astc, replay, wait, pacing = m.groups()
            rows.append(f"Image lente {frame}: {total} ms; pipeline {pipeline}, textures {texture} "
                        f"(ASTC {astc}), replay {replay}, attente GPU/presentation {wait}, cadence {pacing} ms.")
        elif m := SLOW.fullmatch(line):
            frame, total, pipeline, texture, astc, fence, pacing = m.groups()
            rows.append(f"Pic trace {frame}: {total} ms; pipeline {pipeline}, textures {texture} "
                        f"(ASTC {astc}), fence {fence}, cadence {pacing} ms.")
        elif m := WINDOW.match(line):
            frame, avg, maximum = m.groups()
            rows.append(f"Fenetre de 60 images finissant a {frame}: moyenne {avg} ms, maximum {maximum} ms.")
        elif m := GPU.match(line):
            frame, avg = m.groups()
            rows.append(f"GPU, fenetre finissant a {frame}: moyenne {avg} ms.")
        elif m := SPEED.match(line):
            speed, seconds, frames, changes = m.groups()
            rows.append(f"Vitesse du jeu: {speed}x sur {seconds} s ({frames} images, {changes} changements de cadence).")
        elif m := SUBMIT_ERROR.fullmatch(line):
            value, code = m.groups()
            label = " (VK_ERROR_DEVICE_LOST)" if int(code) == -4 else ""
            rows.append(f"Echec de soumission Vulkan: valeur {value}, code {code}{label}.")
        elif INVALID_GPU_PC.fullmatch(line):
            rows.append("Faute GPU: pointeur d'instruction invalide signale par le pilote (adresse omise).")
    if not rows:
        raise ValueError("Aucune mesure reconnue. Utilisez un log de partie, avec MKW_TRACE=perf, puis quittez normalement.")
    header = (
        "Diagnostic de fluidite — mesures et erreurs reconnues\n"
        "Menus et chargements inclus. Les images lentes sont des echantillons, pas toutes les images.\n"
        "Les temps textures/ASTC/replay peuvent se recouvrir : ne pas les additionner.\n"
        "Les percentiles des moyennes par 60 images ne sont pas des percentiles par image.\n"
    )
    return header + "\n".join(rows) + "\n"


def check_game(root: Path) -> tuple[bool, str]:
    """Check structure and the first 72 bytes of main; not the completeness/integrity of the dump."""
    required = ("exefs/main", "exefs/sdk", "exefs/subsdk0")
    missing = [name for name in required if not (root / name).is_file()]
    if not (root / "romfs").is_dir():
        missing.append("romfs/")
    if missing:
        return False, "Structure incomplete : " + ", ".join(missing) + ".\n"
    with (root / "exefs/main").open("rb") as f:
        header = f.read(0x48)
    if len(header) != 0x48 or header[:4] != b"NSO0":
        return False, "exefs/main : en-tete NSO dechiffre absent ou tronque.\n"
    if header[0x40:0x48].hex() != MAIN_BUILD_ID:
        return False, "Version non reconnue : ce port attend Mario Kart World 1.0.0.\n"
    return True, ("Structure attendue et version 1.0.0 reconnues.\n"
                  "Verification partielle : contenu RomFS, autres modules et fonctionnement du jeu non valides.\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log", type=Path, nargs="?")
    ap.add_argument("--check-game", type=Path, metavar="DIR")
    ap.add_argument("--out", type=Path, help="create a new report; an existing file is never overwritten")
    args = ap.parse_args()
    if (args.log is None) == (args.check_game is None) or (args.check_game and args.out):
        ap.error("Indiquez un log [--out NOUVEAU_FICHIER] ou --check-game DOSSIER.")
    try:
        if args.check_game is not None:
            ok, report = check_game(args.check_game)
            sys.stdout.write(report)
            return 0 if ok else 1
        report = frame_report(args.log.read_text(encoding="utf-8-sig", errors="replace"))
        if args.out:
            with args.out.open("x", encoding="utf-8") as f:
                f.write(report)
        else:
            sys.stdout.write(report)
    except FileExistsError:
        print("Rapport deja present : choisissez un nouveau nom avec --out.", file=sys.stderr)
        return 2
    except OSError:
        print("Lecture/ecriture impossible : verifiez le fichier et les droits locaux.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
