"""AI Foundation eval harness.

Runs golden queries through the real HealthQueryAgent (real LLMs, real
prompts, real reasoning loop) against deterministic fixture data, then
scores responses with deterministic checks + an LLM judge.

Usage:
    .venv/bin/python -m evals.run                      # full suite
    .venv/bin/python -m evals.run --case med_stop      # one case
    .venv/bin/python -m evals.run --no-judge           # checks only

NOT part of the pytest suite — every run costs real LLM calls.
"""
