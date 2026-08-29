# Official-first application workflow

This fork treats recruiting platforms primarily as discovery and recruiter-communication sources. When the same job can be verified on the employer's official Careers/ATS site, the official route is preferred for resume submission.

## Channel policy

1. Discover jobs from Boss / Liepin / Zhilian / 51Job.
2. Codex deduplicates obvious cross-platform copies into one canonical job.
3. For selected/review jobs, Codex searches for the employer's official Careers page or ATS posting.
4. Codex writes these fields into `review.json` only after verification:

```json
{
  "official_url": "https://...",
  "official_match_confidence": 0.94,
  "official_evidence": {
    "company_match": true,
    "title_match": true,
    "location_match": true,
    "jd_match": "high"
  }
}
```

5. Run `jobagent-official prepare --input <review.json>`.
6. If confidence is >= 0.80 and evidence exists, `preferred_channel=official`; otherwise the recruiting platform remains the fallback channel.
7. A canonical job is submitted only once. A successful official submission blocks duplicate resume submission on Boss/Liepin/Zhilian/51Job, while recruiter communication may still be used when appropriate.

## ATS routing

Known host patterns are classified as Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Jobvite, Oracle/Taleo, SAP SuccessFactors, Moka, or Beisen. Unknown official forms are `generic_official` and should be handled by Codex Browser rather than guessed selectors.

The ATS label is a routing hint, not proof that automation is safe. CAPTCHA, SMS, identity checks, legal declarations, novel screening questions, or ambiguous form fields require user help.

## Browser queue and tab limits

The queue has hard defaults:

- max open browser tabs: **4**
- max simultaneous application/form tabs: **2**
- max simultaneous final submissions: **1**

Use:

```bash
jobagent-official claim --queue <official-queue.json> --kind form
```

Only claimed jobs may be opened as active application forms. Finish, park as `human_required`, or fail one before claiming more when the cap is reached.

Final submission is always serial. Before clicking a final Submit/Apply button, mark the item `submitting`; the queue rejects a second simultaneous `submitting` item.

## State machine

```text
queued
  -> claimed
  -> filling
  -> human_required (optional)
  -> ready_to_submit
  -> submitting
  -> submitted

or

  -> failed
  -> fallback_platform
```

Use `jobagent-official update` after meaningful transitions. Close the browser tab once a job reaches `submitted`, `failed`, `skipped`, or `fallback_platform` unless it is intentionally kept for recruiter communication.

## Official resolver rules for Codex

Do not assume the first search result is official. Prefer links reachable from the employer's verified corporate domain or an ATS posting clearly branded for that employer. Verify company, role/title, location, and JD similarity. If the evidence is weak, leave `official_url` unset and use the recruiting platform.

Do not create a duplicate application merely because the official title differs slightly. Compare company + normalized title + city + JD. If it is probably the same requisition, keep one canonical record and preserve every source URL under `sources`.

## Personal information

All candidate data is local only. The first Codex run should conduct Career Onboarding and write private files under `career/private/`. Do not commit them.
