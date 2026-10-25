"""Walk the real web app in a headless browser, mode by mode, the way a visitor does: upload, choose who is
recast, add pictures, wait for the words, make a preview, and optionally render, re-roll or cancel.

    python3 tools/e2e_browser.py CASES.json OUT_DIR [--base http://127.0.0.1:5180] [--only NAME ...]

CASES.json is a list of cases (media paths stay outside git):

    {"name": "duo", "mode": "recast", "clip": "a.mp4", "picks": [1, 2], "length": 5,
     "characters": ["left.png", "right.png"], "place": "keep",          # keep | character | image | describe
     "place_text": "...", "place_image": "room.png",
     "style": "Anime Cel",                                              # restyle
     "outfits": {"2": {"text": "a red jacket", "image": "jacket.png"}},  # Restage: per chosen person; optional place
     "draft": false,                   # over 5 s: approve a draft first; then "render", "reroll" apply
     "render": true, "reroll": false, "cancel": false}

Writes OUT_DIR/report.json (one entry per case: what happened at each step, the job's final state, page
errors) and a screenshot per step. Needs Playwright with Chromium (`pip install playwright`,
`playwright install chromium`).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

WORDS_TIMEOUT = 300_000  # ms: the vision model writes a picture's words in about a minute; the GPU may be busy
PEOPLE_TIMEOUT = 300_000
PREVIEW_TIMEOUT = 1_500_000
RENDER_TIMEOUT = 5_400_000
PLACES = {"image": "Use an image", "describe": "Describe a place"}


class Step:
    def __init__(self, page: Page, out: Path, log: list):
        self.page, self.out, self.log = page, out, log

    def __call__(self, name: str, **info) -> None:
        shot = self.out / f"{len(self.log):02d}_{name}.png"
        self.page.screenshot(path=str(shot), full_page=True)
        bad = [t for t in self.page.locator(".text-bad").all_inner_texts() if t.strip()]
        self.log.append({"step": name, "t": round(time.time()), "screenshot": shot.name, **info,
                         **({"errors_shown": bad} if bad else {})})
        print(f"  {name} {info or ''}{' ERRORS: ' + str(bad) if bad else ''}", flush=True)


def wait_words(page: Page, count: int) -> list[str]:
    """Until no box is still being written, and `count` word boxes exist; returns their words."""
    boxes = page.locator("input[placeholder^='e.g.']")
    page.wait_for_function(
        f"() => !document.querySelector('[aria-busy=true]') && document.querySelectorAll(\"input[placeholder^='e.g.']\").length >= {count}",
        timeout=WORDS_TIMEOUT)
    return [boxes.nth(i).input_value() for i in range(boxes.count())]


def upload(page: Page, label: str, path: str) -> None:
    """Into the first drop zone with this label; waits until it is replaced by the picture."""
    zones = page.locator(f"button[aria-label='{label}']")
    before = zones.count()
    zones.first.locator("input[type=file]").set_input_files(path)
    page.wait_for_function(f"() => document.querySelectorAll(\"button[aria-label='{label}']\").length < {before}",
                           timeout=180_000)


def fill_place(page: Page, case: dict, two: bool) -> None:
    mode = case.get("place", "keep")
    if mode == "keep":
        return
    if case["mode"] == "recast":
        page.get_by_role("button", name=re.compile(r"^Place")).click()
    label = {"character": "Left character's place" if two else "My character's place", **PLACES}[mode]
    page.get_by_role("button", name=label, exact=True).click()
    if mode == "describe":
        page.locator("input[placeholder^='e.g. a neon']").fill(case["place_text"])
    elif mode == "image":
        upload(page, "Place image", case["place_image"])


def run_case(page: Page, base: str, case: dict, out: Path) -> dict:
    log: list = []
    step = Step(page, out, log)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    result: dict = {"name": case["name"], "steps": log, "page_errors": errors}
    try:
        page.goto(f"{base}/create?mode={case['mode']}")
        page.locator("input[type=file]").first.set_input_files(case["clip"])
        page.get_by_role("button", name="Use a different clip").wait_for(timeout=180_000)
        page.check("#consent")
        if case["mode"] == "recast":
            page.wait_for_selector("text=/Tap to choose|Tap who to replace|We found one performer|couldn't/",
                                   timeout=PEOPLE_TIMEOUT)
            # the numbered buttons appear only once the picker has read every outline in the browser
            page.wait_for_function("() => document.querySelectorAll(\"button[aria-label^='Person ']\").length > 0"
                                   " || document.body.innerText.includes(\"couldn't\")", timeout=60_000)
            people = page.locator("button[aria-label^='Person ']")
            found = people.count()
            if case.get("picks") is not None:
                for k in range(found):
                    b = people.nth(k)
                    pid = int(re.match(r"Person (\d+)", b.get_attribute("aria-label")).group(1))
                    if (pid in case["picks"]) != (b.get_attribute("aria-pressed") == "true"):
                        b.click()
            chosen = [int(re.match(r"Person (\d+)", people.nth(k).get_attribute("aria-label")).group(1))
                      for k in range(found) if people.nth(k).get_attribute("aria-pressed") == "true"]
            step("people", found=found, chosen=chosen)
        if case.get("length", 5) != 5:  # seconds, on the slider
            page.get_by_label("Seconds of the clip to use").fill(str(case["length"]))
        page.get_by_role("button", name="Continue").click()

        two = case["mode"] == "recast" and len(case.get("characters", [])) == 2
        if case["mode"] == "recast":
            for path in case["characters"]:
                upload(page, "Character image", path)
            words = wait_words(page, len(case["characters"]))
            step("characters", words=words)
            fill_place(page, case, two)
        elif case["mode"] == "restyle":
            page.get_by_role("button", name=case["style"], exact=True).click()
        else:  # Restage: what each chosen person now wears, then an optional new place
            for pid, o in (case.get("outfits") or {}).items():
                group = page.get_by_role("group", name=f"Outfit for person {pid}")
                if o.get("image"):
                    group.locator("input[type=file]").set_input_files(o["image"])
                    group.locator("button[aria-label='Remove'], img[alt='Outfit image']").first.wait_for(timeout=180_000)
                    page.wait_for_function("() => !document.querySelector('[aria-busy=true]')", timeout=WORDS_TIMEOUT)
                    if o.get("text"):
                        group.locator("input[placeholder^='e.g.']").fill(o["text"])
                else:
                    group.get_by_label("What they wear now").fill(o["text"])
            step("outfits")
            if case.get("place", "keep") != "keep":
                page.get_by_role("button", name=re.compile(r"^Place")).click()
                fill_place(page, {**case, "mode": "swap"}, False)
        step("choices")
        if not case.get("draft"):  # the default: straight to the video, nothing to approve
            page.get_by_role("button", name=re.compile(r"^Make the video")).click()
            page.wait_for_url(re.compile(r"/jobs/"), timeout=120_000)
            result["job"] = page.url.rstrip("/").rsplit("/", 1)[-1]
            page.wait_for_timeout(15_000)
            step("making")
        else:  # over 5 s: a draft (the first 5 s, or the start picture) to approve first
            page.get_by_label(re.compile(r"^(Make a 5 s draft first|Check the start picture first)")).check()
            page.get_by_role("button", name=re.compile(r"^Make the (draft|start picture)")).click()
            page.wait_for_selector("text=Does this look right?", timeout=120_000)
            page.wait_for_timeout(15_000)
            step("preview_waiting")  # what the visitor sees while the draft is made
            try:  # and once the GPU is on it, if the page shows steps (the clip's place)
                page.wait_for_function("() => /step \\d of/i.test(document.body.innerText)", timeout=600_000)
                step("preview_rendering")
            except Exception:
                pass

            def preview_done(label: str) -> bool:
                page.wait_for_function(
                    "() => [...document.querySelectorAll('button')].some(b => /^(Render video|Keep this video)/.test(b.textContent) && !b.disabled)"
                    " || document.body.innerText.includes(\"didn't finish\") || !!document.querySelector('.text-bad')",
                    timeout=PREVIEW_TIMEOUT)
                ok = page.evaluate("() => [...document.querySelectorAll('button')].some(b => /^(Render video|Keep this video)/.test(b.textContent) && !b.disabled)")
                step(label, ok=ok, text=page.locator("section").first.inner_text()[:1500])
                return ok

            if not preview_done("preview"):
                result["outcome"] = "preview failed"
                return result
            if case.get("reroll"):
                page.get_by_role("button", name="Try another version").click()
                page.wait_for_timeout(2000)
                if not preview_done("preview_again"):
                    result["outcome"] = "re-roll failed"
                    return result
            result["job"] = page.request.get(f"{base}/api/jobs").json()[0]["id"]
            if not case.get("render"):
                result["outcome"] = "preview ok"
                return result
            page.get_by_role("button", name=re.compile(r"^(Render video|Keep this video)")).click()
            page.wait_for_url(re.compile(r"/jobs/"), timeout=60_000)
        if case.get("cancel"):
            page.wait_for_timeout(20_000)
            page.get_by_role("button", name="Cancel and refund").click()
            page.wait_for_selector("text=/refunded|Cancelled/", timeout=120_000)
        else:
            page.wait_for_selector("text=/Download video|Didn't finish|Cancelled/", timeout=RENDER_TIMEOUT)
        final = page.request.get(f"{base}/api/jobs/{result['job']}").json()
        step("result", state=final["state"], error=final.get("error"))
        result["outcome"] = final["state"]
        result["final"] = {k: final.get(k) for k in ("state", "error", "result", "cost_seconds", "title")}
    except Exception as e:  # one case failing must not stop the rest
        result["outcome"] = f"error: {type(e).__name__}: {str(e).splitlines()[0][:300]}"
        try:
            step("error")
        except Exception:
            pass
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("out")
    ap.add_argument("--base", default="http://127.0.0.1:5180")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    cases = [c for c in json.loads(Path(a.cases).read_text()) if not a.only or c["name"] in a.only]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for case in cases:
            print(case["name"], flush=True)
            d = out / case["name"]
            d.mkdir(exist_ok=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            report[case["name"]] = run_case(page, a.base.rstrip("/"), case, d)
            print(" ->", report[case["name"]]["outcome"], flush=True)
            page.close()
            report_path.write_text(json.dumps(report, indent=1))
        browser.close()
    bad = [n for n, r in report.items() if r["outcome"] not in ("preview ok", "done", "cancelled")]
    print("failed:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
