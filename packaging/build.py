"""Build the program for this operating system and pack it into one archive in dist/.

    python packaging/build.py

Needs:  pip install -e ".[build]"   (PyInstaller; Pillow converts the icon).
Windows and macOS programs can only be built on Windows and macOS (see .github/workflows/build.yml).
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT / "src"))
from gotourney import __version__  # noqa: E402

DOCS = [ROOT / "src/gotourney/data/docs/Quickstart.pdf", ROOT / "src/gotourney/data/docs/Schnellstart.pdf",
        ROOT / "Guide.pdf", ROOT / "Anleitung.pdf"]


def main() -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
                    str(ROOT / "packaging" / "gotourney.spec")], check=True)
    system = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "linux")
    machine = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    stage = DIST / f"GoTournament-{__version__}-{system}-{machine}"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    if system == "macos":
        # keep symlinks and permissions inside the .app: copy with ditto
        subprocess.run(["ditto", str(DIST / "Go Tournament.app"), str(stage / "Go Tournament.app")], check=True)
    else:
        shutil.copytree(DIST / "GoTournament", stage / "GoTournament", symlinks=True)
    for doc in DOCS:
        if doc.exists():
            shutil.copy2(doc, stage / doc.name)
    if system == "macos":
        archive = stage.parent / (stage.name + ".zip")      # not with_suffix: the version contains dots
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(stage), str(archive)], check=True)
    elif system == "windows":
        archive = Path(shutil.make_archive(str(stage), "zip", DIST, stage.name))
    else:
        archive = Path(shutil.make_archive(str(stage), "gztar", DIST, stage.name))
    print(f"\nBuilt {archive}")


if __name__ == "__main__":
    main()
