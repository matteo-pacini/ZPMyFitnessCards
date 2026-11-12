// scripts/card-coverage.js: where the end-to-end tests' coverage of the
// bundle lands in the card scripts, and the floor it checks.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { main } = require("../../scripts/card-coverage.js");
const { out } = require("../../scripts/build.js");

// Runs the script; returns its exit code and what it printed.
function run(args) {
  const printed = [];
  const { log, error } = console;
  console.log = console.error = (...parts) => printed.push(parts.join(" "));
  try {
    return { code: main(args), printed: printed.join("\n") };
  } finally {
    Object.assign(console, { log, error });
  }
}

test("a block the end-to-end tests did not run shows as the card script's lines", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "card-coverage-"));
  try {
    const bundle = fs.readFileSync(out, "utf8");
    const source = fs.readFileSync(path.join(__dirname, "../../src/cards/weight-card.js"), "utf8");
    // One method of weight-card.js, by its offsets in the bundle and its lines in the script.
    const method = "  _keepLogDay(day) {\n    this._logDay = day && day < this._today ? day : null;\n  }\n";
    const start = bundle.indexOf(method);
    const line = source.slice(0, source.indexOf(method)).split("\n").length;
    assert.ok(start > 0);
    const everything = { ranges: [{ startOffset: 0, endOffset: bundle.length, count: 1 }] };
    const notRun = { ranges: [{ startOffset: start, endOffset: start + method.length, count: 0 }] };
    const script = { url: "/metron/metron-cards.js", functions: [everything, notRun] };
    fs.writeFileSync(path.join(dir, "page.json"), JSON.stringify([script]));
    fs.writeFileSync(path.join(dir, "unit.lcov"), "");

    const report = run([dir, path.join(dir, "unit.lcov"), "--fail-under", "100"]);
    assert.equal(report.code, 1);
    const row = report.printed.split("\n").find((l) => l.startsWith("src/cards/weight-card.js"));
    assert.match(row, new RegExp(` ${line}-${line + 2}$`));
    assert.match(report.printed, /^src\/cards\/charts\.js +100\.0 +0\.0 +100\.0 *$/m);
    assert.match(report.printed, /under 100%\.$/);

    // A unit test that ran those lines makes up for the end-to-end tests.
    const lcov = `SF:src/cards/weight-card.js\n${[0, 1, 2].map((i) => `DA:${line + i},1`).join("\n")}\nend_of_record\n`;
    fs.writeFileSync(path.join(dir, "unit.lcov"), lcov);
    assert.equal(run([dir, path.join(dir, "unit.lcov"), "--fail-under", "100"]).code, 0);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
