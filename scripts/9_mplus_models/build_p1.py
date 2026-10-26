"""P1: design-corrected functional-form, age-interaction and education-coding
models in Mplus. Writes the data file and the inputs; Mplus runs them.

    python build_p1.py            # write data/mplus/nhanes_sem_p1.dat and the inputs
    python build_p1.py --check    # verify the data file against the inputs, write nothing

Then, from this directory:  bash run_all.sh 'p1_*.inp' && bash run_all.sh '*_edud.inp'
and from scripts/:          python p1_report.py   (Supplementary Table S21)

What is fitted, all with TYPE = COMPLEX, MLR, the NHANES weight / strata /
PSU, SUBPOPULATION = ADULT20 EQ 1 (the analysis population), the same
covariates as the primary models and KDM-BA advancement as the dependent
variable — the leg of the structural models whose age heterogeneity the
paper discusses:

  p1_{x}_linear        BA_ADV ON x + covariates               (reference line)
  p1_{x}_spline        + the three non-linear natural-spline functions of x;
                       MODEL TEST: the three = 0 (3-df Wald, design-corrected)
  p1_{x}_spline_age    + AGE and the four products x*AGE, N3*AGE, N4*AGE, N5*AGE;
                       MODEL TEST: all four age interactions = 0 (4 df)
  p1_{x}_spline_age_nl the same model; MODEL TEST: the three non-linear
                       interactions = 0 (3 df), i.e. does age modify the shape
  p1_{x}_quint         quintile indicators Q2-Q5 of x (common cut-points) + covariates
  p1_{x}_quint_age     + AGE and the four Q*AGE products; MODEL TEST: the four = 0
  m_{...}_edud         the nine primary mediation models with education entered
                       as four indicators (EDU2-EDU5, reference: less than 9th
                       grade) instead of the single 1-5 term

for x in RA, IV. The spline basis is the natural cubic spline of
wls_utils.ns_basis (Hastie et al., ESL eq. 5.4-5.5) in the RAW metric, with
boundary knots at the 5th and 95th percentiles and three interior knots at
the quartiles (25th, 50th, 75th percentiles) of the metric, all computed once on the
analysis population with the metric observed (adults 20+), so every P1
model uses one pre-specified basis; the three non-linear columns are
z-scored on the same sample (an affine change that does not alter the
tests). Quintile cut-points are likewise common to every model. The x*AGE
products use the z-scored x and AGE already in the file; the other products
are formed in Mplus DEFINE from the file's columns.
"""
import hashlib
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
BASE = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
from wls_utils import ns_basis                      # noqa: E402
from population import ADULT_MIN_AGE                 # noqa: E402
import build_inputs as bi                            # noqa: E402

MPLUS = BASE / 'data' / 'mplus'
DAT_IN = MPLUS / 'nhanes_sem.dat'
MAN_IN = MPLUS / 'nhanes_sem_vars.txt'
DAT_OUT = MPLUS / 'nhanes_sem_p1.dat'
MAN_OUT = MPLUS / 'nhanes_sem_p1_vars.txt'
ANALYTIC = BASE / 'data' / 'processed' / '8_nhanes_analytic.csv'
DAT_REL = '../../data/mplus/nhanes_sem_p1.dat'

EXPOSURES = ('RA', 'IV')
NEW_COLS = (['RA_N3', 'RA_N4', 'RA_N5', 'IV_N3', 'IV_N4', 'IV_N5']
            + ['RA_Q2', 'RA_Q3', 'RA_Q4', 'RA_Q5', 'IV_Q2', 'IV_Q3', 'IV_Q4', 'IV_Q5']
            + ['EDU2', 'EDU3', 'EDU4', 'EDU5'])


def manifest_columns(p):
    return [m.group(2) for l in p.read_text().splitlines() for m in [re.match(r'#\s*(\d+)\s+(\w+)\s*$', l)] if m]


