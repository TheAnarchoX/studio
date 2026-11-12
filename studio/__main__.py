"""Studio — a local studio for poems and their artwork.

  studio                  open Studio (its own window; see open_with in settings)
  studio app              the same
  studio web [--open]     run only the local server (http://127.0.0.1:4747), optionally opening the browser
  studio mcp              the MCP server for Claude, over stdio (Claude starts this itself)
  studio install [--desktop]   add Studio to the Start menu / Applications / app launcher, with its icon
  studio uninstall        remove those launchers
  studio config [key=value ...]   show or change settings (library, signature, port, chrome, open_with)
  studio version
"""
import sys


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "app"
    if cmd == "app":
        from .desktop import run_app
        run_app()
    elif cmd == "web":
        from .web import serve
        serve(open_browser="--open" in a)
    elif cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
    elif cmd == "install":
        from .desktop import install
        for p in install(desktop="--desktop" in a):
            print("added", p)
        if sys.platform == "win32":
            print("Open Studio from the Start menu, then right-click its taskbar icon > Pin to taskbar.")
    elif cmd == "uninstall":
        from .desktop import uninstall
        for p in uninstall():
            print("removed", p)
    elif cmd == "config":
        from . import config
        if len(a) > 1:
            config.save(dict(kv.split("=", 1) for kv in a[1:] if "=" in kv))
        print(config.CONFIG_FILE)
        for k, v in config.load().items():
            print(f"  {k} = {v}")
    elif cmd in ("version", "--version"):
        from . import __version__
        print(__version__)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
