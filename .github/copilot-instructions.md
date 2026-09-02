# Copilot instructions for rnk-rpi

## Environment
- This is the RPi-side codebase, but the agent runs on a **different
  development machine**, not on the actual Raspberry Pi.
- **Never run `scripts/setup.sh`, `scripts/rnk-rpi`, or any systemd/GPIO
  commands directly** — they assume a Raspberry Pi environment (GPIO
  hardware, systemd, apt, the `gpio` group, etc.) and will fail or do
  nothing meaningful on this machine.
- When asked to set up, deploy, or manage the service, make the necessary
  code/script changes and then just report what was changed. The user
  will copy/run/test them manually on the actual Raspberry Pi and report
  results back if needed.
- Plain Python-level checks (unit tests, importing pure modules like
  `app/motor/constants.py`, linting) are fine to run locally since they
  don't touch hardware or systemd.
