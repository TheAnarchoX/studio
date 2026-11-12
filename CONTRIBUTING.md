# Contributing

Thanks for helping. Studio is small on purpose: plain files, a stdlib web server, plain JavaScript, no build step.

## Set up

```bash
git clone https://github.com/TheAnarchoX/studio.git
cd studio
python -m venv .venv
.venv/bin/pip install -e ".[app]"        # Windows: .venv\Scripts\pip install -e ".[app]"
.venv/bin/studio web --open
```

Point it at a test library so you don't touch your own poems:

```bash
STUDIO_ART=/tmp/studio-test STUDIO_CONFIG=/tmp/studio-test/config.json STUDIO_PORT=4748 .venv/bin/studio web --open
```

## Before a pull request

- `python -m unittest discover tests` passes.
- `python tests/e2e_mcp.py` passes if you touched the MCP server, rendering or designs.
- Front-end changes are checked in the browser, in all three formats when it's the Design tab.
- No personal paths, names or settings in code: those belong in the user's config file.

## Where things are

| | |
|---|---|
| `studio/store.py` | the library folder as the database |
| `studio/kit.py` | runs a series' `_kit/build.py` |
| `studio/qa.py` | pixel QA on the renders |
| `studio/metrics.py` | ink metrics from the font files |
| `studio/shoot.py` | design exports with headless Chrome |
| `studio/web.py` | the local web server and its JSON API |
| `studio/mcp_server.py` | the MCP tools |
| `studio/desktop.py` | the app window and launchers |
| `studio/config.py` | settings |
| `studio/static/` | the front end: `app.js` (pages), `editor.js` (Design tab), `design-core.js` (the renderer shared with exports) |

## Rebuilding the vendored editor

The book editor runs on ProseMirror, bundled into one file, `studio/static/vendor/prosemirror.js`. Rebuild it only when you add an export to `tools/vendor-entry.js` or change a version in `tools/package.json`:

```bash
cd tools
npm ci
node build_vendor.mjs
```

The output is committed, so Studio never needs Node at runtime. The build is deterministic: rebuilding without changes leaves the file untouched.

## Reporting bugs

Open an issue with what you did, what you expected and what happened, plus your OS and `studio version`.
Screenshots help for anything visual.
