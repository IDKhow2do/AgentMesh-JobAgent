# Local Career Knowledge Base

This directory contains only public instructions. **Never commit real personal data here.** Actual user files belong under ignored `career/private/`.

Recommended private layout:

```text
career/private/
├── MASTER_PROFILE.md      # confirmed education/employment/skills facts
├── TARGETS.md             # target roles, cities and priorities
├── FILTERS.md             # hard exclusions vs soft risks
├── PROJECTS.md            # evidence-rich work/AI/project cases
├── STORIES.md             # reusable interview stories
├── ANSWERS.json           # user-confirmed reusable ATS answers with scope
├── ONBOARDING_STATE.json  # resumable gap/progress map
└── resumes/
    ├── master.pdf
    ├── fde.pdf
    └── ai-application.pdf
```

Codex should build these conversationally from the user's existing resume rather than asking the user to author Markdown manually.

## Source-of-truth rules

- `MASTER_PROFILE.md` contains truthful confirmed career facts only.
- `PROJECTS.md` stores what the user actually did, ownership/evidence, tools and outcomes; do not invent metrics.
- `TARGETS.md` stores intent and priority, not experience claims.
- `FILTERS.md` clearly separates **hard filters** from **soft risks**. A soft gap should not silently become a rejection rule.
- `ANSWERS.json` stores reusable application answers only when explicitly confirmed, including conditions/scope (for example travel <=30%).
- `ONBOARDING_STATE.json` is only a progress map. It must not override the underlying confirmed facts.

The default workflow computes a Career Profile digest from these files. If the profile/preferences change, previously cached job decisions are not blindly reused.

See `docs/CAREER_ONBOARDING.md` for the interviewing method and `CODEX_LOCAL.md` for the end-to-end job-search flow.
