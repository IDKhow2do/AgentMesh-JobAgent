# Codex Job Agent — Official First

> A local-first job-search toolchain for **Codex**: discover jobs across Chinese recruiting platforms, prefer verified company Careers/ATS applications, keep personal data local, and require the user to approve one final plan before anything is submitted.

This repository is a customized fork of [AgentMesh-JobAgent](https://github.com/jiyangnan/AgentMesh-JobAgent). It preserves the upstream browser/platform implementations under the Apache-2.0 license, but the **default workflow in this fork does not require AgentMesh360, cloud credits, or another LLM API key**.

## What the fork is for

You should mostly talk to Codex instead of operating scripts yourself:

```text
You
 ↓
Codex — career knowledge + reasoning
 ↓
Job tooling
 ├─ BOSS直聘
 ├─ 猎聘
 ├─ 智联招聘
 ├─ 51Job
 └─ Company Careers / ATS
      ├─ Greenhouse
      ├─ Lever
      ├─ Ashby
      ├─ Workday
      ├─ SmartRecruiters
      ├─ iCIMS / Jobvite
      ├─ Oracle / SAP
      ├─ Moka / 北森
      └─ generic official forms via Codex Browser
```

The recruiting platforms are useful for discovery, fallback and recruiter communication. When Codex can reliably find the same requisition on the employer's official Careers/ATS site, the official route is preferred for the resume submission.

## Core behavior

- **Codex is the AI layer.** No separate OpenAI/DeepSeek/Claude API integration is needed.
- **Local personal data.** Resume, contact details, screening answers and career notes stay under ignored `career/private/` / `.jobagent-local/`.
- **Conversational onboarding.** Codex reads your existing resume first, then asks only for missing/ambiguous information.
- **Four recruiting platforms.** BOSS, 猎聘, 智联 and 51Job reuse the upstream browser collectors/delivery adapters.
- **Official-first routing.** Verified company Careers/ATS postings are preferred for resume submission.
- **Cross-channel dedupe.** Obvious copies become one canonical job while retaining source URLs.
- **Incremental daily runs.** Previously seen/unchanged jobs are indexed; prior decisions can be reused only if both the JD fingerprint and your Career Profile are unchanged.
- **Bounded browser load.** At most 4 open official tabs, 2 active application forms and 1 final submission.
- **User-owned final review.** No platform send or official final Submit can happen without approval of the exact reviewed materials.

## The normal UX

After setup, your interaction should feel roughly like this:

> **You:** 开始今天的求职。
>
> **Codex:** 今天发现 126 条，跨平台去重后 78 个；52 个是已见且未变化，复用 48 个缓存判断，需要重点分析 30 个。最终建议 11 个。我已经找到其中 7 个官网职位并准备好投递材料，4 个走招聘平台。这里是最终评审。
>
> **You:** 3、8 不投，5 换 FDE 版简历，其他可以。
>
> **Codex:** 已更新最终方案，请再次确认。
>
> **You:** 同意，开始投。

Only after the last explicit approval are execution authorizations created.

## Quick start for Codex

Clone the repository and open it in Codex, then tell Codex:

```text
Read AGENTS.md and CODEX_LOCAL.md and take ownership of this repo as my local job-search agent. Do not use AgentMesh360 or any extra paid LLM API. Run the focused tests and doctor checks first. If my career/private profile is incomplete, read my resume and interview me conversationally, asking only for missing information. Then search and rank jobs, prefer verified official Careers/ATS submission, and use the platform adapters as discovery/fallback/recruiter communication. Use incremental cache so unchanged jobs are not re-analyzed unnecessarily. Before any real send or submit, generate FINAL_REVIEW.md and show me the whole plan. I am the final reviewer. Only after I explicitly approve the exact plan may you persist both review authorizations, dry-run, and execute. Keep browser limits at 4 tabs, 2 active forms and 1 final submit. Fix repository bugs you encounter, but do not weaken these safety gates.
```

Canonical instructions for Codex live in [`AGENTS.md`](./AGENTS.md) and [`CODEX_LOCAL.md`](./CODEX_LOCAL.md).

## Install / test

Python 3.11+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest tests/test_local_cli.py tests/test_local_state.py tests/test_official.py
jobagent-local doctor
jobagent-local profile
```

The focused test suite is deterministic and does not perform real job applications.

## Career Onboarding

Do not manually create a giant form. Put your existing resume under `career/private/` (or tell Codex where it is), then let Codex interview you.

Recommended private knowledge base:

```text
career/private/
├── MASTER_PROFILE.md
├── TARGETS.md
├── FILTERS.md
├── PROJECTS.md
├── STORIES.md
├── ANSWERS.json
├── ONBOARDING_STATE.json
└── resumes/
```

These paths are gitignored. See [`docs/CAREER_ONBOARDING.md`](./docs/CAREER_ONBOARDING.md).

## Discovery and incremental review

Example:

```bash
jobagent-local round \
  --city 上海 \
  --city 苏州 \
  --keyword FDE \
  --keyword 'AI应用工程师'
```

A run writes:

```text
.jobagent-local/runs/<timestamp>/
├── boss.json
├── liepin.json
├── zhilian.json
├── 51job.json
├── summary.json
├── review-index.json
└── review.json
```

`review-index.json` is intentionally compact. Codex should read it first and deep-read the full JD only for new, changed, uncertain or promising jobs.

Persistent local state:

```text
.jobagent-local/
├── job-index.json       # first/last seen + JD fingerprint
├── decision-cache.json  # profile-aware reusable Codex decisions
└── runs/
```

If your Career Profile changes, stale cached decisions are not blindly reused.

## Official Careers / ATS

After Codex verifies official URLs for selected jobs:

```bash
jobagent-official prepare --input <review.json>
```

Only verified official jobs are claimable as forms:

```bash
jobagent-official claim --queue <official-queue.json> --kind form
```

Hard limits:

| Resource | Limit |
|---|---:|
| Open official tabs | 4 |
| Active form tabs | 2 |
| Final submits | 1 |

Unknown forms are handled by Codex Browser. The project does not try to bypass CAPTCHA, SMS, identity checks or other platform safeguards.

See [`docs/OFFICIAL_FIRST.md`](./docs/OFFICIAL_FIRST.md).

## The final review gate

Codex creates a human-readable:

```bash
jobagent-local summary --input <review.json>
```

which writes:

```text
FINAL_REVIEW.md
```

That page should contain every proposed job, score, important risk, channel, official/ATS route, resume variant, greeting and material screening answer.

You can approve all, exclude jobs or request edits. Any material change requires another review.

After explicit approval, Codex records exact digests:

```bash
jobagent-local review --input <review.json> --approve
jobagent-official review --queue <official-queue.json> --approve
```

Platform dry-run:

```bash
jobagent-local apply --input <review.json>
```

Real platform action:

```bash
jobagent-local apply --input <review.json> --send
```

`--send` is **not sufficient by itself**: it is rejected unless the current selected materials still match the user's final-review authorization.

Official submission is likewise blocked at `submitting` / `submitted` unless the approved official materials still match their digest. Execution status itself does not invalidate approval, so a multi-job batch can progress serially; changing the URL, resume, answers or other reviewed material does.

## Platform behavior

- **BOSS:** structured discovery and verified personalized greeting flow.
- **猎聘:** existing controlled application/resume delivery implementation.
- **智联:** resume-submit flow; greeting is not equivalent to BOSS first-contact messaging.
- **51Job:** resume-submit flow with delivery reconciliation.

A failure on one platform should not stop independent discovery on the others.

## Why keep the project if Codex can browse websites?

Codex Browser is the general-purpose fallback. This repository supplies durable job-specific primitives that should not be re-invented every run: platform parsers, structured candidate records, delivery state machines, dedupe, auditability, bounded browser queues, incremental job history and final-review authorization.

In short:

```text
Codex Browser = flexible general hand
This repo      = job-search tooling + memory + guardrails
```

## Upstream and license

This fork derives from [`jiyangnan/AgentMesh-JobAgent`](https://github.com/jiyangnan/AgentMesh-JobAgent) and retains its Apache License 2.0 attribution. The upstream AgentMesh360 cloud workflow still exists in the inherited source for compatibility/reference, but it is not the default workflow documented or requested by `AGENTS.md` in this fork.

See [`LICENSE`](./LICENSE) for license terms.
