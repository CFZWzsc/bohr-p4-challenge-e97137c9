# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-e97137c9` (track: `deep-research-literature-review`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `deep-research-evidence-review`
- Summary: "面向文献综述与深度研究的证据链工作流：把研究问题拆成子问题，逐条收集来源与段落证据，将每条论断绑定到可核验的 locator 与原文引句，显式保留冲突与覆盖缺口，并输出 result.json、report.md 与 run-review.md。适用于给定文献/材料批次的系统筛选、证据矩阵与带引用综述；不联网、不补造文献。"

## Contents

| File |
|------|
| `SKILL.md` |
| `assets/policy.json` |
| `examples/demo-case/case.json` |
| `examples/quickstart.md` |
| `references/claim-evidence-binding.md` |
| `references/conflicts-and-coverage.md` |
| `references/research-protocol.md` |
| `scripts/run_skill.py` |
| `scripts/sk_analyze.py` |
| `scripts/sk_entry.py` |
| `scripts/sk_ingest.py` |
| `scripts/sk_render.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
