# PyInstaller spec: builds Studio (windowed app) and studio-cli (console, for MCP) into one folder.
#   pip install -e ".[app,build]"
#   pyinstaller packaging/studio.spec --noconfirm
# Output: dist/Studio/ (Windows, Linux) or dist/Studio.app (macOS).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICONS = os.path.join(ROOT, "studio", "static", "icons")
icon = os.path.join(ICONS, "studio.ico" if sys.platform == "win32" else "studio.icns")

hidden = (collect_submodules("studio") + collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli"))
          + ["fontTools.subset", "fontTools.ttLib", "fontTools.varLib.instancer", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
             "numpy",
             # a series' _kit/build.py may import more of the standard library than Studio itself does
             "base64", "csv", "colorsys", "math", "random", "textwrap", "hashlib", "zipfile", "argparse", "itertools", "functools", "statistics"])

a = Analysis([os.path.join(SPECPATH, "entry.py")], pathex=[ROOT],
             datas=[(os.path.join(ROOT, "studio", "static"), os.path.join("studio", "static"))],
             hiddenimports=hidden, excludes=["tkinter", "matplotlib", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
app = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Studio", console=False, icon=icon, upx=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="studio-cli", console=True, icon=icon, upx=False)
coll = COLLECT(app, cli, a.binaries, a.datas, name="Studio", upx=False)

if sys.platform == "darwin":
    BUNDLE(coll, name="Studio.app", icon=icon, bundle_identifier="io.github.theanarchox.studio",
           info_plist={"CFBundleDisplayName": "Studio", "NSHighResolutionCapable": True})
