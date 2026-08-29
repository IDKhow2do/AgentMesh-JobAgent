# Project Instructions for Codex

> **IDKhow2do fork.** Default to the local-only, Codex-native workflow. Do not require AgentMesh360 or another LLM API unless the user explicitly asks to restore upstream commercial behavior.

## Default architecture

```text
User -> Codex
          |-> career/private knowledge base
          |-> jobagent-local -> BOSS / Liepin / Zhilian / 51Job
          |-> official Careers/ATS resolver
          |-> jobagent-official -> dedupe + browser queue + final-submit gate
```

Read `CODEX_LOCAL.md`, `docs/CAREER_ONBOARDING.md`, and `docs/OFFICIAL_FIRST.md` before job-search work.

## Hard rules

1. Do not run `jobagent init --key ...`; do not request an AgentMesh360/OpenAI/DeepSeek/Claude API key for this workflow.
2. Store all real personal data under ignored `career/private/` or `.jobagent-local/`. Never commit resumes, contacts, cookies, login tokens, private answers or application history.
3. Read the user's resume before onboarding questions. Ask only for missing/ambiguous facts. Never invent resume, employer, JD, salary, work-authorization, relocation, travel, legal or screening facts.
4. Recruiting platforms are discovery/fallback/recruiter-communication sources. Prefer a verified employer Careers/ATS requisition for resume submission when the same job is reliably matched.
5. Do not guess official links. Verify employer, title/role, location and JD similarity before setting `official_url`.
6. Cross-channel duplicates become one canonical job. One successful resume submission suppresses duplicate resume submissions on other channels.
7. Official browser limits are hard defaults: **4 open tabs, 2 active form tabs, 1 final submit**. Close/release finished or failed tabs before claiming more.
8. Unknown official forms are handled with Codex Browser, not guessed selectors. CAPTCHA/SMS/identity/legal declarations require user action when appropriate; do not bypass controls.
9. **The user is the final reviewer.** Before any real recruiter message or application submission, generate `FINAL_REVIEW.md` and show the complete consolidated plan.
10. Any change to an approved job, channel, resume variant, greeting, material screening answer or route requires a new final review.
11. Platform `--send` is code-gated by `jobagent-local review --approve`; `--send` alone must fail without a valid matching digest.
12. Official `submitting/submitted` is code-gated by `jobagent-official review --approve`; the queue digest must still match.
13. Always run platform dry-run before real delivery. Final official submits are serial.
14. A failure on one source/job must not unnecessarily stop independent sources/jobs.

## Performance rules

1. After `jobagent-local round`, read `review-index.json` before `review.json`.
2. Cross-platform duplicates are collapsed before Codex review.
3. `job-index.json` marks new/changed/previously-seen jobs across runs.
4. `decision-cache.json` may restore a prior decision only when both the job fingerprint and Career Profile digest are unchanged.
5. Deep-read full JD only for new, changed, uncertain or promising jobs. Do not burn context re-analyzing unchanged cached jobs without a reason.
6. Resolve official Careers pages only after initial filtering/selection, not for every raw result.

## Primary commands

Install/test:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest tests/test_local_cli.py tests/test_local_state.py tests/test_official.py
jobagent-local doctor
jobagent-local profile
```

Discover:

```bash
jobagent-local round --city 上海 --keyword FDE --keyword 'AI应用工程师'
```

Prepare official queue after Codex has verified official URLs:

```bash
jobagent-official prepare --input .jobagent-local/runs/<timestamp>/review.json
```

Create the user-facing final review sheet:

```bash
jobagent-local summary --input .jobagent-local/runs/<timestamp>/review.json
```

After the user explicitly approves the exact plan:

```bash
jobagent-local review --input .jobagent-local/runs/<timestamp>/review.json --approve
jobagent-official review --queue .jobagent-local/runs/<timestamp>/official-queue.json --approve
```

Then dry-run platform actions:

```bash
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json
```

Only after the above approval remains valid:

```bash
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json --send
```

Official form filling uses `jobagent-official claim/update`; `submitting` is impossible without the official final-review authorization.

## Review policy

Use `selected`, `review`, and `rejected`. Apply hard filters before scoring. Preserve uncertainty in `risks`. For selected jobs, record the proposed `resume_variant`, `preferred_channel`, `greeting` when applicable, and material `screening_answers` before final review.

If `preferred_channel=official`, `jobagent-local apply` suppresses duplicate platform resume submission. A BOSS message can still be proposed as `platform_action=message_only` and must appear in `FINAL_REVIEW.md`.

## Development rules

Keep Python 3.11+ compatibility and Apache-2.0 attribution. Prefer additive local orchestration around upstream platform boundaries so upstream rebases remain possible. Add deterministic tests; CI must never perform real applications. Never add anti-abuse evasion or verification bypass logic.

## Done means

- no paid AgentMesh/LLM API is required;
- onboarding remains conversational and private;
- four-platform discovery is isolated by source;
- duplicate and unchanged work is minimized;
- verified official ATS submission is preferred;
- browser limits remain 4 / 2 / 1;
- both official and platform execution are hard-gated by the user's exact final review;
- the normal user-facing artifact is `FINAL_REVIEW.md`, not raw JSON;
- focused tests pass before live browser use;
- live-site limitations are disclosed rather than guessed around.
