# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-e97137c9` (track: `deep-research-literature-review`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `screening-first-literature-review`
- Summary: Use when a batch of literature records must be turned into a cited narrative review, requiring explicit eligibility criteria applied before writing, recorded exclusion reasons, evidence-derived themes, a locatable quote table, per-paragraph citations and honest conflict and gap statements.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
