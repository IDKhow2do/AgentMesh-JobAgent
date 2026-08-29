# Local career profile

This directory documents the private inputs Codex may use for the local-only workflow.

Do **not** commit real personal data. Put actual files under `career/private/`, which is ignored by Git.

Recommended layout:

```text
career/private/
├── resume.pdf
├── PROFILE.md
├── TARGETS.md
└── FILTERS.md
```

`PROFILE.md` should contain only truthful evidence Codex may use when matching a JD: work experience, projects, tools, domain knowledge, education, and other resume-backed strengths.

`TARGETS.md` should contain target roles, target cities, optional salary expectations, preferred company types, and priority ordering.

`FILTERS.md` should distinguish hard filters from soft risks. For example:

```text
Hard filters
- roles the user never wants
- cities the user cannot accept
- employment types the user rejects

Soft risks
- years-of-experience gap
- skill gaps that may be learnable
- degree preference rather than strict requirement
```

Codex should read these files before scoring jobs and must never invent missing experience to improve a match score.
