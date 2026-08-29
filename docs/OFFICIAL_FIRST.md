# Official-first application workflow

Recruiting platforms are primarily discovery, fallback and recruiter-communication sources. When the same selected job is reliably verified on the employer's own Careers/ATS system, prefer the official route for the resume submission.

## Resolution policy

1. Discover and initially filter jobs first; do not open official sites for obviously rejected jobs.
2. Deduplicate obvious platform copies into one canonical job while preserving all source URLs.
3. For selected/promising jobs, find the employer's exact Careers/ATS requisition.
4. Only write an official match when evidence is strong:

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

5. Run:

```bash
jobagent-official prepare --input <review.json>
```

At confidence >= 0.80 with evidence, the item becomes `preferred_channel=official`; otherwise it is represented as `fallback_platform` and is **not** claimed as an official browser form.

A canonical job gets one resume submission. If official succeeds, suppress duplicate platform resume submission. A separately approved BOSS recruiter follow-up may still be useful and must be represented explicitly as `platform_action=message_only` in final review.

## ATS routing

Known hosts are classified as Greenhouse, Lever, Ashby, Workday, SmartRecruiters, iCIMS, Jobvite, Oracle/Taleo, SAP SuccessFactors, Moka or Beisen. Unknown official forms remain `generic_official` and should be handled by Codex Browser instead of guessed selectors.

An ATS label is only a routing hint. CAPTCHA, SMS, identity checks, legal declarations, novel screening questions and ambiguous fields require user help where appropriate.

## Browser queue limits

Hard defaults:

```text
max open tabs         = 4
max active form tabs  = 2
max final submits     = 1
```

Claim form slots with:

```bash
jobagent-official claim --queue <official-queue.json> --kind form
```

Only `preferred_channel=official` items with a verified `official_url` and `status=queued` can be claimed. Platform fallback items never consume official form slots.

Close/release a tab when an item is finished, failed, skipped or moved to fallback before claiming more. A job paused for user input can be `human_required`; avoid keeping many heavy ATS tabs alive when the question can be recorded and resumed later.

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

Final submit is always serial. The queue rejects a second simultaneous `submitting` job.

## Final-review authorization

Form research/filling may occur before final approval, but a final Submit/Apply cannot.

After the user has seen the complete consolidated `FINAL_REVIEW.md`, authorize the official subset:

```bash
jobagent-official review --queue <official-queue.json> --approve
```

Partial approval uses repeated `--key` values.

The authorization digest binds the **reviewed application materials**, including:

- canonical job/company/title/city
- official URL and ATS route
- fallback sources
- score/risks shown to the user
- resume variant
- material screening answers
- any proposed platform follow-up action

Execution status is intentionally **not** part of the digest. Therefore normal transitions such as `queued -> filling -> submitting -> submitted` do not invalidate approval. Changing a reviewed URL, resume choice, screening answer, route, risk/material or approved job does invalidate it and requires another final review.

This distinction is important: approval should survive execution progress, but never survive a changed application plan.

## Resolver rules for Codex

Do not assume the first web result is official. Prefer links reachable from the verified employer domain or a clearly employer-branded ATS tenant. Verify company, title/role, location and JD similarity. If confidence is weak, leave `official_url` unset and use the platform fallback.

Do not create duplicate applications merely because an official title differs slightly. Compare company + normalized role/title + city + JD. Preserve all source URLs under `sources` so another recruiting platform remains available if one fallback breaks.

## Privacy

All candidate/application state is local. Personal data and screening answers belong only under `career/private/` or `.jobagent-local/`. Never commit them.
