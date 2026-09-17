# Data

No data are distributed with this repository. Every file the pipeline reads
is a public NHANES release, and every file it writes is rebuilt from those.

## What to download

From https://wwwn.cdc.gov/nchs/nhanes/ , for each of the two cycles
(2011–2012, suffix `_G`; 2013–2014, suffix `_H`), place the SAS transport
files in `data/raw/2011-2012/` and `data/raw/2013-2014/`. File names are
matched without regard to case, so `DEMO_G.XPT` and `demo_g.xpt` are both
found.

| component | file | read by |
|---|---|---|
| Demographics | `DEMO` | script 3 |
| Cognitive functioning | `CFQ` | script 3 |
| Sleep disorders | `SLQ` | script 3 |
| Mental health – depression screener | `DPQ` | script 3 |
| Physical activity questionnaire | `PAQ` | script 3 |
| Physical activity monitor – day summary and header | `PAXDAY`, `PAXHD` | script 3 |
| Body measures | `BMX` | script 3 |
| Complete blood count | `CBC` | script 4_5 |
| Standard biochemistry profile | `BIOPRO` | script 4_5 |
| Glycohemoglobin | `GHB` | script 4_5 |
| Total cholesterol | `TCHOL` | script 4_5 |
| Plasma fasting glucose; fasting questionnaire; urine albumin and creatinine | `GLU`, `FASTQX`, `ALB_CR` | script 4_5 — optional: carried into the master file, used by no analysis, skipped if absent |

The two minute-level accelerometer files `PAXMIN_G` and `PAXMIN_H` (SAS
transport, about 8 and 9 GB) go directly in `data/raw/`, not in the cycle
folders. Script 5 converts each to CSV once (about 26 GB together) and reads
the CSVs after that.

Script `1_check_files.ipynb` verifies that every file above is present
before anything runs. `scripts/config.py` holds the folder paths and is the
only place they are defined.

## What the pipeline writes here

| path | written by | contents |
|---|---|---|
| `data/csv_files/` | script 5 | the two PAXMIN files as CSV |
| `data/processed/` | scripts 3–5_5 | participant-day file → participant master → analytic file `8_nhanes_analytic.csv` |
| `data/mplus/` | script 9 | `nhanes_sem.dat` and its variants, with column manifests |

All of these are excluded from version control by `.gitignore`.
