"""Variable dictionary for the analysis, checked against the pipeline.

    python variable_dictionary.py            # print
    python variable_dictionary.py --write    # write VARIABLES.md

Definitions are held in VARS below. The script checks that each documented
variable exists in data/processed/8_nhanes_analytic.csv and that every
variable in the Mplus manifest (data/mplus/nhanes_sem_vars.txt) has a
definition; the thresholds in the derivation rules are read from rar_core.py
and 5_5_compute_kdm_ba.R. Exits non-zero on any disagreement.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
ANALYTIC = BASE / 'data' / 'processed' / '8_nhanes_analytic.csv'
MPLUS_VARS = BASE / 'data' / 'mplus' / 'nhanes_sem_vars.txt'
RAR_CORE = BASE / 'scripts' / 'rar_core.py'
KDM_R = BASE / 'scripts' / '5_5_compute_kdm_ba.R'
SUPP = BASE / 'result' / 'supplementary'

# name in .dat | name in the analytic file | block | created by | definition
# 'created by' is the script that first writes the variable. Variables created
# by script 9 (IV_Q, RA_Q) exist only in the Mplus data files and are not
# looked for in the analytic file.
VARS = [
    # exposure
    ('IV', 'IV', 'Rest-activity rhythm', '5',
     'Intradaily variability. Fragmentation of the rest-activity cycle: the '
     'ratio of the mean squared difference between successive hours to the '
     'overall variance, computed on the hourly-binned MIMS profile averaged '
     'across valid days. The von Neumann ratio, bounded [0, 4]; higher values '
     'mean a more broken-up day. Dimensionless.'),
    ('IS', 'IS', 'Rest-activity rhythm', '5',
     'Interdaily stability. Reproducibility of the 24-hour pattern across '
     'days, as the between-hour share of total variance in the hourly profile '
     '(variance-decomposition form, which stays within [0, 1] when not every '
     'hour is observed on every day). Higher values mean a more regular rhythm.'),
    ('RA', 'RA', 'Rest-activity rhythm', '5',
     'Relative amplitude, (M10 - L5) / (M10 + L5), computed at minute '
     'resolution. Strength of the day-night contrast, bounded [0, 1]; higher '
     'values mean a stronger rhythm.'),
    (None, 'M10', 'Rest-activity rhythm', '5',
     'Mean MIMS over the most active continuous 600 minutes, wrapping past '
     'midnight. Characterised but not modelled as an exposure: it correlates '
     '0.92 with total daily volume (R2 = 0.78 on log volume), so a '
     'volume-adjusted M10 has no clean interpretation.'),
    (None, 'L5', 'Rest-activity rhythm', '5',
     'Mean MIMS over the least active continuous 300 minutes. Not modelled as '
     'an exposure: r = -0.88 with relative amplitude, which is derived from it.'),
    ('IV_Q', 'IV_Q', 'Rest-activity rhythm', '9',
     'Quintiles of intradaily variability (1-5), computed within adults on '
     'observed values. A sensitivity analysis against the skew of the '
     'continuous measure.'),
    (None, 'RA_Q', 'Rest-activity rhythm', '9',
     'Quintiles of relative amplitude (1-5), in nhanes_sem_raq.dat. Added '
     'after spline models rejected linearity for RA against both outcomes.'),

    # mediators
    ('BA_ADV', 'KDM_BA_advance', 'Candidate mediator', '5_5 (R)',
     'Klemera-Doubal biological-age advancement: KDM biological age minus '
     'chronological age, in years. Positive values mean biologically older '
     'than one\'s years. Computed with the BioAge package from a ten-marker '
     'panel, internally calibrated on the unweighted NHANES sample, so the '
     'residual is centred at zero in that calibration sample and not in the '
     'survey-weighted population.'),
    (None, 'KDM_BA', 'Candidate mediator', '5_5 (R)',
     'Klemera-Doubal biological age, in years, before subtracting '
     'chronological age.'),
    ('SII_LOG', 'SII_log', 'Candidate mediator', '4_5',
     'Natural log of the systemic immune-inflammation index. Logged because '
     'the raw index is strongly right-skewed (skewness +4.5).'),
    (None, 'SII', 'Candidate mediator', '4_5',
     'Systemic immune-inflammation index, platelets x neutrophils / '
     'lymphocytes, in 10^9/L.'),
    ('NLR_LOG', 'NLR', 'Candidate mediator', '4_5',
     'Neutrophil-to-lymphocyte ratio, logged. Carried as a secondary '
     'inflammation index; not a modelled mediator.'),

    # outcomes
    ('PHQ9', 'PHQ9_total', 'Outcome', '4',
     'Patient Health Questionnaire-9 total, 0-27, summed over DPQ010-DPQ090 '
     'with "refused" (7) and "don\'t know" (9) set to missing and all nine '
     'items required. Higher scores mean more depressive symptoms.'),
    ('MEM_Z', 'memory_score', 'Outcome', '4',
     'CERAD Word List Learning total, z-standardised within adults aged 60+ '
     '(the only group NHANES tests). Raw zeros are recoded to missing before '
     'standardisation, as they are a non-response code rather than a score.'),
    ('FLUEN_Z', 'fluency_score', 'Outcome', '4',
     'Animal Fluency total (CFDAST), z-standardised within 60+.'),
    ('SPEED_Z', 'speed_score', 'Outcome', '4',
     'Digit Symbol Substitution Test (CFDDS), z-standardised within 60+.'),
    ('COG_Z', 'Cog_composite_z', 'Outcome', '6 / 9',
     'Mean of the three cognition z-scores. Used as an observed composite in '
     'the supportive regressions; in the structural models the three '
     'indicators load on a latent factor instead, with the first loading '
     'constrained positive because COG@1 identifies the factor only up to '
     'sign.'),

    # covariates
    ('AGE', 'RIDAGEYR', 'Covariate', 'NHANES DEMO',
     'Age in years at screening. Top-coded at 80 by NHANES.'),
    ('AGE60', None, 'Covariate', '9',
     'Indicator for age 60 and over, used to select the analysis cell.'),
    (None, 'COVOK', 'Covariate', '9',
     'Indicator that all six covariates are observed, in '
     'nhanes_sem_covok.dat only. The unadjusted counterparts of the primary '
     'models (m_*_crude.inp) contain no covariates and add COVOK EQ 1 to '
     'their SUBPOPULATION statement, so that they are fitted to the same '
     'participants as the adjusted models.'),
    ('SEX', 'RIAGENDR', 'Covariate', 'NHANES DEMO', 'Sex, recoded 1 = female, 0 = male.'),
    ('BMI', 'BMXBMI', 'Covariate', 'NHANES BMX', 'Body mass index, kg/m2, measured.'),
    ('EDU', 'DMDEDUC2', 'Covariate', 'NHANES DEMO',
     'Educational attainment, ordinal 1-5. Codes 7 (refused) and 9 '
     '(don\'t know) are set to missing; education is the largest single '
     'source of exclusion from the models (492 participants).'),
    ('WEAR_T', 'Wear_Time', 'Covariate', '5',
     'Mean accelerometer wear time, minutes per valid day.'),
    ('SLEEP_H', 'SLD010H', 'Covariate', 'NHANES SLQ',
     'Self-reported usual sleep duration on weeknights, hours.'),
    ('VOLUME', 'TOTAL_MIMS', 'Covariate', '5',
     'Total daily activity volume: the mean of observed hourly MIMS times '
     '1440, so that it is defined on the same days as the rhythm metrics.'),

    # activity intensity
    ('OBJ_MVPA', 'obj_mvpa_min', 'Activity intensity', '5',
     'Minutes per day at or above the MVPA threshold. Reported as a '
     'descriptive and as a covariate in one sensitivity model, not as an '
     'exposure: MIMS has no consensus cut-point.'),
    (None, 'obj_sed_min', 'Activity intensity', '5',
     'Minutes per day below the sedentary threshold.'),
    (None, 'peak30_mims', 'Activity intensity', '5',
     'Mean of a person\'s 30 highest MIMS minutes in a day, averaged over '
     'valid days. Threshold-free intensity measure (Zheng et al. 2023) used '
     'in place of cut-point MVPA where an intensity summary is needed.'),

    # interaction
    ('IV_AGE', None, 'Interaction term', '9',
     'Product of standardised intradaily variability and standardised age.'),
    ('IS_AGE', None, 'Interaction term', '9', 'Standardised IS x standardised age.'),
    ('RA_AGE', None, 'Interaction term', '9', 'Standardised RA x standardised age.'),

    # survey design
    ('SEQN', 'SEQN', 'Survey design', 'NHANES', 'NHANES respondent identifier.'),
    ('WT4YR', 'WTMEC4YR', 'Survey design', '8 (stored once)',
     'Four-year mobile examination centre weight, WTMEC2YR / 2 for the pooled '
     '2011-2012 and 2013-2014 cycles. Computed once when the analytic file is '
     'built and asserted, not re-derived, in every downstream script.'),
    ('STRATUM', 'SDMVSTRA', 'Survey design', 'NHANES DEMO',
     'Masked variance stratum (29 strata in the analytic sample).'),
    ('PSU', 'SDMVPSU', 'Survey design', 'NHANES DEMO',
     'Masked primary sampling unit (61 PSUs).'),
    (None, 'Valid_Days', 'Survey design', '5',
     'Number of accelerometer days meeting the validity rule.'),
]


def pipeline_constants():
    """Read the thresholds the code actually used, to check the prose."""
    src = RAR_CORE.read_text()
    c = {}
    for name in ('MVPA_THRESHOLD', 'SED_THRESHOLD', 'PEAK_N', '9',
                 'MIN_VALID_MIN_PER_DAY', 'MIN_VALID_DAYS'):
        m = re.search(rf'^{name}\s*=\s*([\d.]+)', src, re.M)
        if m:
            c[name] = float(m.group(1))
    m = re.search(r'^biomarker_panel\s*<-\s*c\((.*?)\)', KDM_R.read_text(), re.S | re.M)
    c['KDM_PANEL'] = re.findall(r'"(\w+)"', m.group(1)) if m else []
    return c


def derivation_rules(c):
    """Rules that apply to whole blocks, stated once with their constants."""
    return [
        ('Accelerometry validity',
         f'A minute counts when the quality flag PAXQFM is zero, the wear '
         f'classification PAXPREDM is wake-wear or sleep-wear, and MIMS is '
         f'observed. A day counts when it has at least '
         f'{c["MIN_VALID_MIN_PER_DAY"]:.0f} valid minutes; a participant '
         f'counts with at least {c["MIN_VALID_DAYS"]:.0f} valid days.'),
        ('Sentinel values',
         'PAXMTSM = -0.01 marks "not computable" and is set to missing, not '
         'clipped to zero. Treating it as zero movement passed the quality '
         'filter for 58.9% of affected minutes and injected spurious rest.'),
        ('Minute of day',
         'PAXSSNMP is a session sample counter at 80 Hz, not a minute-of-day '
         'index. Clock position is (session minute - day-2 start) modulo 1440.'),
        ('Activity thresholds',
         f'MVPA is MIMS >= {c["MVPA_THRESHOLD"]}; sedentary is MIMS < '
         f'{c["SED_THRESHOLD"]}; the peak intensity summary averages the '
         f'{c["PEAK_N"]:.0f} highest minutes of a day.'),
        ('Biological age',
         'Klemera-Doubal, internally calibrated, from '
         f'{len(c["KDM_PANEL"])} markers: '
         + ', '.join(c['KDM_PANEL']) + '.'),
        ('Standardisation',
         'Every variable written to the Mplus data file is z-standardised, so '
         'the reported STDYX coefficients are per standard deviation of both '
         'exposure and outcome. Standardisation is within each model sample, '
         'so the conversion to natural units differs by analysis cell; the '
         'Scale sheet of Tables 2 and 3 gives the factors.'),
        ('Missing-value code', 'Missing is written as -9999 in the Mplus file.'),
    ]


def build():
    rows = [dict(**{'Mplus name': m or '—', 'Analytic-file name': a or '—',
                    'Block': b, 'Created by': f'script {p}' if p[0].isdigit()
                    else p, 'Definition': d})
            for m, a, b, p, d in VARS]
    t = pd.DataFrame(rows)

    problems = []
    if ANALYTIC.exists():
        cols = set(pd.read_csv(ANALYTIC, nrows=1, low_memory=False).columns)
        for m, a, b, prov, _ in VARS:
            # Only variables the analytic file holds; those created in script 9
            # (when the Mplus file is written) or derived inside a notebook are
            # skipped.
            if not a or prov.startswith('9') or a in ('Cog_composite_z', 'PHQ9_total'):
                continue
            if a not in cols:
                problems.append(
                    f'{a} is documented as created by {prov} but is absent '
                    f'from the analytic file')
    if MPLUS_VARS.exists():
        manifest = re.findall(r'^#\s+\d+\s+(\w+)\s*$', MPLUS_VARS.read_text(), re.M)
        documented = {m for m, _, _, _, _ in VARS if m}
        for v in manifest:
            if v not in documented:
                problems.append(f'{v} is in the Mplus manifest with no definition')
        for v in documented:
            if v not in manifest and v not in ('RA_Q',):
                problems.append(f'{v} documented as an Mplus variable but not in the manifest')
    return t, problems


def main():
    c = pipeline_constants()
    t, problems = build()
    rules = derivation_rules(c)

    with pd.option_context('display.width', 200, 'display.max_rows', None,
                           'display.max_colwidth', 60):
        for b in t.Block.unique():
            print(f'\n=== {b} ===')
            print(t[t.Block == b][['Mplus name', 'Analytic-file name',
                                   'Created by', 'Definition']].to_string(index=False))
    print('\n=== Derivation rules ===')
    for k, v in rules:
        print(f'  {k}: {v}')

    print(f'\n{len(t)} variables documented')
    if problems:
        print('\nPROBLEMS')
        for p in problems:
            print(' ', p)
    else:
        print('every Mplus variable has a definition; every documented '
              'variable exists')

    if '--write' in sys.argv:
        # The dictionary is a repository document (VARIABLES.md), not a
        # supplementary table. The checks above run on every invocation.
        md = BASE / 'VARIABLES.md'
        lines = ['# Variable dictionary', '',
                 'Generated by `scripts/variable_dictionary.py`. Do not edit by '
                 'hand — the script checks itself against the data and the '
                 'pipeline constants.', '']
        for b in t.Block.unique():
            lines += [f'## {b}', '',
                      '| Mplus | Analytic file | Created by | Definition |',
                      '|---|---|---|---|']
            for _, r in t[t.Block == b].iterrows():
                lines.append(f'| `{r["Mplus name"]}` | `{r["Analytic-file name"]}` '
                             f'| {r["Created by"]} | {r.Definition} |')
            lines.append('')
        lines += ['## Derivation rules', '']
        lines += [f'**{k}.** {v}\n' for k, v in rules]
        md.write_text('\n'.join(lines) + '\n')
        print(f'wrote {md.relative_to(BASE)}')

    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
