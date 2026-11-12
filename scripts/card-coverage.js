// How much of each card script the tests run: the card unit tests, the
// end-to-end tests, and both together, line by line.
//
//   node scripts/card-coverage.js <e2e-dir> <unit.lcov> [--fail-under <percent>]
//
// <e2e-dir> holds what tests/e2e wrote with METRON_CARD_COVERAGE set to it:
// Chromium's block coverage of the cards' bundle. <unit.lcov> is the card
// unit tests' coverage, from Node's test runner with its lcov reporter. With
// --fail-under, exits 1 when both together cover less of all the scripts.

const fs = require("node:fs");
const path = require("node:path");
const { out, sources } = require("./build.js");

const root = path.join(__dirname, "..");

// Where each script's code sits in the bundle, which holds each one as it is,
// after a line naming it.
function scriptsInBundle(bundle) {
  return sources.map((file) => {
    const name = path.relative(root, file);
    const code = fs.readFileSync(file, "utf8").trimEnd();
    const start = bundle.indexOf(`// ${name}\n`) + `// ${name}\n`.length;
    if (bundle.slice(start, start + code.length) !== code) {
      throw new Error(`${path.relative(root, out)} is out of date: run node scripts/build.js`);
    }
    return { name, code, start };
  });
}

// Which characters of the bundle any snapshot ran. Each function's first
// range is the whole function; the ones after it are blocks inside, whose
// count overrides the function's.
function ranInBundle(dir, length) {
  const ran = new Uint8Array(length);
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".json"))) {
    for (const script of JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"))) {
      const counts = new Int32Array(length).fill(-1);
      for (const fn of script.functions) {
        for (const r of fn.ranges) counts.fill(r.count, r.startOffset, Math.min(r.endOffset, length));
      }
      for (let i = 0; i < length; i++) if (counts[i] > 0) ran[i] = 1;
    }
  }
  return ran;
}

// The lines each script's unit tests ran, from lcov, by script name.
function unitLines(lcov) {
  const lines = {};
  let current = null;
  for (const line of fs.readFileSync(lcov, "utf8").split("\n")) {
    if (line.startsWith("SF:")) {
      current = path.relative(root, path.resolve(root, line.slice(3)));
      lines[current] ??= new Set();
    } else if (line.startsWith("DA:") && current) {
      const [n, count] = line.slice(3).split(",").map(Number);
      if (count > 0) lines[current].add(n);
    }
  }
  return lines;
}

// A script's lines, each with whether the end-to-end tests ran it: a line
// with code counts as run if any of its code ran.
function e2eLines(script, ran) {
  const result = [];
  let offset = script.start;
  for (const text of script.code.split("\n")) {
    let code = false;
    let hit = false;
    for (let i = 0; i < text.length; i++) {
      if (text[i].trim()) {
        code = true;
        if (ran[offset + i]) hit = true;
      }
    }
    result.push({ code, hit });
    offset += text.length + 1;
  }
  return result;
}

const percent = (n, total) => (total ? (100 * n) / total : 100).toFixed(1);

// Runs of line numbers, as "3-7 12".
function runs(numbers) {
  const parts = [];
  for (let i = 0; i < numbers.length; i++) {
    let j = i;
    while (j + 1 < numbers.length && numbers[j + 1] === numbers[j] + 1) j++;
    parts.push(i === j ? `${numbers[i]}` : `${numbers[i]}-${numbers[j]}`);
    i = j;
  }
  return parts.join(" ");
}

function main(args) {
  const [dir, lcov] = args;
  const at = args.indexOf("--fail-under");
  const floor = at >= 0 ? Number(args[at + 1]) : null;
  if (!dir || !lcov || (at >= 0 && Number.isNaN(floor))) {
    console.error("usage: node scripts/card-coverage.js <e2e-dir> <unit.lcov> [--fail-under <percent>]");
    return 2;
  }
  const bundle = fs.readFileSync(out, "utf8");
  const ran = ranInBundle(dir, bundle.length);
  const unit = unitLines(lcov);
  const totals = { lines: 0, e2e: 0, unit: 0, both: 0 };
  console.log("file".padEnd(34), "e2e %".padStart(7), "unit %".padStart(7), "both %".padStart(7), " lines neither ran");
  for (const script of scriptsInBundle(bundle)) {
    const lines = e2eLines(script, ran);
    const byUnit = unit[script.name] ?? new Set();
    const counted = { lines: 0, e2e: 0, unit: 0, both: 0 };
    const missed = [];
    lines.forEach(({ code, hit }, i) => {
      if (!code) return;
      const unitHit = byUnit.has(i + 1);
      counted.lines++;
      if (hit) counted.e2e++;
      if (unitHit) counted.unit++;
      if (hit || unitHit) counted.both++;
      else missed.push(i + 1);
    });
    for (const key of Object.keys(totals)) totals[key] += counted[key];
    console.log(
      script.name.padEnd(34),
      percent(counted.e2e, counted.lines).padStart(7),
      percent(counted.unit, counted.lines).padStart(7),
      percent(counted.both, counted.lines).padStart(7),
      ` ${runs(missed)}`,
    );
  }
  const both = Number(percent(totals.both, totals.lines));
  console.log(
    "all scripts".padEnd(34),
    percent(totals.e2e, totals.lines).padStart(7),
    percent(totals.unit, totals.lines).padStart(7),
    percent(totals.both, totals.lines).padStart(7),
  );
  if (floor != null && both < floor) {
    console.error(`The tests run ${both}% of the cards' lines, under ${floor}%.`);
    return 1;
  }
  return 0;
}

module.exports = { main };

if (require.main === module) process.exit(main(process.argv.slice(2)));
