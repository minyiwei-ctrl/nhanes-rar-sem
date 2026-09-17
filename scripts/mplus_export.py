"""Reshaping and inference helpers for the parsed Mplus results (library; no main()).

    mplus_parse.py    .out files   -> tidy frames
    mplus_export.py   tidy frames  -> tables, Holm, mediation proportion
    mplus_report.py   the above    -> QC / main / supplementary workbooks + figures
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from mplus_parse import parse_dir, label_models

BASE = Path(__file__).resolve().parent.parent
MODELS = BASE / 'scripts' / '9_mplus_models'



def fmt_p(p):
    if pd.isna(p):
        return ''
    return '<0.001' if p < 0.001 else f'{p:.3f}'


def fmt_ci(e, lo, hi, dp=3):
    # The sign convention (minus kept, plus omitted) is defined once, in nature_palette.
    from nature_palette import fmt_ci as _fmt_ci
    if pd.isna(e):
        return ''
    return _fmt_ci(e, None if pd.isna(lo) else lo,
                   None if pd.isna(hi) else hi, dp)


def load():
    est, eff, info = parse_dir(MODELS)
    info = label_models(info)
    return est, eff, flag_duplicates(est, info)


# Reshaping
PATHS = [('a1', 'BA_ADV ON', 'exposure', 'exposure -> KDM-BA advancement'),
         ('a2', 'SII_LOG ON', 'exposure', 'exposure -> log SII'),
         ('b1', 'OUTCOME ON', 'BA_ADV', 'KDM-BA advancement -> outcome'),
         ('b2', 'OUTCOME ON', 'SII_LOG', 'log SII -> outcome'),
         ('c_prime', 'OUTCOME ON', 'exposure', 'direct effect')]


def path_table(est, info):
    """One row per model per structural path, STDYX."""
    s = est[est.solution == 'STDYX']
    rows = []
    for _, m in info.iterrows():
        if m.family == 'interaction':
            continue
        y = 'COG' if m.outcome == 'cognition' else 'PHQ9'
        exp = m.exposure
        for name, sec, par, desc in PATHS:
            sec_r = sec.replace('OUTCOME', y)
            par_r = exp if par == 'exposure' else par
            r = s[(s.model == m.model) & (s.section == sec_r) & (s.parameter == par_r)]
            if not len(r):
                continue
            r = r.iloc[0]
            rows.append(dict(model=m.model, family=m.family, role=m.role,
                             is_duplicate=m.is_duplicate, duplicate_of=m.duplicate_of,
                             outcome=m.outcome, age_cell=m.age_cell,
                             exposure=exp, volume_adjusted=m.volume_adjusted,
                             n=int(m.n), path=name, description=desc,
                             beta=r.estimate, ci_lo=r.ci_lo, ci_hi=r.ci_hi, p=r.p))
    return pd.DataFrame(rows)


def effect_table(eff, info):
    s = eff[eff.solution == 'STDYX'].merge(
        info[['model', 'family', 'role', 'outcome', 'age_cell', 'exposure',
              'volume_adjusted', 'n', 'is_duplicate', 'duplicate_of']],
        on='model', how='left')
    s['label'] = s.effect + s.via.apply(lambda v: f' via {v}' if pd.notna(v) else '')
    return s[s.family != 'interaction']


def interaction_table(est, info):
    s = est[est.solution == 'STDYX']
    u = est[est.solution == 'unstandardized']
    rows = []
    for _, m in info[info.family == 'interaction'].iterrows():
        exp = m.exposure
        # The moderation family has two possible dependent variables; read the
        # section the model fits.
        dv = 'SII_LOG ON' if m.outcome == 'log SII' else 'BA_ADV ON'
        main = s[(s.model == m.model) & (s.section == dv) & (s.parameter == exp)]
        inter = s[(s.model == m.model) & (s.section == dv) & (s.parameter == f'{exp}_AGE')]
        # Mplus truncates parameter names to 8 characters, so SLOPE_MID appears
        # as SLOPE_MI and total_ind as TOTAL_IN. Match on the truncation.
        slopes = {p: u[(u.model == m.model) & (u.parameter == p[:8].upper())]
                  for p in ('SLOPE_LO', 'SLOPE_MID', 'SLOPE_HI')}
        row = dict(model=m.model, exposure=exp, outcome=m.outcome,
                   volume_adjusted=m.volume_adjusted, n=int(m.n))
        for lab, df in [('main_effect', main), ('interaction', inter)]:
            if len(df):
                d = df.iloc[0]
                row |= {f'{lab}_beta': d.estimate, f'{lab}_lo': d.ci_lo,
                        f'{lab}_hi': d.ci_hi, f'{lab}_p': d.p}
        for lab, df in slopes.items():
            if len(df):
                d = df.iloc[0]
                row |= {f'{lab}_beta': d.estimate, f'{lab}_lo': d.ci_lo,
                        f'{lab}_hi': d.ci_hi, f'{lab}_p': d.p}
        rows.append(row)
    return pd.DataFrame(rows)



def flag_duplicates(est, info):
    """Mark models that are the same specification run under two names."""
    # Fingerprint: n, a1 and b1 rounded to four decimals. The generated
    # m_cog_old_{iv,is,ra} models and the hand-written M1_cognition /
    # S3_cognition_{is,ra} models are the same specification.
    s = est[est.solution == 'STDYX']
    fp = {}
    for _, m in info.iterrows():
        if m.family == 'interaction':
            continue
        y = 'COG' if m.outcome == 'cognition' else 'PHQ9'
        a1 = s[(s.model == m.model) & (s.section == 'BA_ADV ON') & (s.parameter == m.exposure)]
        b1 = s[(s.model == m.model) & (s.section == f'{y} ON') & (s.parameter == 'BA_ADV')]
        if len(a1) and len(b1):
            fp[m.model] = (int(m.n), round(a1.iloc[0].estimate, 4),
                           round(b1.iloc[0].estimate, 4))

    groups = {}
    for k, v in fp.items():
        groups.setdefault(v, []).append(k)

    dup_of, canonical = {}, {}
    for members in groups.values():
        if len(members) < 2:
            continue
        # keep the generated name as canonical; it carries the age cell explicitly
        keep = sorted(members, key=lambda m: (not m.startswith('m_'), m))[0]
        for m in members:
            canonical[m] = keep
            if m != keep:
                dup_of[m] = keep

    info = info.copy()
    info['duplicate_of'] = info.model.map(dup_of)
    info['is_duplicate'] = info.duplicate_of.notna()
    return info


# Holm adjustment and mediation proportion
def holm(pvals):
    """Holm-Bonferroni adjusted p-values, order preserved."""
    p = np.asarray(pvals, dtype=float)
    ok = np.isfinite(p)
    out = np.full(p.shape, np.nan)
    idx = np.argsort(p[ok])
    m = ok.sum()
    adj, prev = np.empty(m), 0.0
    for i, j in enumerate(idx):
        prev = max(prev, min(1.0, p[ok][j] * (m - i)))
        adj[j] = prev
    out[ok] = adj
    return out


def indirect_with_holm(effects):
    """Indirect effects per model, with Holm applied across the two mediators within each model."""
    d = effects[(effects.effect == 'indirect') & (~effects.is_duplicate)].copy()
    d['p_holm'] = np.nan
    for model, g in d.groupby('model'):
        d.loc[g.index, 'p_holm'] = holm(g.p.values)
    d['survives_holm'] = d.p_holm < 0.05
    return d.sort_values(['outcome', 'age_cell', 'exposure', 'volume_adjusted', 'via'])


def mediation_proportion(est, effects):
    """prop_BA / prop_SII per model, with `proportion` set to NaN where the ratio is uninterpretable."""
    u = est[est.solution == 'unstandardized']
    rows = []
    for model, g in effects[~effects.is_duplicate].groupby('model'):
        tot = g[g.effect == 'total']
        if not len(tot):
            continue
        tot = tot.iloc[0]
        for par, med in [('PROP_BA', 'BA_ADV'), ('PROP_SII', 'SII_LOG')]:
            r = u[(u.model == model) & (u.parameter == par[:8])]
            ind = g[(g.effect == 'indirect') & (g.via == med)]
            if not len(r) or not len(ind):
                continue
            r, ind = r.iloc[0], ind.iloc[0]

            # Suppression rule, in order of precedence: total effect p >= 0.05,
            # indirect effect p >= 0.05, or opposite signs (inconsistent
            # mediation). raw_ratio keeps the value in every case.
            if tot.p >= 0.05:
                why = 'total effect not significant'
            elif ind.p >= 0.05:
                why = 'indirect effect not significant'
            elif np.sign(ind.estimate) != np.sign(tot.estimate):
                why = 'inconsistent mediation: indirect opposes the total effect'
            else:
                why = None

            ok = why is None
            rows.append(dict(
                model=model, outcome=tot.outcome, age_cell=tot.age_cell,
                exposure=tot.exposure, volume_adjusted=tot.volume_adjusted,
                # family and is_duplicate let a consumer separate primary
                # models from sensitivity ones.
                family=tot.family, is_duplicate=tot.is_duplicate,
                mediator=med,
                total_effect=tot.estimate, total_p=tot.p,
                indirect_effect=ind.estimate, indirect_p=ind.p,
                proportion=r.estimate if ok else np.nan,
                prop_lo=r.ci_lo if ok else np.nan,
                prop_hi=r.ci_hi if ok else np.nan,
                prop_p=r.p if ok else np.nan,
                raw_ratio=r.estimate,
                reported='yes' if ok else f'suppressed: {why}'))
    return pd.DataFrame(rows)