def build_data():
    cols = manifest_columns(MAN_IN)
    dat = pd.read_csv(DAT_IN, sep=r'\s+', header=None, names=cols, na_values=['-9999', '-9999.000'])
    raw = pd.read_csv(ANALYTIC, low_memory=False, usecols=['SEQN', 'RIDAGEYR', 'RA', 'IV', 'DMDEDUC2'])
    d = dat.merge(raw, on='SEQN', how='left', suffixes=('', '_raw'))
    assert len(d) == len(dat)
    pop = (d.RIDAGEYR >= ADULT_MIN_AGE)
    notes = []
    for x in EXPOSURES:
        v = d[f'{x}_raw'].astype(float)
        m = pop & v.notna()
        xx = v[m].values
        # knots on the analysis population, applied to everyone with the metric
        b_lo, b_hi = np.quantile(xx, [0.05, 0.95])
        knots = np.quantile(xx, np.clip(np.linspace(0, 1, 5)[1:-1], 0.06, 0.94))
        B_all = np.full((len(d), 4), np.nan)
        obs = v.notna().values
        B_all[obs] = ns_basis(v[obs].values, df=4, knots=knots, boundary=(b_lo - 1e-6, b_hi + 1e-6))
        for k, name in enumerate([f'{x}_N3', f'{x}_N4', f'{x}_N5']):
            col = B_all[:, k + 1]
            mu, sd = np.nanmean(col[m.values]), np.nanstd(col[m.values])
            d[name] = (col - mu) / sd
        notes.append(f'#   {x}: boundary knots {b_lo:.4f}, {b_hi:.4f}; interior knots '
                     + ', '.join(f'{k:.4f}' for k in knots) + f' (raw {x}; n = {int(m.sum()):,})')
        # common-cut-point quintiles within the analysis population
        q = pd.qcut(v[m], 5, labels=False) + 1
        edges = np.quantile(xx, [0.2, 0.4, 0.6, 0.8])
        qi = pd.Series(np.nan, index=d.index); qi[m] = q
        for k in (2, 3, 4, 5):
            d[f'{x}_Q{k}'] = np.where(qi.isna(), np.nan, (qi == k).astype(float))
        notes.append(f'#   {x} quintile cut-points: ' + ', '.join(f'{e:.4f}' for e in edges))
    e = d['DMDEDUC2'].astype(float)
    for k in (2, 3, 4, 5):
        d[f'EDU{k}'] = np.where(e.isna(), np.nan, (e == k).astype(float))
    # cross-check: the common-cut quintile score equals the file's IV_Q where both exist
    iv_score = sum(k * d[f'IV_Q{k}'] for k in (2, 3, 4, 5)).where(d['IV_Q2'].notna())
    iv_score = iv_score.where(iv_score > 0, 1.0)
    both = d['IV_Q'].notna() & iv_score.notna()
    mism = int((d.loc[both, 'IV_Q'] != iv_score[both]).sum())
    out = d[cols + NEW_COLS].copy()
    out = out.fillna(-9999)
    fmt = {c: '%d' for c in ('SEQN', 'STRATUM', 'PSU', 'SEX', 'AGE60', 'ADULT20')}
    with open(DAT_OUT, 'w') as f:
        for _, row in out.iterrows():
            f.write(' '.join((fmt.get(c, '%.6f') % row[c]) if row[c] != -9999 else '-9999' for c in out.columns) + '\n')
    sha = hashlib.sha256(DAT_OUT.read_bytes()).hexdigest()
    (MPLUS / 'nhanes_sem_p1.dat.sha256').write_text(f'{sha}  nhanes_sem_p1.dat\n')
    lines = ['# Mplus variable manifest for nhanes_sem_p1.dat (P1 functional-form models)',
             f'# nhanes_sem.dat ({len(cols)} columns, same rows and order) plus:',
             '#   {x}_N3 {x}_N4 {x}_N5  non-linear natural-spline functions of raw x (ESL eq. 5.4-5.5), z-scored on adults 20+',
             '#   {x}_Q2..{x}_Q5        quintile indicators of raw x, cut-points common to every model (adults 20+)',
             '#   EDU2..EDU5            education indicators (DMDEDUC2 = 2..5; reference = 1, less than 9th grade)',
             '# Products with AGE (x*AGE from the file; N_k*AGE and Q_k*AGE in Mplus DEFINE) use the z-scored AGE of the file.',
             *notes,
             f'# IV_Q check: common-cut quintile score equals the file IV_Q in all but {mism} of {int(both.sum()):,} rows.',
             '# Column order:']
    lines += [f'#  {i:3d}  {c}' for i, c in enumerate(out.columns, 1)]
    MAN_OUT.write_text('\n'.join(lines) + '\n')
    print(f'wrote {DAT_OUT.name}: {len(out):,} rows x {len(out.columns)} columns; sha256 {sha[:12]}')
    print('\n'.join(notes))
    return list(out.columns)


