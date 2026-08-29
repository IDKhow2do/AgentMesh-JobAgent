# Codex Local Job Agent

This fork is designed for one interaction model: **the user talks to Codex; Codex operates the job-search tools.** No AgentMesh360 key and no extra paid LLM API are required.

## Product contract

Codex is the brain. The repository is the durable tooling layer: BOSS / 猎聘 / 智联 / 51Job adapters, official Careers/ATS routing, cross-channel dedupe, cross-run cache, browser queue, audit state and hard approval gates.

The user is always the final reviewer. Codex may search, research, score, find official postings, draft messages, choose resume variants and pre-fill forms before approval, but **must not send a recruiter message, submit a platform application, or click a final official Submit/Apply button until one consolidated final plan has been explicitly approved.**

## First-time setup

Run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest tests/test_local_cli.py tests/test_local_state.py tests/test_official.py
jobagent-local doctor
jobagent-local profile
```

If the career profile is incomplete, do conversational onboarding first. Read the user's existing resume before asking questions. Store private information only under `career/private/`; never commit it. The preferred files are:

```text
career/private/
├── MASTER_PROFILE.md
├── TARGETS.md
├── FILTERS.md
├── PROJECTS.md
├── STORIES.md
├── ANSWERS.json
└── resumes/
```

Do not ask for one giant form. Ask the smallest useful follow-up, save confirmed facts, and continue. Never invent an answer to an ATS screening question.

## Daily workflow

### 1. Discover

Use the recruiting platforms as job discovery/recruiter-communication sources:

```bash
jobagent-local round \
  --city 上海 \
  --city 苏州 \
  --keyword FDE \
  --keyword 'AI应用工程师'
```

A run emits:

```text
summary.json       machine summary
review-index.json  compact, cheap-to-read review index
review.json        full JD and decision workspace
```

Performance rule: **read `review-index.json` first.** The tool deduplicates obvious cross-platform copies and persists `job-index.json`. Unchanged jobs can restore a decision from `decision-cache.json` only when both the JD fingerprint and the user's Career Profile digest are unchanged. Deep-read the full JD only for new, changed, uncertain or promising jobs.

### 2. Decide

Apply `FILTERS.md` first, then score. For useful jobs, write back to `review.json`:

```json
{
  "decision": "selected",
  "score": 88,
  "reasons": ["..."],
  "risks": ["..."],
  "resume_variant": "FDE版",
  "greeting": "...",
  "preferred_channel": "official"
}
```

Use `review` when evidence is insufficient and `rejected` when the job should not be submitted.

### 3. Resolve official Careers / ATS

For selected/promising jobs, search for the exact employer Careers/ATS requisition. Only set `official_url` when company, role, location and JD evidence are strong. Then:

```bash
jobagent-official prepare --input <review.json>
```

Official submission is preferred when verified. Known ATS families include Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Jobvite, Oracle/Taleo, SAP SuccessFactors, Moka and Beisen. Unknown official forms should be handled with Codex Browser rather than guessed selectors.

Browser limits are hard defaults:

```text
open tabs       <= 4
active forms    <= 2
final submits   = 1
```

Never open more application forms than claimed queue slots. Final submissions are serial.

### 4. Prepare, but do not submit

Codex may fill forms up to the final action. For CAPTCHA, SMS, identity verification, legal declarations, or a material screening question that is not already confirmed, pause only that job and ask the user.

A successful official application should suppress duplicate platform resume submission. A BOSS recruiter follow-up can still be proposed separately by setting `platform_action=message_only` and including that action in final review.

### 5. Generate the one page the user reviews

After every selected job has a proposed channel/materials:

```bash
jobagent-local summary --input <review.json>
```

This creates `FINAL_REVIEW.md`. Show the **entire** file to the user. It contains the proposed company, role, score, risks, channel, ATS/URLs, resume variant, greeting and non-trivial screening answers.

The user can approve all, remove jobs, or request edits. After any edit, regenerate `FINAL_REVIEW.md` and ask again.

### 6. Persist exact approval

After explicit approval of the final plan, authorize both execution layers against their exact snapshots.

Recruiting-platform plan:

```bash
jobagent-local review --input <review.json> --approve
```

For partial approval, use repeated `--key <canonical_job_key>`.

Official queue:

```bash
jobagent-official review --queue <official-queue.json> --approve
```

Changing an approved message, resume choice, screening answer, route or selected job invalidates the matching digest and requires another final review.

### 7. Dry-run, then execute

Platform dry-run:

```bash
jobagent-local apply --input <review.json>
```

Only after the exact final review is authorized:

```bash
jobagent-local apply --input <review.json> --send
```

Official submission follows the authorized official queue and remains serial. Do not treat “帮我找工作”, “准备一下”, “这些不错” or any earlier general automation preference as final approval.

## UX principles for Codex

- The user should mainly see conversation and `FINAL_REVIEW.md`, not raw JSON.
- Do not repeatedly explain implementation details unless something breaks.
- On normal days, report: new jobs, changed jobs, cached decisions reused, recommended jobs, questions needing user input, and final outcomes.
- Ask one compact batch of related onboarding/screening questions when possible instead of interrupting after every field.
- A failure on one source must not stop other sources.
- Keep tabs bounded and close completed/failed form tabs before claiming more.
- Preserve uncertainty. Never manufacture resume facts, employer facts or screening answers.

## Recommended first message to Codex

```text
Read AGENTS.md and CODEX_LOCAL.md and take ownership of this repo as my local job-search agent. Do not use AgentMesh360 or any extra paid LLM API. Run the focused tests and doctor checks first. If my career/private profile is incomplete, read my resume and interview me conversationally, asking only for missing information. Then search and rank jobs, prefer verified official Careers/ATS submission, and use the platform adapters as discovery/fallback/recruiter communication. Use incremental cache so unchanged jobs are not re-analyzed unnecessarily. Before any real send or submit, generate FINAL_REVIEW.md and show me the whole plan. I am the final reviewer. Only after I explicitly approve the exact plan may you persist both review authorizations, dry-run, and execute. Keep browser limits at 4 tabs, 2 form tabs and 1 final submit. Fix repository bugs you encounter, but do not weaken these safety gates.
```
