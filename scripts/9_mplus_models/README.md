# Mplus models

One `.inp` per model, 51 in all. `run_all.sh` runs them through Mplus and
writes a `.out` beside each; `scripts/mplus_parse.py` reads the `.out` files
and `scripts/mplus_report.py` builds the tables and figures from them. The
`.out` files are not in the repository. Model roles are decoded from the
file stem in `mplus_parse.label_models()`.

The inputs read `../../data/mplus/nhanes_sem.dat` (script 9) and, for the
trimmed models, `nhanes_sem_trimmed.dat` (script 16); `run_all.sh` changes
into this directory first so that the relative path resolves.

## Generated set

Written by `build_inputs.py` from one template. Edit the template and
regenerate rather than editing these `.inp` files directly.

```
python build_inputs.py            # write
python build_inputs.py --check    # verify only
```

### Mediation models: `m_{outcome}_{cell}_{exposure}[_vol].inp`

18 files: 3 exposures (IV, IS, RA) x 3 cells x with/without volume adjustment.
Each fits the parallel two-mediator model exposure -> (KDM-BA advancement,
log SII) -> outcome, with `MODEL INDIRECT` and the derived quantities
`ind_BA`, `ind_SII`, `total_ind`, `total`, `prop_BA` and `prop_SII`.

| cell | subpopulation | sample |
|---|---|---|
| `dep_young` | AGE60 EQ 0 | depression (PHQ-9), 18-59 |
| `dep_old` | AGE60 EQ 1 | depression (PHQ-9), 60+ |
| `cog_old` | AGE60 EQ 1 | cognition (latent factor of three tests), 60+; NHANES administers the cognitive battery only at 60+ |

The `dep_young` / `dep_old` pair varies age while holding the outcome fixed.

`_vol` adds total daily activity volume (total MIMS) as a covariate to all three
equations. Both versions are reported.

### Unadjusted counterparts: `m_{outcome}_{cell}_{exposure}_crude.inp`

9 files, one per primary model (STROBE item 16a). Identical to the primary
model except that no equation contains a covariate. Because Mplus drops a
participant only when a variable *in the model* is missing, removing the
covariates would otherwise admit participants the adjusted model excluded;
these inputs read `nhanes_sem_covok.dat` (script 9), which adds `COVOK` = 1
when all six covariates are observed, and add `COVOK EQ 1` to the
`SUBPOPULATION` statement (`SUBPOPULATION = AGE60 EQ 0 AND COVOK EQ 1`).
Mplus does not allow `USEOBSERVATIONS` together with `SUBPOPULATION`, and
domain analysis is the correct subsetting under `TYPE = COMPLEX`; the
participants outside the domain contribute nothing to the estimates, and
because none of the 61 sampling units is emptied by the covariate exclusion,
the design-based standard errors are computed on the same structure as in
the adjusted model. Each unadjusted model therefore has exactly the n of its
counterpart, which `mplus_report` asserts before writing Supplementary Table
S20. Weights, strata, PSU, the residual covariance between the biological
measures, the latent cognition specification, `MODEL INDIRECT` and the
derived quantities are unchanged. Reported alongside the adjusted estimates
in Supplementary Table S20 and used for no inference.

### Interaction models: `x_age_{exposure}[_vol].inp`

6 files. The a1 equation alone (KDM-BA advancement on the exposure), with an
exposure x age product and simple slopes at -1 s.d., mean and +1 s.d. of age.
The interaction coefficient tests whether the a1 association changes with age.

## Hand-written set

These files are not produced by `build_inputs.py`.

- `x_age_sii_{exposure}[_vol].inp` (6 files): the interaction model with log
  SII as the dependent variable (the a2 path).
- `M1_*` (IV) and `S3_*` (IS, RA): the mediation model without age
  stratification. The depression versions pool all adults 18+ and are
  reported as secondary (age-unstratified); the cognition versions are
  restricted to 60+ (`SUBPOPULATION = AGE60 EQ 1`).
- `S2_*_ivquint` and `S2_*_raquint`: the exposure entered as quintiles
  (`IV_Q` in `nhanes_sem.dat`, `RA_Q` in `nhanes_sem_raq.dat`, scored 1-5).
  Reported as sensitivity analyses.
- `S1_*_trimmed`: participants beyond the 0.5th or 99.5th percentile of
  KDM biological age excluded (`SUBPOPULATION = KDMOUT EQ 0` on
  `nhanes_sem_trimmed.dat`). Reported as sensitivity analyses (script 16).

The cognition models `M1_cognition` and `S3_cognition_{is,ra}` are the same
specification as `m_cog_old_{iv,is,ra}`; `mplus_export.flag_duplicates()`
detects this from the estimates and downstream tables count them once.

## Notes that apply to every model

- `l1 > 0` in the cognition models fixes the latent factor's orientation.
  `COG@1` identifies the factor only up to sign, so without the constraint the
  optimiser can return the mirror solution, flipping every sign on COG.
  `run_all.sh` flags any output with negative loadings.
