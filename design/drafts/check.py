"""Checks a UX draft written by design/drafts/kit.js, in Chromium.

    nix develop -c python design/drafts/check.py <draft.html>

Fails on page errors, on a flow step whose target is missing (or, for typing,
is no input), on a diff mark that matches nothing, and on a page wider than
the window at desktop and phone widths.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROBLEMS = """() => {
  const out = [];
  const flows = JSON.parse(document.getElementById("flows").textContent);
  for (const [id, f] of Object.entries(flows)) f.steps.forEach((s, i) => {
    if (!s.target) return;
    const box = document.createElement("div");
    box.innerHTML = s.html + (s.overlay || "");
    const el = box.querySelector(s.target);
    const where = `${id} step ${i + 1}: ${s.target}`;
    if (!el) out.push(`${where} is missing`);
    else if (s.act === "type" && !el.matches("input, :has(input)")) out.push(`${where}: no input`);
  });
  for (const fig of document.querySelectorAll("figure[data-marks]"))
    for (const [sel] of JSON.parse(fig.dataset.marks))
      if (!fig.querySelector(sel))
        out.push(`${fig.closest("section").id} ${fig.firstElementChild.textContent}: no ${sel}`);
  return out;
}"""


def main(path):
    url = Path(path).resolve().as_uri()
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in (1100, 390):
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
            page.goto(url)
            page.wait_for_timeout(500)
            if width == 1100:
                problems.extend(page.evaluate(PROBLEMS))
            scroll = page.evaluate("document.documentElement.scrollWidth")
            if scroll > width:
                problems.append(f"{scroll}px wide at {width}px")
            page.close()
        browser.close()
    for problem in problems:
        print(problem)
    print("ok" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
