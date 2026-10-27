---
description: Reproduce a failing LopoDev or Godot check with minimal commands, logs and an evidence-backed diagnosis.
agent: lopodev
---
Diagnose: `$ARGUMENTS`.

1. Record the exact failing command, exit code, expected result, and actual
   result. Save stdout/stderr under `artifacts/logs/`.
2. Reproduce with the smallest command. Do not change multiple causes at once.
3. Check tool versions and project state before editing. Inspect logs and the
   generated artifact independently.
4. Delegate a repair only after identifying one likely cause, and specify the
   failed gate plus downstream gates to rerun.
5. Report root cause, changed files, rerun results, and remaining `NOT RUN`
   checks. Do not hide a failed gate behind a passing one.
