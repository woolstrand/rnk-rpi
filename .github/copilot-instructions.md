# Copilot instructions for rnk-rpi

## Environment
- This codebase targets a **Raspberry Pi**, but the agent runs on a
  **completely different, unrelated development machine** (e.g. a
  Mac/dev laptop). The two are separate computers with separate OSes,
  separate Python installs, separate installed packages, and separate
  hardware. Nothing about this machine's environment tells you anything
  about the Pi's, and vice versa.
- **Never launch, run, test, or check anything locally**, including:
  - `scripts/setup.sh`, `scripts/rnk-rpi`, or any systemd/GPIO commands
    (they assume Pi hardware/OS and will fail or do nothing meaningful);
  - starting the app (`python main.py`, `flask run`, etc.);
  - running the test suite or individual tests (`pytest`, ad-hoc
    `python -c "import ..."` sanity checks);
  - probing what's installed locally (`pip list`, `which`, checking
    package versions) to infer anything about the Pi's setup or to
    decide what to add to `requirements.txt`.
  None of this reflects the target environment, so results from this
  machine are misleading at best, and can waste time.
- Instead: verify changes by **reading the code carefully** (static
  review, tracing logic by hand). Base dependency decisions solely on
  what's declared in `requirements.txt` and imported in the code, never
  on what happens to be importable here.
- When asked to set up, deploy, test, or manage the service, make the
  necessary code/script changes and then just report what was changed.
  The user will copy/run/test everything manually on the actual
  Raspberry Pi and report results back if needed.
