# PyInstaller build description. Run via:  python packaging/build.py
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)
NAME = "GoTournament"

datas = collect_data_files("gotourney")            # templates, styles, club list, fonts, icon
hidden = collect_submodules("gotourney") + ["waitress"]

a = Analysis([str(HERE / "launch.py")], datas=datas, hiddenimports=hidden,
             excludes=["pytest", "PyInstaller"], noarchive=False)
pyz = PYZ(a.pure)
icon = str(HERE / "icon.png")
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=icon,
          argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)

if sys.platform == "darwin":
    from gotourney import __version__
    app = BUNDLE(coll, name="Go Tournament.app", icon=icon, bundle_identifier="eu.go-tournament.gotourney",
                 info_plist={"CFBundleShortVersionString": __version__, "NSHighResolutionCapable": True})
