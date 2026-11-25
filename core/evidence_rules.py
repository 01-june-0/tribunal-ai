"""What the roles may ask for as evidence, shared by every ARCHITECT and INSPECTOR prompt.

A mission once failed six steps in a row although every test passed: the ARCHITECT wrote acceptance criteria that asked
for records of a process (a browser play-through, test runs before the change, a re-run on a clean commit), and the
INSPECTOR reported each missing record as P0. Nobody can hand such a record to the INSPECTOR: it sees the diff and
Tribunal's own test run only, and Tribunal already runs the baseline and the final tests itself.
"""

PROCESS_RECORDS = ("logs or reports of test runs, baseline or before/after runs, manual or browser play-throughs, "
                   "screenshots, console observations, re-runs on a clean commit")

CRITERIA_RULE = (
    "Acceptance criteria state behaviour that a test can assert: a test in the diff that Tribunal's own test run "
    "executes (pytest, plus Node tests that import node:test or the project's `npm test`). Tribunal itself runs the "
    "tests before the change (baseline) and after it and checks for regressions; the Inspector sees only the diff and "
    "that test output. So never require records of a process (" + PROCESS_RECORDS + "). Behaviour seen in a browser "
    "(a game, a page) is specified through logic a test can drive: state, rules and rendering inputs kept in modules "
    "a test imports."
)

INSPECTOR_RULE = (
    "The evidence you judge is the diff and Tribunal's own test run shown here; Tribunal itself runs the baseline "
    "before the change and the final tests, and enforces regressions. A missing record of a process ("
    + PROCESS_RECORDS + ") is never a P0 or P1 finding: nobody can hand it to you. When an acceptance criterion asks "
    "for such a record, judge the behaviour it is about from the code and the tests instead, and note the record at "
    "most as P2."
)

DECIDE_RULE = (
    "Inspector findings that only report a missing record of a process (" + PROCESS_RECORDS + ") count as P2: Tribunal "
    "records the test runs itself and no role can supply the rest. Do not FAIL a run for them, and never ask the Maker "
    "for them in next_steps."
)
