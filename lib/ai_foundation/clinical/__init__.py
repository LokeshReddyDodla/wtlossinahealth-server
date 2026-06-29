"""
Clinical intelligence modules.

Each subdirectory is a clinical domain (metabolic, cardio, renal, ...) with its own
deterministic engine, data requirements, and safety gates. Agents consume these via
the domain's service class — they never call the raw engine directly.
"""
