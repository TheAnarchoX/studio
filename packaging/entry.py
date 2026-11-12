"""Entry point for the packaged executables (PyInstaller).

Studio(.exe) is the windowed app: without arguments it opens Studio.
studio-cli(.exe) is the console twin, for `studio-cli mcp` (Claude) and the other commands.
"""
import os
import sys

if sys.stdout is None or sys.stderr is None:      # the windowed app has no console; kits may still print
    sys.stdout = sys.stdout or open(os.devnull, "w", encoding="utf-8")
    sys.stderr = sys.stderr or open(os.devnull, "w", encoding="utf-8")

from studio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
