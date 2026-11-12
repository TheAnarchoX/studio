# PyInstaller spec: builds Studio (windowed app) and studio-cli (console, for MCP) into one folder.
#   pip install -e ".[app,build]"
#   pyinstaller packaging/studio.spec --noconfirm
# Output: dist/Studio/ (Windows, Linux) or dist/Studio.app (macOS).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICONS = os.path.join(ROOT, "studio", "static", "icons")
icon = os.path.join(ICONS, "studio.ico" if sys.platform == "win32" else "studio.icns")

# Books: studio.* is collected whole above (routes_books, books, manuscript, book_import, book_export are named here
# too, so a rename shows up as a build error). manuscript.py imports markdown_it and the mdit_py_plugins attrs,
# colon_fence and footnote plugins; book_import imports mammoth lazily (which a static scan can miss); book_export
# imports docx. Collecting each package whole also takes their sub-packages.
books = (["studio.routes_books", "studio.books", "studio.manuscript", "studio.book_import", "studio.book_export"]
         + collect_submodules("markdown_it") + collect_submodules("mdit_py_plugins")
         + collect_submodules("mammoth") + collect_submodules("docx"))
hidden = (collect_submodules("studio") + books + ["brotli"] + collect_submodules("mcp", filter=lambda n: not n.startswith("mcp.cli"))
          + ["fontTools.subset", "fontTools.ttLib", "fontTools.varLib.instancer", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
             "numpy",
             # a series' _kit/build.py may import more of the standard library than Studio itself does
             "base64", "csv", "colorsys", "math", "random", "textwrap", "hashlib", "zipfile", "argparse", "itertools", "functools", "statistics"])

a = Analysis([os.path.join(SPECPATH, "entry.py")], pathex=[ROOT],
             datas=[(os.path.join(ROOT, "studio", "static"), os.path.join("studio", "static"))]
                   + collect_data_files("docx"),   # python-docx's default.docx and style templates; mammoth has no data files
             hiddenimports=hidden, excludes=["tkinter", "matplotlib", "IPython", "pytest"], noarchive=False)
# collect_submodules("studio") covers routes_update/styles/making, updater, fonts, styles, home, examples, making;
# datas holds studio/static whole (fonts, styles, icons, scripts).
pyz = PYZ(a.pure)
app = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Studio", console=False, icon=icon, upx=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="studio-cli", console=True, icon=icon, upx=False)
coll = COLLECT(app, cli, a.binaries, a.datas, name="Studio", upx=False)

if sys.platform == "darwin":
    BUNDLE(coll, name="Studio.app", icon=icon, bundle_identifier="io.github.theanarchox.studio",
           info_plist={"CFBundleDisplayName": "Studio", "NSHighResolutionCapable": True})
