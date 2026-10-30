# CLAUDE.md

Behavioral guidelines plus SwiftCut project protocol. Read AGENTS.md
too (upstream conventions: PEP8, 79-char lines, pixi tasks). Where
this file and AGENTS.md conflict, this file wins.

**Tradeoff:** These guidelines bias toward caution over speed. For
trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If uncertain and the task defines a DEFAULT WHEN UNCERTAIN, apply it
  and record the decision in your report. If no default exists and the
  ambiguity is material, stop and ask. Never guess creatively.

Process defaults when a task does not say otherwise: do every task
listed, in the order given (or dependency order if you state why),
one conventional commit per task on the current branch, and proceed
without waiting for confirmation. A check you cannot perform in this
environment is done in the closest available form and marked
NEEDS-OWNER in the report; it is never a reason to stop.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?"
If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it; don't delete it.
- Remove imports/variables/functions that YOUR changes made unused.

The test: every changed line traces directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

- "Add validation" → write tests for invalid inputs, make them pass.
- "Fix the bug" → write a test that reproduces it, make it pass.
- "Refactor X" → tests pass before and after.

For multi-step tas, state a brief plan: step → verify: check.

## 5. Graphify

The knowledge graph lives at graphify-out/ (god nodes, communities,
cross-file relationships).
- FIRST action on any task: `graphify query "<question>"` for the
  modules, call paths and tests involved. `graphify path "<A>" "<B>"`
  for relationships, `graphify explain "<concept>"` for a focused
  concept. Cite the result in your plan.
- graphify-out/wiki/index.md for broad navigation; GRAPH_REPORT.md
  only for architecture review or when query/path/explain fall short.
- LAST action after the final commit: `graphify update .`
- graphify-out/ is gitignored; never commit it.

## 6. Strict Boss (non-trivial tasks)

You are the lead, not the implementer. Decompose into work packages
with acceptance criteria; delegate to subagents (VoltAgent: debugger,
refactoring-specialist, python-pro, performance-engineer; cavecraft
haiku reviewers for cheap first-pass diff review). Every delivery must
carry evidence: the diff, the exact test command and its output, and
what was NOT verified. Reject by default with file:line reasons;
re-dispatch with the rejection attached; max 3 rounds, then ESCALATE.
Approve only what you verified yourself: run the suite, run the grep
gates, read the diff.
Trivial tasks (a default value, a label, a sign flip): skip the boss
layer, keep Graphify and tests.

## 7. Protected (never modify unless the task explicitly allows it)

- machine/driver/ruida/** (driver, client, encoder, protocol,
  transport, server, simulator, fixtures, tests)
- pipeline job path: intent_builder aggregate assembly, build_rd_bytes,
  send_job, export .rd
- jog panel behavior: hold-jog + safety releases, Home, Go Scale, Cut
  Scale + confirmation, start-corner selector, X/Y readout
- mm/s units everywhere; Min/Max power fields; Start/Pause/Stop
- layer/step system; Swift Cut theme + layout tokens (docs/design/)
- MOTION_AUDIT.md invariants (stop-resync, busy interlock)
Gate before approval: `git diff --stat` shows nothing under those
paths unless the task allowed it.

## 8. Source of truth for protocol questions

1. tests/machine/driver/ruida/fixtures/rdworks_reference.rd (real
   controller output). Wins every conflict.
2. docs/reference/rdcam_*.md (RDCAM.dll decompile: opcodes, parameter
   IDs, USB open sequence), process-ordering audit, MOTION_AUDIT.md.
3. external/meerk40t (MIT, read-only reference).
4. Community docs.
Never invent opcodes or byte layouts.

## 9. Invariants

- Units: model stores mm/min, UI shows mm/s, encoder emits µm/s.
  Exactly ONE conversion site per value path.
- Exactly ONE axis-direction mapping site (jog_widget._jog_deltas).
  Corner pre-positioning and Go/Cut Scale derive from it.
- Start position: jobs use D8 12 (current head position); the corner
  selector pre-moves the head, never translates geometry.
- UDP frames: swizzle then 16-bit sum prefix. USB/serial: swizzle,
  no prefix. Chunks ≤1000 bytes on command boundaries, ACK-paced.

## 10. Environment and baselines

- macOS: pixi (`pixi run format | lint | test`).
- Windows: pixi does not solve win-64; use the scratchpad win-64 env
  (conda-forge pyvips). Launch: `run.bat app` (console) or `run.bat
  app-gui`. Build: `run.bat build` → dist/SwiftCut/SwiftCut.exe.
- Test baseline: 1 known Windows timing failure (MOT-14) acceptable;