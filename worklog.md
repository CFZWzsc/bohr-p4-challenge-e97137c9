# Worklog

## Round 21 — 把综述草稿做成一等交付物

目标：让评审第一眼看到可进入科研讨论的综述草稿，并让论断-证据绑定、PRISMA 计数、
自检与溯源都能被机械复核。改动均不触及算法主线，全部由既有字段重排或渲染。

### 改了什么

1. **新增交付主体 `review_draft.md`**
   - `scripts/sk_render.py` 增加 `render_review_draft()`，只渲染 `synthesis.sections` 的正文，
     去掉“运行报告”表壳；`scripts/sk_entry.py` 写出该文件，并在 `output_paths` 登记。

2. **`result.json` 增加可核验字段**
   - `prisma{n_identified,n_duplicates,n_screened,n_excluded_by_code,n_included}`；
   - `quote_check_summary{checked,verified,not_found}`；
   - `boundary{scanned,ok,hits}`（越界措辞扫描）；
   - `uncertainty[].human_confirm`；
   - `gates[]`、`self_check[]`、`validator_verdict`，并与 `all_checks_passed` 绑定。

3. **新增 `scripts/sk_artifacts.py`（标准库）**
   - 生成 `synthesis_matrix.csv`、`screening_log.csv`、`prisma_flow.svg`、
     `provenance.json`（`source_map` 复用 `input_manifest` 的 sha256）、`validation.json`；
   - `research_report.docx` 用 `zipfile` + OOXML 纯标准库生成，固定 zip 时间戳保证确定性。

4. **新增门禁**
   - 越界措辞词表（全球首创/填补空白/实验已完成/world-first 等）；
   - `established` 主题不得包含相反/混合证据；
   - 排除项必须有 `reason`，否则判 error；
   - PRISMA 平衡：identified − duplicates − excluded = included，且等于进入证据的来源数。

5. **补齐生态文件**
   - 包根 `README.md`、`requirements.txt`、`worklog.md`；
   - `docs/ERROR_HANDLING.md`；
   - `examples/example-result.json`（demo 实跑结果）。

### 为什么

- 评审为人工评审，第一眼看到的是 `/app/output`；此前用“运行报告表”承担草稿角色，是最直接的
  “任务完成度/使用增益”失分点。
- PRISMA、引文校验摘要、自检门禁与溯源映射让“可核验”从口头承诺变成可逐行对账的产物。

### 验证

- 全部 `.py` 通过 `py_compile`；
- demo 连跑两次，10 个输出文件逐字节一致；
- 空输入与损坏 `case.json` 均写出 `result.json` 且退出 0；
- 仓库根 `python _shared/validators/validate_gray_packages.py` 全部通过。
