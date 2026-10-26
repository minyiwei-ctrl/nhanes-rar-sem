# Pipeline

Numbered files are stages and run in order; unnumbered files are libraries
imported by the stages, or checkers run after them. `5_5` is an R script;
every other stage is a Jupyter notebook. Each notebook locates the project
root from its own position and reloads the project modules on its first
cell, so it can be run from any working directory; restart the kernel after
editing a library.

The analysis population is adults aged 20 years and over; the age limit and
the two age cells (20–59, 60+) are defined once, in `population.py`, and
every stage from `5_6` onwards imports them. The limit applies to the
association analyses only: the Klemera–Doubal calibration (`5_5`) and the
Mplus data files (`9`) keep every adult, and the Mplus models declare the
population through `SUBPOPULATION` so that the survey design is unchanged.

## Stages

| stage | input | output |
|---|---|---|
| `1_check_files` | `data/raw/` | verifies that every NHANES file the pipeline reads is present; stops with the list of any that are missing |
| `3_merge_personlevel` | NHANES questionnaire, examination and accelerometer day-summary files | participant-day file, both cycles pooled |
| `4_paday_cf_sl_paq_dp_personlevel` | participant-day file | one row per participant; NHANES missing codes applied; PHQ-9 total; cognitive sub-test scores; sleep duration; sex and education recodes |
| `4_5_biomarker_merge` | laboratory files, participant master | biomarker panel; systemic immune-inflammation index and its log |
| `5_accelerometer_RAR` | `PAXMIN` minute files | valid-wear classification; relative amplitude, interdaily stability, intradaily variability (full time series; the superseded composite-profile ratio is kept as `IV_profile_legacy` for audit only); activity volume. Steps 1–3 read about 26 GB of CSV and take hours; Step 4 recomputes every rhythm metric from the saved hourly grid (`7_hourly_by_day.npz`) in minutes and is the entry point after a change to `rar_core.py` |
| `5_5_compute_kdm_ba` (R) | biomarker panel | Klemera–Doubal biological age and its advancement (BioAge package, internal calibration) |
| `5_6_data_screening` | analytic file | data screening before any model is fitted: range checks, then Supplementary Tables 17 (weighted correlations among the model variables), 18 (variance inflation factors) and 19 (distributions, extreme values, missingness, sample cascade) |
| `6_descriptives` | analytic file | Table 1; Supplementary Tables 1, 2, 13 |
| `7_iv_to_mediators` | analytic file | Supplementary Table 14 (weighted least squares, rhythm → biological measures) |
| `8_iv_to_outcomes` | analytic file | Supplementary Table 15 (weighted least squares, total and direct associations) |
| `9_mplus_prep` | analytic file | Mplus data files and their column manifests: all adults with the `ADULT20` population flag, and the `_covok` file (plus `COVOK`) for the unadjusted counterparts |
| — | `cd 9_mplus_models && bash run_all.sh` | runs the 51 Mplus models (Mplus 9 required) |
| `10_mplus_parse_fig234` | Mplus `.out` files | Tables 2 and 3; Figures 2–4; Supplementary Figure 5; Supplementary Tables 3–7 and 20 (unadjusted against adjusted estimates, from the `m_*_crude` models); then runs every checker below |
| `11_age_moderation` | analytic file | Supplementary Table 8; Supplementary Figure 1 |
| `12_RAR_dimension_specificity` | analytic file | Supplementary Table 9; Supplementary Figure 2 |
| `13_GAM_nonlinearity` | analytic file | Supplementary Table 10 (spline tests of linearity by outcome and cell; linearity of the relative-amplitude associations on the quintile scale); Supplementary Figure 3 |
| `14_main_fig1` | analytic file, Mplus outputs | Figure 1; Supplementary Table 12; Supplementary Figure 4 |
| `16_kdm_outlier_sensitivity` | analytic file | Supplementary Table 11; the trimmed Mplus data file and inputs |
| `17_kdm_component_specificity` | analytic file | Supplementary Table 16 (marker-level associations; decomposition of the index) |
| `18_variance_decomposition` | analytic file | Supplementary Figure 6 (unique variance per predictor, permutation reference) |
| `19_sensitivity_mplus` | analytic file, stage-`9` data file, the 51 baseline Mplus outputs | Step 1 writes the sensitivity data files and inputs (`9_mplus_models/build_p1.py` → `nhanes_sem_p1.dat`, 12 `p1_*` + 9 `m_*_edud`; `build_cycle_audit.py` → `nhanes_sem_cycle.dat`, `cycle_audit/` 42 cycle-adjusted + 12 cycle-specific age models (+18 retired split-cycle SEMs, not run); `build_cycle_contrasts.py` → `cycle_contrasts/` 12 pooled contrasts; `build_selection_audit.py` → `nhanes_sem_selection.dat`, `selection_audit/` 3 complete-case cognition models). Step 2 (outside Jupyter): `9_mplus_models/mplus_run.py`, 90 models, each bound to its input and data by a `.run.json` record; `--record` binds the existing baseline outputs. Step 3: `p1_report.py` → Supplementary Table 21; `freeze_sensitivity_report.py` → Supplementary Tables 22 (survey cycle) and 23 (cognitive availability, complete case). Step 4: registries and checkers (Mplus 9 required) |

