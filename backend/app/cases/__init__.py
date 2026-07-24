"""CASES — the case file that ties the four modules into one investigation.

A case is the spine an investigator works: intel (INFILTRATE), tracing (TRACE),
attribution (TAKEDOWN) and action (UNCOVER) all attach to it via ``case_id``,
and it walks the real investigation stages (intake → freeze → trace → takedown
→ report → recovery → closed). Persisted on the existing ``core.cases`` table
(agency-scoped RLS), memory-backed in POC.
"""