- `CINTERVAL` gives delta-method intervals. Bootstrap is unavailable under
  `TYPE = COMPLEX` with weights; `TECH3` (the parameter covariance matrix) is
  saved so that Monte Carlo intervals can be built from it.
- Mplus deletes cases listwise on exogenous variables (exposure and
  covariates); FIML applies only to dependent variables. Roughly a quarter of
  adults are dropped, 79% of that because they have no accelerometry.

## P1: functional form, age interaction and education coding (2026-10-19)

`build_p1.py` writes `data/mplus/nhanes_sem_p1.dat` — `nhanes_sem.dat` plus
the three non-linear natural-spline functions of raw RA and raw IV (knots
fixed once on adults 20+: boundary 5th/95th percentiles, interior quartiles;
z-scored on that sample), quintile indicators with common cut-points, and
education indicators (DMDEDUC2 2–5 against less than 9th grade) — and 21
inputs: `p1_{ra,iv}_{linear,spline,spline_age,spline_age_nl,quint,quint_age}`
(dependent variable KDM-BA advancement, adults 20+, core covariates, with
`MODEL TEST` for the design-corrected joint Wald tests; age products formed
in `DEFINE`) and `m_*_edud` (the nine primary mediation models with the four
education indicators). Run them with `python mplus_run.py 'p1_*.inp'` and
`python mplus_run.py '*_edud.inp'` (stage 19, Step 2); `python ../p1_report.py`
then writes Supplementary Table S21. `build_p1.py --check` verifies that every
input's NAMES matches the data file.

## Stage 19: the sensitivity sets and `mplus_run.py` (2026-10-20)

Stage `19_sensitivity_mplus.ipynb` writes two more data files and three
folders of inputs, all derived from the P1 file, with the model set of each
fixed in a `plan.json` before anything is fitted (copies under
`result/qc/freeze/`):

| folder | written by | models | reads |
|---|---|---|---|
| `cycle_audit/` | `../build_cycle_audit.py` | 42 `adjusted_*` (a 2013–14 cycle indicator added to every structural regression of the 9 primary, 9 volume-adjusted, 6 age-interaction, 6 volume-adjusted age-interaction and 12 P1 models); 12 `cycleG_x_age_*` / `cycleH_x_age_*` (cycle-specific age-interaction models); 18 `cycleG_m_*` / `cycleH_m_*` split-cycle full SEMs, generated for the record but **retired and not run** (eight carried design-rank warnings in the F1 freeze) | `nhanes_sem_cycle.dat` (P1 file + `CYCLE2`, 48 columns) |
| `cycle_contrasts/` | `../build_cycle_contrasts.py` | 12 `cycle_diff_{young,old}_{ba_adv,sii_log}_{ra,is,iv}`: pooled single-outcome regressions in which the exposure, every covariate slope and the intercept differ by cycle; `MODEL TEST` on the exposure × cycle term (1 df) | `nhanes_sem_cycle.dat` |
| `selection_audit/` | `../build_selection_audit.py` | 3 `cc_m_cog_old_*`: the primary cognition models restricted to participants with every modelled variable observed (`SUBPOPULATION = AGE60 EQ 1 AND CC_x EQ 1`) | `nhanes_sem_selection.dat` (P1 file + `CC_RA`, `CC_IS`, `CC_IV`) |

`mplus_run.py` replaces `run_all.sh` for these models (and can run any
input here). It runs one input at a time, accepts the output only when
`mplus_output_qc.validate_output` passes, archives a previous output under
`_previous_runs/`, keeps a rejected output as `.failed.out`, stops at the
first failure, and writes a `.run.json` beside the input with the sha256 of
the input, the data file and the output. The reports (`../p1_report.py`,
`../freeze_sensitivity_report.py`) read outputs only through
`mplus_output_qc.read_verified`, which re-checks those hashes, so a stale,
edited or failed output cannot enter a table.

```
python mplus_run.py --record '*.inp'                 # bind the existing baseline outputs (no run)
python mplus_run.py 'p1_*.inp'                       # 12
python mplus_run.py '*_edud.inp'                     #  9
python mplus_run.py 'cycle_audit/adjusted_*.inp'     # 42
python mplus_run.py 'cycle_audit/cycle?_x_age_*.inp' # 12
python mplus_run.py 'cycle_contrasts/*.inp'          # 12
python mplus_run.py 'selection_audit/*.inp'          #  3
```

`--record` exists because the 51 baseline outputs of the unified re-run were
produced by `run_all.sh`, which writes no record, while
`freeze_sensitivity_report.py` reads each baseline through `read_verified`
to compare it with its variants. It validates every existing output with
the same `validate_output` gate and writes the record with
`recorded_post_hoc = true` and the run date from the Mplus header; it runs
nothing and alters no output.