Gaps in the numbering are deliberate: `2` and `15` are not part of the
published pipeline. Stage `16` reads only the analytic file and the stage-`9`
data file, so when the whole chain is re-run it can go before the Mplus
models; all 51 models then run in one pass and stage `10` once. Stage `19`
comes last: its reports compare every sensitivity model with the baseline
output it qualifies, and nothing in it changes a primary result. Its model
sets were fixed before fitting and are recorded in the `plan.json` of each
model folder.

## Libraries

| module | provides | imported by |
|---|---|---|
| `config.py` | paths to `data/raw`, the two cycle folders and `data/processed`; `raw_file()`, which finds a raw NHANES file whatever the case of its name | `1`, `3`, `4_5`, `5` |
| `population.py` | the analysis population (adults aged 20 and over) and the age-cell keys | `5_6`–`18`, `nature_palette`, `mplus_parse`, `mplus_report` |
| `rar_core.py` | accelerometer ingest and the rest–activity rhythm numerics | `5` |
| `wls_utils.py` | survey-weighted least squares with HC3 errors; natural cubic spline basis; exact t, χ² and F distributions | `5_6`, `6`–`8`, `11`–`13`, `16`–`18` |
| `nature_palette.py` | one colour per rhythm metric; age-group labels; number format | every figure- or table-producing stage |
| `mplus_parse.py` | Mplus `.out` files → tidy tables of estimates, effects and fit | `7`, `10`, `17` |
| `mplus_export.py` | effect decomposition, Holm adjustment, indirect/total ratio | `10`, `17` |
| `mplus_report.py` | builds every display item derived from the Mplus output; the engine behind stage `10` and also runnable on its own (`python mplus_report.py`) | `10` |
| `mplus_output_qc.py` | `validate_output` (normal termination, trustworthy standard errors, input echo identical to the input file, expected Wald df, positive cognition loadings) and `read_verified` (an output is read only with a PASS `.run.json` whose input, data and output sha256 match) | `9_mplus_models/mplus_run.py`, `p1_report`, `freeze_sensitivity_report` |
| `build_cycle_audit.py`, `build_cycle_contrasts.py`, `build_selection_audit.py` | the stage-`19` model builders: cycle-adjusted and cycle-specific variants, pooled cycle contrasts, complete-case cognition models, each with its plan fixed before fitting (`plan.json`, `result/qc/freeze/`) | `19` |
| `p1_report.py`, `freeze_sensitivity_report.py` | the stage-`19` reports: Supplementary Tables 21, 22 and 23 from verified outputs, with the full numerical audit under `result/qc/freeze/` | `19` |

