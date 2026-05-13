# Golden agent transcripts

Realistic (not idealised) sample outputs for each agent role, one file
per `<role>.<label>.md`. The file content is exactly what the agent's
`text_output` would be — prose around a fenced `json` block, using the
schema the role's prompt asks for, including the optional fields
(`params`, `observation`, `next_step`, `artifacts`, …) and a bit of
surrounding narration.

Replayed through `run_experiment` by
`tests/test_orchestrator/test_loop_golden.py` to check that the loop
copes with realistic output (the canned strings in `test_loop.py` are
hand-trimmed to parse cleanly, so they don't exercise prompt/parser
drift). **Refresh these from a real `URIKA_SMOKE_REAL=1` run when you
change a role's prompt or its output JSON schema.**
