# Codex Local Job Agent

This fork is local-only and Codex-native. Do not use AgentMesh360 cloud credits or request an AgentMesh API key. Codex is the reasoning layer; the repository supplies recruiting-platform adapters, official-career routing, dedupe, queue state, and safe delivery controls.

## First run

Read:

1. `AGENTS.md`
2. `docs/CAREER_ONBOARDING.md`
3. `docs/OFFICIAL_FIRST.md`

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest tests/test_local_cli.py tests/test_official.py
jobagent-local doctor
```

## Personal information

Do not ask the user to manually fill a giant form. If a resume is provided, read it first, identify gaps, and interview conversationally. Store all real user information under ignored `career/private/` only. Recommended files include `MASTER_PROFILE.md`, `TARGETS.md`, `FILTERS.md`, `PROJECTS.md`, `STORIES.md`, `ANSWERS.json`, and resume variants.

Never invent answers. When an ATS asks something not covered by the local profile, pause that job, ask the smallest necessary question, save the confirmed answer locally, and continue.

## Discovery

Use all four supported recruiting platforms when useful:

```bash
jobagent-local round \
  --city 上海 \
  --city 苏州 \
  --keyword FDE \
  --keyword 'AI应用工程师'
```

Review the resulting `review.json` yourself. Apply the user's hard filters, score the JD, add `decision`, `score`, `reasons`, `risks`, and `greeting`, and deduplicate obvious cross-platform copies.

## Official-first resolution

For `selected` and promising `review` jobs, use Codex Browser/search to look for the same requisition on the employer's official Careers page or official ATS. Do this **after** initial JD filtering so you do not open dozens of sites for rejected jobs.

Only write an official match when evidence is strong:

```json
{
  "official_url": "https://...",
  "official_match_confidence": 0.93,
  "official_evidence": {
    "company_match": true,
    "title_match": true,
    "location_match": true,
    "jd_match": "high"
  }
}
```

Then create the application queue:

```bash
jobagent-official prepare --input .jobagent-local/runs/<timestamp>/review.json
```

The queue prefers a verified official route at confidence >= 0.80. Otherwise it retains the recruiting platform as fallback. Known ATS hosts are labeled Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Jobvite, Oracle/Taleo, SAP SuccessFactors, Moka, or Beisen; unknown forms remain `generic_official` and should be handled by Codex Browser.

## Browser concurrency

Hard defaults:

```text
max open tabs          = 4
max active form tabs   = 2
max final submissions  = 1
```

Claim only available form slots:

```bash
jobagent-official claim --queue <official-queue.json> --kind form
```

Do not open unclaimed application forms. When a form is done, blocked, failed, or moved to fallback, update its queue status and close/release the tab before claiming another.

Final Submit/Apply is always serial. Mark the job `submitting` immediately before the final click; the queue rejects a second simultaneous submit.

Example transitions:

```bash
jobagent-official update --queue <queue> --key <key> --status filling
jobagent-official update --queue <queue> --key <key> --status human_required
jobagent-official update --queue <queue> --key <key> --status ready_to_submit
jobagent-official update --queue <queue> --key <key> --status submitting
jobagent-official update --queue <queue> --key <key> --status submitted --submitted-via official
```

## Cross-channel rule

The same canonical job should receive one resume submission. If official submission succeeds, suppress duplicate resume submission through Boss/Liepin/Zhilian/51Job. Platform recruiter communication may still be used when useful, e.g. telling a recruiter truthfully that the official application has already been submitted.

If official resolution/application fails technically, mark `fallback_platform` and use the best platform source instead.

## Platform delivery fallback

Always dry-run first:

```bash
jobagent-local apply --input <review.json>
```

Only after explicit user approval:

```bash
jobagent-local apply --input <review.json> --send
```

## Recommended startup prompt for Codex

```text
Read AGENTS.md, CODEX_LOCAL.md, docs/CAREER_ONBOARDING.md and docs/OFFICIAL_FIRST.md first. This is my local-only job-search agent. Do not use AgentMesh360 or any paid LLM API. You are the reasoning layer.

On first use, ask me for my resume if I have one, read it first, then interview me conversationally only for missing facts. Keep every real personal detail under career/private and never commit it.

When I ask you to find jobs, use Boss/Liepin/Zhilian/51Job as discovery sources, review and score jobs, and deduplicate them. For jobs I actually want, try to resolve the exact job on the employer's official Careers/ATS site. Prefer verified official applications over platform resume submission.

Use jobagent-official for the official queue. Never exceed 4 open tabs, 2 simultaneous form tabs, or 1 final submission. Close/release finished tabs before claiming more. Unknown ATS/forms should be handled with your browser rather than guessed selectors.

Never submit the same canonical job twice across channels. Do not click a final Submit/Apply or run jobagent-local --send unless I have clearly approved the job set. If a form asks for information you do not know, ask me rather than inventing it, store my confirmed answer locally, then continue.
```
