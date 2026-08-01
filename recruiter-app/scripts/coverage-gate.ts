#!/usr/bin/env bun
// FE-T1 frontend coverage gate (no-regression ratchet).
//
// WHY a script instead of bunfig `[test] coverageThreshold`:
//   bun 1.3.10 PRINTS the coverage table but does NOT fail the process when
//   coverage is below `coverageThreshold` (verified locally: a run at 37% lines
//   against a 0.90 threshold still exits 0 — both the single-number and the
//   { line, function } object forms). So the threshold in bunfig.toml is
//   documentation of INTENT only; THIS script is the enforced gate. If/when a
//   future bun makes coverageThreshold fail the run, the bunfig value takes over
//   and this script can be retired.
//
// It runs the same `bun test --coverage` the dev script uses, parses the
// "All files" row of the text reporter (which bun writes to STDERR), and exits
// non-zero if line OR function coverage dips below the floors below. The floors
// sit just under the measured baseline so the gate blocks regressions without
// flaking on rounding.

const MIN_LINES = 87.0;
const MIN_FUNCS = 82.0;

const proc = Bun.spawnSync(['bun', 'test', '--coverage', '--coverage-reporter=text'], {
  stdout: 'pipe',
  stderr: 'pipe',
});

const out = new TextDecoder().decode(proc.stdout);
const err = new TextDecoder().decode(proc.stderr);
const combined = `${err}\n${out}`;

// The suite itself must be green before we even look at coverage.
if (proc.exitCode !== 0) {
  process.stderr.write(combined);
  console.error(`\ncoverage-gate: test suite failed (exit ${proc.exitCode})`);
  process.exit(proc.exitCode ?? 1);
}

// Row shape: "All files | <funcs> | <lines> |"
const row = combined.split('\n').find((l) => l.trim().startsWith('All files'));
if (!row) {
  process.stderr.write(combined);
  console.error('\ncoverage-gate: could not find the "All files" coverage row');
  process.exit(1);
}

const cols = row.split('|').map((c) => c.trim());
const funcs = Number.parseFloat(cols[1] ?? '');
const lines = Number.parseFloat(cols[2] ?? '');
if (!Number.isFinite(funcs) || !Number.isFinite(lines)) {
  console.error(`coverage-gate: failed to parse coverage from: ${row}`);
  process.exit(1);
}

// Report on stderr (console.error is in biome's noConsole allow-list, and a CI
// gate's status line belongs on stderr anyway).
console.error(
  `coverage-gate: lines=${lines.toFixed(2)}% (floor ${MIN_LINES}%), ` +
    `funcs=${funcs.toFixed(2)}% (floor ${MIN_FUNCS}%)`,
);

let failed = false;
if (lines < MIN_LINES) {
  console.error(`coverage-gate: FAIL line coverage ${lines.toFixed(2)}% < ${MIN_LINES}%`);
  failed = true;
}
if (funcs < MIN_FUNCS) {
  console.error(`coverage-gate: FAIL function coverage ${funcs.toFixed(2)}% < ${MIN_FUNCS}%`);
  failed = true;
}

process.exit(failed ? 1 : 0);
