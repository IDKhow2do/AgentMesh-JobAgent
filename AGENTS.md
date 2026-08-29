# Project Instructions for Codex

> **Modified in the IDKhow2do fork.** This fork defaults to the local-only, Codex-native workflow. The upstream AgentMesh360 cloud workflow remains in the original source/docs for reference, but Codex MUST NOT require or call AgentMesh360 cloud services unless the user explicitly asks to restore the upstream commercial workflow.

## Default Mode: Local Only

Read `CODEX_LOCAL.md` before doing job-search work.

The default architecture is:

```text
User -> Codex -> jobagent-local -> local browser/platform adapters
                  |                    |
                  |                    +-> Boss / Liepin / Zhilian / 51Job
                  +-> local JSON review files

Codex itself = search-intent reasoning + JD review + scoring + greeting generation
```

### Hard rules

1. Do not run `jobagent init --key ...` in the local workflow.
2. Do not request an AgentMesh360 API key.
3. Do not call AgentMesh360 cloud resume analysis, SearchPlan, decision, credit, or greeting endpoints.
4. Do not ask for an OpenAI/DeepSeek/Claude API key. The interactive Codex session itself is the reasoning layer.
5. Reuse the existing open-source browser collectors and delivery implementations instead of rewriting recruiting-site automation unless a platform adapter is broken.
6. Keep all personal data under ignored paths: `career/private/` and `.jobagent-local/`.
7. Never commit resumes, phone numbers, email addresses, recruiting-site cookies, login tokens, private career profiles, generated application history, or other user-specific job-search data.
8. Recruiting-site login should be completed by the user in the managed browser when QR/SMS/manual verification is required. Never request the user's recruiting-site password in chat or store it in the repository.
9. Discovery may run without delivery authorization. Real delivery is different: always show the selected jobs to the user and require an explicit instruction to submit/apply/send before using `jobagent-local apply ... --send`.
10. `jobagent-local apply` without `--send` is the mandatory first dry-run for a newly reviewed batch.
11. Keep browser actions serial. A failure on one platform must not prevent discovery on the other platforms.
12. Never invent resume facts, job requirements, salary, employer details, or skills. Preserve uncertainty in `risks`/`reasons` instead of guessing.

## Start Here

1. `CODEX_LOCAL.md` — canonical workflow for this fork.
2. `src/jobagent/local_cli.py` — local-only CLI orchestration.
3. `src/jobagent/platforms/discovery.py` — shared four-platform collection layer.
4. `src/jobagent/platforms/*/apply.py` and Boss `send_flow.py` — existing delivery implementations reused by local mode.
5. `career/README.md` — private career-profile layout.
6. `pyproject.toml` — exposes `jobagent-local`.

The upstream `README.md`, `docs/agent-onboarding.md`, cloud client, signed decision protocol, credits, and account binding describe the original AgentMesh360 product. They are **legacy/upstream mode** in this fork, not the default execution path.

## Common Commands

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
jobagent-local doctor
```

Discover all supported platforms:

```bash
jobagent-local round \
  --city 上海 \
  --keyword FDE \
  --keyword 'AI应用工程师'
```

The output is written under `.jobagent-local/runs/<timestamp>/`. Codex must review the generated `review.json`, using the user's private career profile, then add `decision`, `score`, `reasons`, `risks`, and `greeting` where appropriate.

Dry-run selected jobs:

```bash
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json
```

Only after explicit user authorization:

```bash
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json --send
```

## Review Policy

Use these decisions:

- `selected`: recommend for delivery.
- `review`: plausible but user should inspect.
- `rejected`: do not deliver.

Apply the user's explicit hard filters before scoring. For duplicate postings across platforms, preserve the strongest canonical record and note duplicates rather than recommending repeated applications unless the user specifically wants that.

Do not treat a nominal years-of-experience mismatch as an automatic rejection unless the user's filters say so; report it as a risk and judge the actual responsibilities against the user's evidence. Do not weaken explicit degree, location, employment-type, outsourcing, compensation, or other hard filters when the user has declared them mandatory.

## Platform Notes

- Boss: local delivery requires a non-empty reviewed personalized greeting and uses the existing verified Boss greeting flow.
- Liepin: local mode reuses `LiepinApplySender`.
- Zhilian: local mode reuses `ZhilianApplySender`; its application flow is resume submission, not automatic first-contact greeting delivery.
- 51Job: local mode reuses `Job51ApplySender`; its web application flow is resume submission and greeting text is review/handoff context.

When a platform asks for login, captcha, QR, SMS, or other human verification, surface that need to the user. Do not attempt to defeat platform risk controls or bypass verification.

## Development Rules

- Keep changes compatible with Python 3.11+.
- Preserve the Apache-2.0 license and attribution. Modified upstream files should carry an obvious modification notice where practical.
- Prefer adding local-only orchestration around the public platform boundaries rather than deleting upstream code. This keeps the fork easy to compare and rebase.
- Add tests for local logic that does not require a live recruiting site. Do not make CI perform real applications or depend on a user's logged-in browser.
- Never put private operational secrets or anti-abuse evasion logic in this public repository.

## Done Means

For local-only changes:

- `jobagent-local doctor` starts without an AgentMesh API key.
- local SearchPlans can be built from user-provided cities/keywords.
- a four-platform round isolates platform failures and emits `review.json`.
- Codex can enrich `review.json` without third-party LLM API calls.
- apply defaults to dry-run; real delivery requires `--send` plus prior explicit user approval.
- personal data paths are gitignored.
- tests or at least a Python syntax/import smoke check are run when the environment permits; if network/runtime dependencies prevent verification, say so explicitly in the handoff.
