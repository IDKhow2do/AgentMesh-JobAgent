# Codex Local Job Agent

This fork is local-only and Codex-native. Do not use AgentMesh360 cloud credits or request an AgentMesh API key. Codex is the reasoning layer; the repository supplies recruiting-platform adapters, official-career routing, dedupe, queue state, and safe delivery controls.

## Non-negotiable final review gate

The user is the final reviewer. Discovery, research, scoring, official-site matching, form preparation and draft answers may happen before approval, but **no application may be submitted and no recruiter greeting may be sent until the user has reviewed one complete final plan and explicitly approved it**.

Before asking for approval, present one consolidated list containing every proposed application: company, role, city, score, important risks, preferred channel (official/platform), official URL/ATS when known, fallback channel, resume variant, greeting/message if any, and any non-trivial screening answers. The user may approve all, exclude individual jobs, or request changes. Regenerate the final plan after changes.

For official/ATS submission, persist the exact approved snapshot with:

```bash
jobagent-official review --queue <official-queue.json> --approve
```

or approve only chosen canonical keys with repeated `--key`. Queue content changes invalidate authorization automatically. `submitting`/`submitted` states are rejected without a valid matching authorization digest.

For recruiting-platform delivery, treat the same final approval as mandatory. Run `jobagent-local apply` dry-run first; only after the consolidated final review is approved may Codex add `--send`. Do not interpret earlier statements such as “帮我找工作”, “看看这些”, “准备一下”, or a general preference for automatic applications as final approval.

## First run

Read `AGENTS.md`, `docs/CAREER_ONBOARDING.md`, and `docs/OFFICIAL_FIRST.md`. Then install and test:

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

## Workflow

1. Discover jobs from BOSS / Liepin / Zhilian / 51Job and other useful sources.
2. Codex reviews, scores and deduplicates.
3. For selected candidates, search for the exact official Careers/ATS posting. Official is preferred only with reliable matching evidence.
4. Prepare forms using the local career profile. Unknown material questions require the user.
5. Build `official-queue.json`; respect 4 total tabs, 2 form tabs, 1 submit.
6. Produce the **single consolidated final review plan** for the user.
7. Wait. No send/submit action before explicit approval.
8. Record final-review authorization for the exact queue and run platform dry-runs.
9. Submit serially. Successful official submission suppresses duplicate platform resume submission; platform communication may still be used when explicitly included in the approved plan.
10. Audit outcomes and report delivered / failed / human-required separately.

## Recommended Codex startup prompt

```text
Read AGENTS.md and CODEX_LOCAL.md. Use local-only mode; do not use AgentMesh360 or another paid LLM API. Start by interviewing me conversationally to build my private Career Profile from my resume. Then discover and score jobs, prefer verified official Careers/ATS applications, deduplicate cross-channel postings, and prepare application materials. Before any real submission or recruiter message, give me ONE complete consolidated final review plan covering every proposed job, channel, resume/message and important screening answer. I am the final reviewer. Wait for my explicit approval. After approval, persist the exact review authorization, dry-run, then submit serially. If the plan changes, ask me to review it again. Keep browser limits at 4 open tabs, 2 active forms and 1 final submit.
```