# ------------------------------------------------------------------ inputs
HEAD = """TITLE:
    {title}

DATA:
    FILE = {dat};

VARIABLE:
    NAMES =
        {names};

    USEVARIABLES =
        {usevars};

    MISSING = ALL(-9999);

    SUBPOPULATION = ADULT20 EQ 1;

    IDVARIABLE = SEQN;

    STRATIFICATION = STRATUM;
    CLUSTER        = PSU;
    WEIGHT         = WT4YR;
{define}
ANALYSIS:
    TYPE        = COMPLEX;
    ESTIMATOR   = MLR;
    INFORMATION = OBSERVED;

MODEL:
{model}
{test}
OUTPUT:
    STDYX CINTERVAL TECH1;
"""
COVS = 'AGE SEX BMI EDU WEAR_T SLEEP_H'
COVS_NOAGE = 'SEX BMI EDU WEAR_T SLEEP_H'


def wrap_names(cols):
    out, line = [], []
    for c in cols:
        line.append(c)
        if len(' '.join(line)) > 60:
            out.append(' '.join(line)); line = []
    if line:
        out.append(' '.join(line))
    return '\n        '.join(out)


def p1_inputs(cols):
    names = wrap_names(cols)
    files = {}
    for x in EXPOSURES:
        N = [f'{x}_N3', f'{x}_N4', f'{x}_N5']
        Q = [f'{x}_Q2', f'{x}_Q3', f'{x}_Q4', f'{x}_Q5']
        # linear reference
        files[f'p1_{x.lower()}_linear'] = HEAD.format(
            title=f'P1 {x}: linear a1 equation, BA_ADV on {x} + covariates, adults 20+',
            dat=DAT_REL, names=names, usevars=f'{x} BA_ADV\n        {COVS}', define='',
            model=f'    BA_ADV ON {x} (b1)\n              {COVS};', test='')
        # spline vs linear
        files[f'p1_{x.lower()}_spline'] = HEAD.format(
            title=f'P1 {x}: natural-spline a1 equation; MODEL TEST = non-linear terms jointly zero (3 df)',
            dat=DAT_REL, names=names, usevars=f'{x} {" ".join(N)} BA_ADV\n        {COVS}', define='',
            model=(f'    BA_ADV ON {x} (b1)\n              {N[0]} (b3)\n              {N[1]} (b4)\n              {N[2]} (b5)\n'
                   f'              {COVS};'),
            test='\nMODEL TEST:\n    b3 = 0;\n    b4 = 0;\n    b5 = 0;\n')
        # spline x age
        prods = [f'{x}N{k}AGE' for k in (3, 4, 5)]
        define = ('\nDEFINE:\n' + ''.join(f'    {p} = {n}*AGE;\n' for p, n in zip(prods, N)))
        usev = f'{x} {" ".join(N)} {x}_AGE AGE BA_ADV\n        {COVS_NOAGE}\n        {" ".join(prods)}'
        model = (f'    BA_ADV ON {x} (b1)\n              {N[0]} (b3)\n              {N[1]} (b4)\n              {N[2]} (b5)\n'
                 f'              AGE (g_age)\n              {x}_AGE (i1)\n'
                 + ''.join(f'              {p} (i{k})\n' for k, p in zip((3, 4, 5), prods))
                 + f'              {COVS_NOAGE};')
        files[f'p1_{x.lower()}_spline_age'] = HEAD.format(
            title=f'P1 {x}: spline a1 equation with age interactions; MODEL TEST = all four x-by-age terms zero (4 df)',
            dat=DAT_REL, names=names, usevars=usev, define=define, model=model,
            test='\nMODEL TEST:\n    i1 = 0;\n    i3 = 0;\n    i4 = 0;\n    i5 = 0;\n')
        files[f'p1_{x.lower()}_spline_age_nl'] = HEAD.format(
            title=f'P1 {x}: spline a1 equation with age interactions; MODEL TEST = the three non-linear age terms zero (3 df)',
            dat=DAT_REL, names=names, usevars=usev, define=define, model=model,
            test='\nMODEL TEST:\n    i3 = 0;\n    i4 = 0;\n    i5 = 0;\n')
        # quintile indicators (common cut-points), with and without age interaction
        files[f'p1_{x.lower()}_quint'] = HEAD.format(
            title=f'P1 {x}: quintile indicators (common cut-points, reference Q1) on BA_ADV + covariates, adults 20+',
            dat=DAT_REL, names=names, usevars=f'{" ".join(Q)} BA_ADV\n        {COVS}', define='',
            model='    BA_ADV ON ' + ' '.join(Q) + f'\n              {COVS};', test='')
        qprods = [f'{x}Q{k}AGE' for k in (2, 3, 4, 5)]
        define = ('\nDEFINE:\n' + ''.join(f'    {p} = {q}*AGE;\n' for p, q in zip(qprods, Q)))
        model = ('    BA_ADV ON ' + ' '.join(Q) + '\n              AGE (g_age)\n'
                 + ''.join(f'              {p} (q{k})\n' for k, p in zip((2, 3, 4, 5), qprods))
                 + f'              {COVS_NOAGE};')
        files[f'p1_{x.lower()}_quint_age'] = HEAD.format(
            title=f'P1 {x}: quintile indicators with age interactions; MODEL TEST = the four Q-by-age terms zero (4 df)',
            dat=DAT_REL, names=names, usevars=f'{" ".join(Q)} AGE BA_ADV\n        {COVS_NOAGE}\n        {" ".join(qprods)}',
            define=define, model=model,
            test='\nMODEL TEST:\n    q2 = 0;\n    q3 = 0;\n    q4 = 0;\n    q5 = 0;\n')
    return files


