# Career Onboarding for Codex

The user should not be asked to manually fill a long profile form. Codex should conduct a conversational interview, starting from any resume the user provides and only asking for missing or ambiguous facts.

## Private outputs

Write all real personal information under ignored `career/private/` only:

```text
career/private/
  MASTER_PROFILE.md
  TARGETS.md
  FILTERS.md
  PROJECTS.md
  STORIES.md
  ANSWERS.json
  resumes/
```

Never commit these files.

## Interview method

1. If a resume exists, read it first and extract only stated facts.
2. Build a gap list instead of asking the user to repeat known information.
3. Ask one small, concrete question at a time. Prefer prompts like “你说从研发做到量产，具体包含 recipe / DOE / release / matching 中哪些？” over “请描述你的工作经历”.
4. Convert conversational answers into structured career facts, but never embellish or invent metrics.
5. Ask follow-ups for evidence: ownership, scope, tools, measurable outcome, production impact, troubleshooting examples, collaboration, and 0-to-1 work.
6. Separate fact from preference. “做过 X” belongs in profile/projects; “不想做外包” belongs in filters.
7. For uncertain or sensitive screening answers, ask the user instead of guessing.

## Minimum profile domains

- identity/contact fields needed for applications
- education
- employment history with dates
- projects and accomplishments
- skills with evidence and confidence
- target roles and target cities
- salary/notice/travel/relocation preferences when the user chooses to provide them
- links/portfolio
- reusable ATS screening answers

## Reusable ATS answers

`ANSWERS.json` may store user-confirmed reusable answers such as notice period, travel willingness, relocation, sponsorship, work authorization, portfolio links, and common application questions. Store the answer plus scope/conditions so Codex does not overgeneralize it.

Example:

```json
{
  "travel": {
    "answer": true,
    "max_percentage": 30,
    "confirmed_by_user": true
  }
}
```

If a later form asks for 70% travel, the stored 30% preference is not enough; ask again.

## Completion behavior

Onboarding does not need to reach 100% before job discovery. Start once core resume, target city, and target-role information are sufficient. During job review or official ATS filling, if a new information gap appears, pause only that job, ask the smallest necessary question, store the confirmed answer locally, and resume.
