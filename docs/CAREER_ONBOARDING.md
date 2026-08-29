# Career Onboarding for Codex

The user should not fill a giant profile form. Codex should build a durable private Career Knowledge Base through conversation, starting from the user's existing resume and asking only for information that is missing, ambiguous, or materially useful for job matching/application forms.

## Private outputs

Store real personal information only under ignored `career/private/`:

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

Never commit these files.

## Interaction principles

- **Resume first.** Read existing material before asking the user to repeat anything.
- **Small batches.** Ask 1–3 tightly related questions in one turn, not a 20-field questionnaire and not dozens of one-line interruptions.
- **Concrete prompts.** Prefer “你说这段经历从研发做到量产，recipe / DOE / release / matching 哪些是你亲自负责？” over “请描述你的工作经历”.
- **Evidence before adjectives.** Capture ownership, scope, tools, measurable outcome, production impact, troubleshooting examples, collaboration, and 0→1 work. Do not turn “参与” into “负责” or invent metrics.
- **Fact vs preference.** “做过 X” belongs in profile/projects; “不接受外包” belongs in filters; “愿意出差 30%” belongs in reusable answers/preferences.
- **Progressive completion.** The profile can become richer while job search is already running.
- **Resumeable.** Update `ONBOARDING_STATE.json` so future Codex sessions continue from gaps instead of starting over.

## Recommended phases

### Phase 0 — ingest existing evidence

Read resume(s), portfolio links and any prior profile files. Extract only explicit facts. Create a gap map with confidence, for example:

```json
{
  "education": "complete",
  "employment_dates": "complete",
  "current_role_scope": "partial",
  "quantified_outcomes": "missing",
  "target_roles": "missing",
  "target_cities": "partial",
  "salary_preference": "optional",
  "travel_preference": "unknown"
}
```

Do not ask the user to confirm every extracted field unless something is ambiguous or important.

### Phase 1 — search intent

Get enough to start searching quickly:

- target role families and priority
- target cities / remote preference
- hard exclusions
- obvious compensation or employment-type constraints, only when the user wants to state them

Once these are sufficient, job discovery may begin even if deeper profile work is unfinished.

### Phase 2 — experience depth

For each relevant work/project experience, fill the highest-value gaps:

- what problem existed
- what the user personally owned
- what tools/technology/process were used
- what decisions/experiments/troubleshooting they performed
- what changed because of their work
- what evidence could be discussed in an interview

Do not chase every detail. Prioritize facts that change JD matching, resume positioning, recruiter messages or interview readiness.

### Phase 3 — stories and positioning

Build reusable interview/resume evidence in `STORIES.md`, preferably with situation → task → action → result, but preserve the user's natural facts rather than forcing fake metrics.

Also record legitimate positioning bridges, e.g. domain expertise + software/AI project experience, without claiming professional experience the user does not have.

### Phase 4 — ATS/application facts

Collect only when needed or voluntarily provided:

- phone/email/address fields used in applications
- notice period
- work authorization / sponsorship
- travel / relocation limits
- salary expectations
- portfolio/GitHub/website links
- reusable screening answers

For legal, demographic, disability, veteran, criminal-history, work-authorization, sponsorship or similarly sensitive application questions, never infer. Ask when the form requires it and record only what the user explicitly confirms.

## Reusable ATS answers

`ANSWERS.json` should store both the answer and its scope so Codex does not overgeneralize.

```json
{
  "travel": {
    "answer": true,
    "max_percentage": 30,
    "confirmed_by_user": true,
    "confirmed_at": "2026-08-29"
  }
}
```

A later 70% travel question is outside the saved scope and requires a new confirmation.

For free-text screening questions, save reusable answers only when they remain truthful across employers. Company-specific motivation answers should not be blindly reused.

## ONBOARDING_STATE.json

Keep a lightweight resumable state, for example:

```json
{
  "schema": "career-onboarding-v1",
  "core_ready": true,
  "domains": {
    "identity": "partial",
    "education": "complete",
    "experience": "complete",
    "projects": "partial",
    "targets": "complete",
    "filters": "complete",
    "ats_answers": "partial"
  },
  "next_questions": [
    "补充最能代表 0→1 ownership 的项目结果",
    "首次遇到官网要求 notice period 时确认"
  ]
}
```

This file is guidance, not truth. The underlying profile/project/answer files remain the source of confirmed facts.

## Completion behavior

Onboarding does not need to reach 100%. Start job discovery once core resume evidence + target roles + target cities + hard filters are usable. If a new JD or ATS exposes a gap, pause only the affected job, batch the smallest related questions, save the confirmed answer locally, and continue.

The user should feel that the agent is **learning them once and reusing that knowledge**, not repeatedly interviewing them from scratch.
