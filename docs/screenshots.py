#!/usr/bin/env python3
"""Regenerate docs/images/*.png from the demo data. Needs Playwright (pip install playwright; playwright install chromium).

usage: python3 docs/screenshots.py
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
PORT = 8765


def serve(folder):
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"], cwd=folder,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    return proc


async def shoot():
    from playwright.async_api import async_playwright
    sys.path.insert(0, str(ROOT / "scripts"))
    import demo_data
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    demo_data.make(work / "normal", "normal")
    demo_data.make(work / "outage", "outage")
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)   # CHROMIUM: path of a browser to use instead of the one Playwright installs
        url = f"http://127.0.0.1:{PORT}/"

        async def page_of(site, scheme="light", width=1280, height=760):
            proc = serve(site)
            ctx = await browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, locale="en-US", timezone_id="UTC")
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(700)
            return proc, ctx, page

        async def done(proc, ctx):
            await ctx.close()
            proc.terminate()
            proc.wait()

        proc, ctx, page = await page_of(work / "normal")
        await page.screenshot(path=OUT / "overview.png")                       # folded: everything on one screen
        await page.click("#toggleAll"); await page.wait_for_timeout(300)
        await page.hover(".comp .bars .bar:nth-child(60)"); await page.wait_for_timeout(200)
        await page.screenshot(path=OUT / "expanded.png", full_page=True)
        await page.click('[data-metric=latency]'); await page.wait_for_timeout(400)
        await page.hover(".comp svg.chart rect:nth-child(55)"); await page.wait_for_timeout(200)
        await page.screenshot(path=OUT / "latency.png", full_page=True)
        await page.click('[data-metric=speed]'); await page.wait_for_timeout(400)
        await page.click('#ranges button:has-text("7d")'); await page.wait_for_timeout(500)
        await page.screenshot(path=OUT / "speed.png")
        await done(proc, ctx)

        proc, ctx, page = await page_of(work / "normal", scheme="dark")
        await page.screenshot(path=OUT / "dark.png")
        await done(proc, ctx)

        proc, ctx, page = await page_of(work / "outage")
        await page.click('#ranges button:has-text("24h")'); await page.wait_for_timeout(500)
        await page.screenshot(path=OUT / "outage.png")
        await done(proc, ctx)

        proc, ctx, page = await page_of(work / "normal", width=390, height=800)
        await page.screenshot(path=OUT / "mobile.png")
        await done(proc, ctx)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(shoot())
    print("wrote", OUT)
