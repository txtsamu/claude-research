# evonic-hermes-benchmark

Harness and raw results for [../evonic-vs-hermes-agent-benchmark.md](../evonic-vs-hermes-agent-benchmark.md).

- `tasks.py`: 16 tasks (fixtures, prompts, checkers, reference solutions). `selftest.py` validates the suite itself.
- `bench.py`: runner (interleaved, resumable, retries provider failures, marks runs invalid); `report.py`: markdown summary.
- `hermes_driver.py`, `evonic_driver.py`, `evonic_adapter.py`: one `run_task(prompt, workdir, timeout_s)` per agent.
- `evonic_home_setup.py`, `provision_evonic.py`: lean Evonic configuration on the NixOS host (key and password via environment only).
- `mock/`: mock OpenAI server and an isolated local Evonic instance, used to prove the driver before touching a real key.
- `results/`: `full.jsonl` (96 runs), `report.md`, two pilots.

Paths such as `/srv/bench` and the credential file location are specific to the host this ran on. No secrets are stored here.
