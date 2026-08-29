# Project Instructions for Codex

> **Modified in the IDKhow2do fork.** This fork defaults to the local-only, Codex-native workflow. The upstream AgentMesh360 cloud workflow remains in the original source/docs for reference, but Codex MUST NOT require or call AgentMesh360 cloud services unless the user explicitly asks to restore the upstream commercial workflow.

## Default Mode: Local Only, Official First

Read `CODEX_LOCAL.md`, `docs/OFFICIAL_FIRST.md`, and `docs/CAREER_ONBOARDING.md` before doing job-search work.

The default architecture is:

```text
User -> Codex
          |-> career/private knowledge base
          |-> jobagent-local -> Boss / Liepin / Zhilian / 51Job discovery
          |-> official-careers resolver -> ATS / company career site
          |-> jobagent-official -> dedupe + queue + tab/submission limits
```

Codex is the reasoning layer. Recruiting-platform code and official-career queue code are deterministic tools.

### Hard rules

1. Do not run `jobagent init --key ...` in the local workflow.
2. Do not request an AgentMesh360 API key or another LLM API key.
3. Keep all personal data under ignored paths: `career/private/` and `.jobagent-local/`.
4. Never commit resumes, contact data, cookies, login tokens, private profiles, screening answers, or application history.
5. When login/QR/SMS/CAPTCHA/legal declaration requires the user, stop only that job and ask for the smallest necessary action.
6. Never invent resume facts, metrics, skills, company facts, JD facts, salary, work authorization, sponsorship, relocation, travel, demographic, legal, or screening answers.
7. Read an existing resume before asking onboarding questions. Ask only for missing or ambiguous information, one concrete question at a time.
8. Recruiting platforms are discovery + recruiter-communication sources. If the same selected job is reliably verified on the employer's official Careers/ATS site, prefer official resume submission.
9. Do not assume a search result is official. Verify employer identity, title/role, location, and JD similarity. Only populate `official_url` when there is real evidence.
10. Cross-channel duplicates become one canonical job. A successful resume submission through one channel blocks duplicate resume submission through the others unless the user explicitly asks otherwise.
11. Official browser limits are hard defaults: max 4 open tabs, max 2 simultaneous application/form tabs, and exactly 1 final submission at a time.
12. Close or release completed/failed/fallback official tabs before claiming more queue items.
13. Real submission always requires explicit user approval. Analysis/discovery phrases never authorize submission.
14. For platform delivery, `jobagent-local apply` must be dry-run first; `--send` requires explicit approval.
15. For official ATS delivery, fill/validate may proceed after the user approved the job set, but the final Submit/Apply action remains serial and must be tracked in `official-queue.json`.
16. Unknown or changing official forms should be handled by Codex Browser, not guessed selectors. Known ATS labels are routing hints, not permission to bypass safeguards.

## Start Here

1. `CODEX_LOCAL.md` — canonical end-to-end workflow.
2. `docs/CAREER_ONBOARDING.md` — conversational profile-building rules.
3. `docs/OFFICIAL_FIRST.md` — official Careers/ATS policy, queue, and tab limits.
4. `src/jobagent/local_cli.py` — four-platform local discovery/delivery.
5. `src/jobagent/official.py` — canonical dedupe, ATS detection, queue policy.
6. `src/jobagent/official_cli.py` — queue CLI (`jobagent-official`).
7. `src/jobagent/platforms/*` — existing platform collectors/senders.

The upstream README/cloud protocol remains reference-only in this fork.

## Common Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest tests/test_local_cli.py tests/test_official.py
jobagent-local doctor
```

Discover platforms:

```bash
jobagent-local round --city 上海 --keyword FDE --keyword 'AI应用工程师'
```

Codex then reviews `review.json`, builds/updates the private career profile, resolves official career URLs for selected/review jobs, and writes `official_url`, `official_match_confidence`, and `official_evidence` only when verified.

Prepare official-first queue:

```bash
jobagent-official prepare --input .jobagent-local/runs/<timestamp>/review.json
jobagent-official status --queue .jobagent-local/runs/<timestamp>/official-queue.json --details
```

Claim at most the permitted form slots:

```bash
jobagent-official claim --queue .jobagent-local/runs/<timestamp>/official-queue.json --kind form
```

Use `jobagent-official update` for `filling`, `human_required`, `ready_to_submit`, `submitting`, `submitted`, `failed`, or `fallback_platform`. The queue rejects two simultaneous `submitting` jobs.

Platform fallback stays available:

```bash
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json
# only after explicit approval
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json --send
```

## Review and Routing Policy

Use `selected`, `review`, and `rejected`. Apply user hard filters before scoring. Preserve uncertainty in `risks` instead of guessing. A nominal experience mismatch is a risk, not automatically fatal unless the user's filters make it one.

Official resolution is preferred after selection, not before every raw result. This avoids opening dozens of career sites for jobs that would be rejected anyway.

If official submission succeeds, mark the canonical job submitted via official and suppress platform resume delivery. Platform messaging can still be used as a recruiter communication channel when it adds value and does not misrepresent submission status.

If official resolution or application fails for a non-user-specific technical reason, mark `fallback_platform` and use the best existing platform source. If the form requires missing user facts, use `human_required`, ask the user, store the confirmed answer locally, and resume that job.

## Development Rules

Keep Python 3.11+ compatibility and Apache-2.0 attribution. Prefer additive local orchestration around upstream boundaries so rebasing stays possible. Add tests for deterministic logic; never make CI perform real applications. Never add anti-abuse evasion or verification bypass logic.

## Done Means

- no AgentMesh API key is required in the default workflow;
- four-platform discovery emits a local review file;
- career onboarding is conversational and private;
- cross-platform duplicates can become one canonical job;
- verified official Careers/ATS links are preferred;
- ATS type is detected when possible;
- queue limits enforce 4 open tabs / 2 form tabs / 1 submit;
- successful official submission prevents duplicate platform resume submission;
- real application always requires explicit user authorization;
- tests/smoke checks are run when possible, and any untested live-browser behavior is disclosed.
