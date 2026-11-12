"""End-to-end check of the MCP server, the way Claude uses it: start `studio mcp` over stdio and call the tools.

Without arguments it builds a throwaway library (a series without a kit) and runs the design loop:
read_poem -> save_design -> render_design -> get_design. Needs Chrome, Chromium or Edge.

    python tests/e2e_mcp.py

With a poem from a series that has a kit, it also runs the carousel loop (brief, slides, render, qa).
Point it at a COPY of your library, since it writes to the poem:

    STUDIO_ART=/path/to/copy-of-library python tests/e2e_mcp.py "<Series>/<Poem>"
"""
import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

EXPECTED = {"list_poems", "read_poem", "get_rules", "list_concepts", "write_brief", "set_slides", "render", "qa",
            "get_design", "save_design", "render_design"}


def text(res):
    return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


def throwaway_library():
    from studio.store import Store
    root = Path(tempfile.mkdtemp(prefix="studio-e2e-"))
    s = Store(root / "Poems", root / "cache")
    s.create_series("Night Letters", "Letters written at night.")
    p = s.create("Hold the Line", "Night Letters")
    s.save_text(p["id"], "Hold the Line", "Hold the line\nwhen they push.\nHold it longer.")
    return root, p["id"]


async def main(poem, out_dir, env):
    params = StdioServerParameters(command=sys.executable, args=["-m", "studio", "mcp"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        init = await s.initialize()
        print("server:", init.server_info.name, "| instructions:", bool(init.instructions))
        tools = {t.name for t in (await s.list_tools()).tools}
        assert EXPECTED <= tools, f"missing tools: {EXPECTED - tools}"
        print("tools:", ", ".join(sorted(tools)))

        async def call(name, **args):
            res = await s.call_tool(name, args)
            if res.is_error:
                raise SystemExit(f"{name} failed: {text(res)}")
            return res

        print("\n— list_poems\n" + text(await call("list_poems"))[:600])
        info = json.loads(text(await call("read_poem", poem=poem)))
        print("— read_poem:", info["id"], "| kit:", not info["art"].get("no_kit"))
        series = poem.split("/")[0]
        print("— get_rules:", len(text(await call("get_rules", series=series))), "chars")

        if not info["art"].get("no_kit"):
            concepts = text(await call("list_concepts", series=series))
            built = json.loads(concepts.split("\n\n# Catalogue")[0])["built"]
            assert built, "the kit has no concepts"
            print("— list_concepts:", ", ".join(c["id"] for c in built))
            print(text(await call("write_brief", poem=poem, brief=f"# {info['title']} — brief\n\nAn end-to-end test.\n")))
            bad = await s.call_tool("set_slides", {"poem": poem, "slides": [{"concept": "no-such-concept"}]})
            assert bad.is_error and "unknown concept" in text(bad), "set_slides should refuse unknown concepts"
            print(text(await call("set_slides", poem=poem, slides=[{"concept": c["id"]} for c in built[:2]])))
            res = await call("render", poem=poem)
            print("\n— render\n" + text(res)[:1200])
            imgs = [c for c in res.content if getattr(c, "type", "") == "image"]
            assert imgs, "render should return a picture"
            Path(out_dir, "render-preview.jpg").write_bytes(base64.b64decode(imgs[0].data))
            print("\n— qa\n" + text(await call("qa", poem=poem))[:1200])

        design = {"name": "Test card", "format": "45", "background": "#0C0E11", "elements": [
            {"type": "text", "text": "Hold the line", "font": "Archivo", "weight": 900, "stretch": 87.5, "size": 120,
             "case": "upper", "color": "#EEEAE2", "x": 88, "y": 200},
            {"type": "ellipse", "x": 500, "y": 120, "w": 500, "h": 500, "fill": "#DA291C"},
            {"type": "text", "text": "Hold the line", "font": "Archivo", "weight": 900, "stretch": 87.5, "size": 120,
             "case": "upper", "color": "#0C0E11", "x": 88, "y": 200, "clip": True},
            {"type": "shape", "kind": "star", "n": 5, "x": 88, "y": 700, "w": 200, "h": 200,
             "fill": {"type": "linear", "angle": 90, "stops": [{"c": "#DA291C", "p": 0}, {"c": "#EEEAE2", "p": 1}]}},
            {"type": "text", "role": "name", "text": "A. Poet", "font": "Archivo", "weight": 700, "size": 28,
             "tracking": 260, "case": "upper", "color": "#959AA2", "x": 88, "y": 1200}]}
        saved = text(await call("save_design", poem=poem, design=design))
        print("\n— save_design\n" + saved)
        slug = re.search(r"'([^']+)'", saved).group(1)
        res = await call("render_design", poem=poem, design=slug)
        print("— render_design\n" + text(res))
        pics = [c for c in res.content if getattr(c, "type", "") == "image"]
        assert len(pics) == 3, "render_design should return a picture per format"
        Path(out_dir, "design-preview.jpg").write_bytes(base64.b64decode(pics[0].data))
        assert '"Hold the line"' in text(await call("get_design", poem=poem, design=slug))
        print("\nall good; previews in", Path(out_dir).resolve())


if __name__ == "__main__":
    env = {k: v for k, v in os.environ.items()}
    tmp = None
    if len(sys.argv) > 1:
        poem = sys.argv[1]
    else:
        tmp, poem = throwaway_library()
        env.update(STUDIO_ART=str(tmp), STUDIO_CACHE=str(tmp / "cache"), STUDIO_CONFIG=str(tmp / "config.json"))
    try:
        asyncio.run(main(poem, sys.argv[2] if len(sys.argv) > 2 else tempfile.gettempdir(), env))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