Manuscript numbering of figures and tables is defined once, in
`mplus_report.FIGNUM` and `TABNUM`; stage `10` asserts that the set of items
produced matches those registries.

After editing a library, re-run the stages listed in its "imported by"
column. A change confined to `mplus_parse`, `mplus_export` or `mplus_report`
needs only stage `10`.

## Checkers

Each exits non-zero on a defect; stage `10` runs all of them in its last cell.

| checker | checks |
|---|---|
| `verify_figures.py` | every figure is a vector PDF with embedded TrueType fonts and a 600-dpi PNG, at most 183 mm wide, with a source-data workbook; no orphaned source data |
| `display_map.py` | every display item maps to exactly one producing stage; no orphans, duplicates or missing files (`--write` refreshes `DISPLAY_ITEMS.md`) |
| `variable_dictionary.py` | every variable in the Mplus files has a definition; every documented variable exists; quoted thresholds equal the constants in `rar_core.py` and the R script (`--write` refreshes `VARIABLES.md`) |
| `captions.py` | every display item has a title, and its caption is assembled from the item's own Notes or legend sheet (`--write` refreshes `CAPTIONS.md`) |
| `verify_citations.py` | every display item is cited in the manuscript body and every citation resolves to an item on disk; reads the Markdown drafts, or a Word file given on the command line (`python verify_citations.py manuscript/EJE/<file>.docx`); skipped where neither is present |
| `_validate_rar_core.py` | asserts the rest–activity numerics in `rar_core.py` against analytically known answers on synthetic profiles, including the full-series intradaily variability under missing hours and missing days |
| `_validate_mplus_parse.py` | asserts, on fixtures in the Mplus 9 layout, that every reported 95% interval is read from the 2.5% / 97.5% columns and that the interaction term equals the difference of the simple slopes in the unstandardised solution |
The tools below work on the archived results and the manuscript during
revision; they are kept locally and are not in the public repository.

| local tool | does |
|---|---|
| `_check_rerun.py` | stage gates for a re-run against an archived state (`_archive_*/`): after notebook 5 Step 4, the R script, notebook 9 and `run_all.sh`, each gate PASSes, FAILs or is SKIPped (step not yet run); only what was meant to change may change |
| `compare_with_archive.py` | after a re-run: every estimate, interval and p of the current Mplus outputs against an archived state (`_archive_*/`), with the reason for each difference → `result/qc/Comparison_with_archive.xlsx` |
| `docx_redline.py`, `manuscript_stageC_edits.py` | the Stage C revision of the Word manuscript as tracked changes (`python manuscript_stageC_edits.py IN.docx OUT.docx`): paragraph-level text decisions, Tables 1–3 rewritten from `result/main`, the four figures re-embedded; validated with the docx tooling |
| `build_supplement_word.py` | the Supplementary Materials Word file from the current tables and figures (`python build_supplement_word.py`): Supplementary Methods 1–5, the STROBE table carried over, Tables S1–S20 (S21–S23 once stage `19` has written them) from `result/supplementary`, Figures S1–S6, titles from `captions.TITLES` and notes from `build_supplementary_captions_data.ITEMS` |
| `manuscript_provenance.py` | every number quoted in the manuscript prose, resolved from the archived and the current result tables (old value, new value, source cell, required text change) → `result/qc/Manuscript_provenance.xlsx`; `manuscript_numbers.py MANUSCRIPT.docx` is the untargeted version that looks every numeric token of a Word file up in the tables |

Headless equivalent of stage `10`:

```bash
python _validate_rar_core.py
python _validate_mplus_parse.py
python mplus_report.py
python verify_figures.py
python display_map.py --write
python variable_dictionary.py --write
python captions.py --write
python verify_citations.py
```

A stage notebook can be run without opening Jupyter:

```bash
jupyter nbconvert --to notebook --execute --inplace 6_descriptives.ipynb
```
