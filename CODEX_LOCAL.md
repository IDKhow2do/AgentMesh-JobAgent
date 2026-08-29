# Codex Local Job Agent

> Fork extension: this workflow is designed to run without AgentMesh360 cloud credits or an AgentMesh API key. It reuses the upstream open-source browser collectors and delivery drivers. Codex is the reasoning layer.

## Goal

The user should be able to tell Codex things like:

- “开始今天的求职。”
- “搜上海、苏州、无锡的 FDE / AI 应用 / AI Solution / 工业 AI 岗位。”
- “把匹配度 80 分以上的岗位给我看。”
- “这 8 个都投。”

Codex should turn that intent into local CLI calls, review the returned job JSON itself, and only perform real delivery after explicit user approval.

## Privacy

Never commit resumes, phone numbers, email addresses, recruiting-site cookies, private career notes, or generated application history.

Use these ignored paths:

```text
career/private/
.jobagent-local/
```

Recommended local files:

```text
career/private/resume.pdf
career/private/PROFILE.md
career/private/TARGETS.md
career/private/FILTERS.md
```

## Install from this branch

```bash
git clone -b codex-local-agent https://github.com/IDKhow2do/AgentMesh-JobAgent.git
cd AgentMesh-JobAgent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
jobagent-local doctor
```

No AgentMesh API key is required for `jobagent-local`.

## First-run browser login

The collectors reuse the upstream managed Chrome browser/session code. If a site reports that login is required, let the browser open and ask the user to complete QR/SMS/manual login. Never ask the user to paste a recruiting-site password into a prompt or repository file.

If the existing upstream login commands work locally, they may be used only for browser login/session setup; do not run `jobagent init --key ...`, `resume analyze`, or cloud discovery in this local-only workflow.

## Discover one platform

```bash
jobagent-local discover \
  --platform boss \
  --city 上海 \
  --city 苏州 \
  --keyword FDE \
  --keyword 'AI应用工程师'
```

Supported platform values:

```text
boss
liepin
zhilian
51job
```

## Discover all four platforms

```bash
jobagent-local round \
  --city 上海 \
  --city 苏州 \
  --city 无锡 \
  --keyword FDE \
  --keyword 'Forward Deployed Engineer' \
  --keyword 'AI应用工程师' \
  --keyword 'AI Solution Engineer' \
  --keyword '工业AI' \
  --keyword '智能制造AI' \
  --keyword '半导体AI'
```

The command creates a run directory under `.jobagent-local/runs/<timestamp>/` containing per-platform JSON plus `review.json`.

A failure on one recruiting platform must not stop the other platforms.

## Codex review contract

Open the generated `review.json`, read the user's local career files, and enrich every useful job with fields like:

```json
{
  "decision": "selected",
  "score": 88,
  "reasons": [
    "role is AI application/FDE-like",
    "manufacturing domain experience is relevant"
  ],
  "risks": [
    "JD asks for more software engineering experience"
  ],
  "greeting": "根据真实简历信息生成的简短招呼语"
}
```

Allowed `decision` values:

- `selected`: recommend for delivery
- `review`: ask the user to inspect
- `rejected`: do not send

Rules for Codex:

1. Do not call any third-party LLM API. Codex itself performs job matching and copy generation.
2. Never invent resume experience, degree, skills, salary, company facts, or JD requirements.
3. Apply hard filters from `career/private/FILTERS.md` before scoring.
4. Explain uncertain cases instead of guessing.
5. Deduplicate obvious cross-platform duplicates before recommending a final set.
6. Write decisions back to the generated `review.json`.
7. Show the user the final selected set before real delivery.

## Safe delivery

First run a dry-run:

```bash
jobagent-local apply --input .jobagent-local/runs/<timestamp>/review.json
```

Dry-run is the default and sends nothing.

Only after the user explicitly approves the selected jobs, run:

```bash
jobagent-local apply \
  --input .jobagent-local/runs/<timestamp>/review.json \
  --send
```

Platform behavior follows the upstream browser implementations:

- Boss: sends the reviewed personalized greeting.
- Liepin: controlled resume/application flow plus greeting when the platform flow supports it.
- Zhilian: submits the resume; greeting is review/handoff context because its web apply flow has no equivalent first-contact message field.
- 51Job: submits the resume; greeting is review/handoff context rather than an automatically typed message.

Real delivery must never be inferred from phrases like “看看”, “分析一下”, or “跑一遍”. Require an unambiguous user instruction to apply/send before adding `--send`.

## Recommended Codex startup prompt

Paste this once in Codex after cloning:

```text
Read CODEX_LOCAL.md first. You are my local job-search agent. Do not use AgentMesh360 cloud services or request an AgentMesh API key. Use jobagent-local and the existing browser/platform code. Keep all resume and personal career data under career/private or .jobagent-local so it is never committed. First help me prepare PROFILE.md, TARGETS.md and FILTERS.md from my resume. When I say “开始今天的求职”, search all four supported platforms, review and score jobs yourself, deduplicate them, and show me the selected set. Always dry-run delivery first. Only use --send after I explicitly approve the jobs to be submitted. If a recruiting site requires QR/SMS/manual login, pause only for that user action and continue afterward.
```