def edu_inputs(cols):
    """The nine primary mediation models with education as four indicators."""
    names = wrap_names(cols)
    covs = 'AGE SEX BMI EDU2 EDU3 EDU4 EDU5 WEAR_T SLEEP_H'
    files = {}
    for exp in ('IV', 'IS', 'RA'):
        for outcome, cell in (('dep', 'young'), ('dep', 'old'), ('cog', 'old')):
            y_use, meas, y = bi.OUTCOMES[outcome]
            subpop, cell_lab = bi.CELLS[cell]
            stem = f'm_{outcome}_{cell}_{exp.lower()}_edud'
            usevars = f'{exp} BA_ADV SII_LOG\n        {y_use}\n        {covs}'
            text = bi.TEMPLATE.format(
                title=f'{exp} -> (KDM-BA, log SII) -> {y}, {cell_lab}, education as four indicators (P1)',
                dat=DAT_REL, names=names, usevars=usevars,
                subpop=f'\n    {subpop}\n', starts='\n    STARTS      = 20;' if outcome == 'cog' else '',
                measurement=f'    {meas}\n\n' if meas else '', exp=exp, y=y,
                covs_m=f'\n               {covs}', covs_y=f'\n           {covs}',
                orient=bi.ORIENT if outcome == 'cog' else '', stem=stem)
            files[stem] = text
    return files


def check(cols):
    ncol = len(DAT_OUT.read_text().splitlines()[0].split())
    ok = ncol == len(cols)
    print(f'{DAT_OUT.name}: {ncol} columns; manifest {len(cols)} -> {"OK" if ok else "MISMATCH"}')
    n = 0
    for f in sorted(HERE.glob('p1_*.inp')) + sorted(HERE.glob('*_edud.inp')):
        names = re.search(r'NAMES\s*=\s*(.*?);', f.read_text(), re.S).group(1).split()
        if names != cols:
            print('  NAMES mismatch:', f.name); ok = False
        n += 1
    print(f'{n} inputs checked')
    return ok


def main():
    if '--check' in sys.argv:
        cols = manifest_columns(MAN_OUT)
        return 0 if check(cols) else 1
    cols = build_data()
    files = p1_inputs(cols); files.update(edu_inputs(cols))
    for stem, text in files.items():
        (HERE / f'{stem}.inp').write_text(text)
    print(f'wrote {len(files)} inputs: ' + ', '.join(sorted(files)))
    return 0 if check(cols) else 1


if __name__ == '__main__':
    raise SystemExit(main())
