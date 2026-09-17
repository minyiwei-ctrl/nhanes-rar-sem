# Pipeline

Numbered files are stages and run in order; unnumbered files are libraries
imported by the stages, or checkers run after them. `5_5` is an R script;
every other stage is a Jupyter notebook. Each notebook locates the project
root from its own position and reloads the project modules on its first
cell, so it can be run from any working directory; restart the kernel after
editing a library.

## Stages

| stage | input | output |
|---|---|---|
| `1_check_files` | `data/raw/` | verifies that every NHANES file the pipeline reads is present; stops with the list of any that are missing |
| `3_merge_personlevel` | NHANES questionnaire, examination and accelerometer day-summary files | participant-day file, both cycles pooled |
| `4_paday_cf_sl_paq_dp_personlevel` | participant-day file | one row per participant; NHANES missing codes applied; PHQ-9 total; cognitive sub-test scores; sleep duration; sex and education recodes |
| `4_5_biomarker_merge` | laboratory files, participant master | biomarker panel; systemic immune-inflammation index and its log |
| `5_accelerometer_RAR` | `PAXMIN` minute files | valid-wear classification; relative amplitude, interdaily stability, intradaily variability; activity volume. Reads about 26 GB of CSV and takes hours |
| `5_5_compute_kdm_ba` (R) | biomarker panel | Klemera–Doubal biological age and its advancement (BioAge package, internal calibration) |
| `5_6_data_screening` | analytic file | data screening before any model is fitted: range checks, then Supplementary Tables 17 (weighted correlations among the model variables), 18 (variance inflation factors) and 19 (distributions, extreme values, missingness, sample cascade) |
| `6_descriptives` | analytic file | Table 1; Supplementary Tables 1, 2, 13 |
| `7_iv_to_mediators` | analytic file | Supplementary Table 14 (weighted least squares, rhythm → biological measures) |
| `8_iv_to_outcomes` | analytic file | Supplementary Table 15 (weighted least squares, total and direct associations) |
| `9_mplus_prep` | analytic file | Mplus data files and their column manifests |
| — | `cd 9_mplus_models && bash run_all.sh` | runs the 51 Mplus models (Mplus 9 required) |
| `10_mplus_parse_fig234` | Mplus `.out` files | Tables 2 and 3; Figures 2–4; Supplementary Figure 5; Supplementary Tables 3–7 and 20 (unadjusted against adjusted estimates, from the `m_*_crude` models); then runs every checker below |
| `11_age_moderation` | analytic file | Supplementary Table 8; Supplementary Figure 1 |
| `12_RAR_dimension_specificity` | analytic file | Supplementary Table 9; Supplementary Figure 2 |
| `13_GAM_nonlinearity` | analytic file | Supplementary Table 10; Supplementary Figure 3 |
| `14_main_fig1` | analytic file, Mplus outputs | Figure 1; Supplementary Table 12; Supplementary Figure 4 |
| `16_kdm_outlier_sensitivity` | analytic file | Supplementary Table 11; the trimmed Mplus data file and inputs |
| `17_kdm_component_specificity` | analytic file | Supplementary Table 16 (marker-level associations; decomposition of the index) |
| `18_variance_decomposition` | analytic file | Supplementary Figure 6 (unique variance per predictor, permutation reference) |

Gaps in the numbering are deliberate: `2` and `15` are not part of the
published pipeline.

## Libraries

| module | provides | imported by |
|---|---|---|
| `config.py` | paths to `data/raw`, the two cycle folders and `data/processed`; `raw_file()`, which finds a raw NHANES file whatever the case of its name | `1`, `3`, `4_5`, `5` |
| `rar_core.py` | accelerometer ingest and the rest–activity rhythm numerics | `5` |
| `wls_utils.py` | survey-weighted least squares with HC3 errors; natural cubic spline basis; exact t, χ² and F distributions | `5_6`, `6`–`8`, `11`–`13`, `16`–`18` |
| `nature_palette.py` | one colour per rhythm metric; age-group labels; number format | every figure- or table-producing stage |
| `mplus_parse.py` | Mplus `.out` files → tidy tables of estimates, effects and fit | `7`, `10`, `17` |
| `mplus_export.py` | effect decomposition, Holm adjustment, indirect/total ratio | `10`, `17` |
| `mplus_report.py` | builds every display item derived from the Mplus output; the engine behind stage `10` and also runnable on its own (`python mplus_report.py`) | `10` |

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
| `verify_citations.py` | every display item is cited in the manuscript body and every citation resolves to an item on disk; skipped where the manuscript drafts are not present |
| `_validate_rar_core.py` | asserts the rest–activity numerics in `rar_core.py` against analytically known answers on synthetic profiles |

Headless equivalent of stage `10`:

```bash
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
