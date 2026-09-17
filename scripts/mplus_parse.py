"""Parse Mplus .out files into tidy tables.

    from mplus_parse import parse_dir
    est, eff, info = parse_dir('scripts/9_mplus_models')

Reads every .out file in a directory and returns three long-format frames:
parameter estimates, effect decompositions and per-model metadata.
"""
import re
from pathlib import Path

import pandas as pd

# Section cuts
def _slice(text, start, end=None):
    m = re.search(start, text, re.S)
    if not m:
        return ''
    rest = text[m.end():]
    if end:
        e = re.search(end, rest, re.S)
        if e:
            rest = rest[:e.start()]
    return rest


def _rows(block):
    """Yield (section, parameter, values) from a results block; headers are like `BA_ADV ON` or `Intercepts`."""
    section = None
    for line in block.split('\n'):
        s = line.strip()
        if not s:
            continue
        head = re.match(r'^([A-Z][A-Z0-9_]*)\s+(ON|BY|WITH)$', s)
        if head:
            section = f'{head.group(1)} {head.group(2)}'
            continue
        if re.match(r'^(Intercepts|Means|Variances|Residual Variances|'
                    r'New/Additional Parameters|Thresholds)$', s):
            section = s
            continue
        m = re.match(r'^([A-Za-z][\w.]*)\s+((?:-?\d+\.\d+\s*)+)$', s)
        if m and section:
            vals = [float(v) for v in m.group(2).split()]
            yield section, m.group(1), vals


def _est_block(text, standardized):
    if standardized:
        b = _slice(text, r'STANDARDIZED MODEL RESULTS\s*\n\s*STDYX Standardization',
                   r'\n\s*R-SQUARE')
    else:
        b = _slice(text, r'\nMODEL RESULTS\s*\n', r'STANDARDIZED MODEL RESULTS')
    return b


def _ci_block(text, standardized):
    if standardized:
        return _slice(text, r'CONFIDENCE INTERVALS OF STANDARDIZED MODEL RESULTS.*?STDYX Standardization',
                      r'CONFIDENCE INTERVALS OF (?:STANDARDIZED )?TOTAL')
    return _slice(text, r'CONFIDENCE INTERVALS OF MODEL RESULTS\s*\n',
                  r'CONFIDENCE INTERVALS OF STANDARDIZED')


# Estimates
def parse_estimates(text, model):
    """Parameter estimates with CIs, standardized and unstandardized."""
    out = []
    for std in (False, True):
        est = {(s, p): v for s, p, v in _rows(_est_block(text, std))}
        ci = {(s, p): v for s, p, v in _rows(_ci_block(text, std))}
        for key, v in est.items():
            if len(v) < 4:
                continue
            sec, par = key
            c = ci.get(key)
            out.append(dict(
                model=model, solution='STDYX' if std else 'unstandardized',
                section=sec, parameter=par,
                estimate=v[0], se=v[1], est_se=v[2], p=v[3],
                ci_lo=c[1] if c and len(c) >= 7 else None,
                ci_hi=c[5] if c and len(c) >= 7 else None))
    return out


# Effects
# Total, Total indirect and Sum of indirect carry their numbers on the same
# line. Direct is printed as "Direct", then the outcome, then the exposure,
# then the numbers, so it needs its own pattern.
_EFF_INLINE = [('total', r'Total'), ('total_indirect', r'Total indirect'),
               ('sum_indirect', r'Sum of indirect')]


def parse_effects(text, model):
    """Total / indirect / direct effects, plus each specific indirect path."""
    out = []
    for std in (True, False):
        if std:
            b = _slice(text, r'STANDARDIZED TOTAL, TOTAL INDIRECT.*?STDYX Standardization',
                       r'\n\s*CONFIDENCE INTERVALS')
            cb = _slice(text, r'CONFIDENCE INTERVALS OF STANDARDIZED TOTAL.*?STDYX Standardization',
                        r'\n\s*MODEL COMMAND|\Z')
        else:
            b = _slice(text, r'\nTOTAL, TOTAL INDIRECT, SPECIFIC INDIRECT, AND DIRECT EFFECTS\s*\n',
                       r'STANDARDIZED TOTAL')
            cb = _slice(text, r'CONFIDENCE INTERVALS OF TOTAL, TOTAL INDIRECT.*?\n',
                        r'CONFIDENCE INTERVALS OF STANDARDIZED TOTAL')
        sol = 'STDYX' if std else 'unstandardized'

        for name, pat in _EFF_INLINE:
            m = re.search(rf'^\s*{pat}\s+(-?[\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+([\d.]+)',
                          b, re.M)
            c = re.search(rf'^\s*{pat}\s+' + r'\s+'.join([r'(-?[\d.]+)'] * 7), cb, re.M)
            if m:
                out.append(dict(model=model, solution=sol, effect=name, via=None,
                                estimate=float(m.group(1)), se=float(m.group(2)),
                                p=float(m.group(4)),
                                ci_lo=float(c.group(2)) if c else None,
                                ci_hi=float(c.group(6)) if c else None))

        # Direct: label, outcome, exposure, then the numbers.
        m = re.search(r'\n\s*Direct\s*\n\s+\w+\s*\n\s+\w+\s+'
                      r'(-?[\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+([\d.]+)', b)
        c = re.search(r'\n\s*Direct\s*\n\s+\w+\s*\n\s+\w+\s+'
                      + r'\s+'.join([r'(-?[\d.]+)'] * 7), cb)
        if m:
            out.append(dict(model=model, solution=sol, effect='direct', via=None,
                            estimate=float(m.group(1)), se=float(m.group(2)),
                            p=float(m.group(4)),
                            ci_lo=float(c.group(2)) if c else None,
                            ci_hi=float(c.group(6)) if c else None))

        # Specific indirect blocks: outcome / mediator / exposure, then numbers
        seen = set()
        for m in re.finditer(r'Specific indirect \d+\s*\n\s+(\w+)\s*\n\s+(\w+)\s*\n\s+(\w+)'
                             r'\s+(-?[\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+([\d.]+)', b):
            med = m.group(2)
            if med in seen:
                continue
            seen.add(med)
            c = re.search(rf'Specific indirect \d+\s*\n\s+\w+\s*\n\s+{med}\s*\n\s+\w+\s+'
                          + r'\s+'.join([r'(-?[\d.]+)'] * 7), cb)
            out.append(dict(model=model, solution=sol, effect='indirect', via=med,
                            estimate=float(m.group(4)), se=float(m.group(5)),
                            p=float(m.group(7)),
                            ci_lo=float(c.group(3)) if c else None,
                            ci_hi=float(c.group(7)) if c else None))
    return out


# Header and fit statistics
_FIT = [('n', r'Number of observations\s+(\d+)'),
        ('free_parameters', r'Number of Free Parameters\s+(\d+)'),
        ('missing_patterns', r'Number of missing data patterns\s+(\d+)'),
        ('loglik', r'H0 Value\s+(-?[\d.]+)'),
        ('aic', r'Akaike \(AIC\)\s+([\d.]+)'),
        ('bic', r'Bayesian \(BIC\)\s+([\d.]+)'),
        ('chi2', r'Chi-Square Test of Model Fit\s*\n\s+Value\s+([\d.]+)'),
        ('chi2_df', r'Chi-Square Test of Model Fit\s*\n\s+Value\s+[\d.]+\*?\s*\n\s+Degrees of Freedom\s+(\d+)'),
        ('rmsea', r'RMSEA.*?Estimate\s+([\d.]+)'),
        ('rmsea_lo', r'90 Percent C\.I\.\s+([\d.]+)'),
        ('rmsea_hi', r'90 Percent C\.I\.\s+[\d.]+\s+([\d.]+)'),
        ('cfi', r'CFI\s+([\d.]+)'), ('tli', r'TLI\s+([\d.]+)'),
        ('srmr', r'SRMR.*?Value\s+([\d.]+)'),
        ('strata', r'Number of strata\s+(\d+)'),
        ('clusters', r'Number of clusters\s+(\d+)')]


def parse_info(text, model):
    info = dict(model=model)
    for k, pat in _FIT:
        m = re.search(pat, text, re.S)
        info[k] = float(m.group(1)) if m else None
    info['n_errors'] = len(re.findall(r'^\s*\*\*\*\s*ERROR', text, re.M))
    info['n_warnings'] = len(re.findall(r'^\s*\*\*\*\s*WARNING', text, re.M))

    # Factor orientation. COG@1 identifies the factor only up to sign; a mirror
    # solution flips every coefficient on COG.
    std = _est_block(text, True)
    loads = [v[0] for s, p, v in _rows(std) if s.endswith(' BY')]
    info['n_loadings'] = len(loads)
    info['loadings_positive'] = all(v > 0 for v in loads) if loads else None

    # R-square, one entry per dependent variable. Mplus prints an "Observed
    # Variable" sub-table and, when a factor is present, a "Latent Variable"
    # sub-table with the same column layout, so one pattern reads both. The
    # latent entry is the share of the factor's variance explained by its
    # structural predictors; it is reported in a separate column downstream.
    # R-square is the only fit-related quantity the saturated depression
    # models (zero degrees of freedom; no CFI, TLI or RMSEA) produce.
    blk = re.search(r'\nR-SQUARE\s*\n(.*?)(?=\n\n\n|\nQUALITY|\nTOTAL,|\Z)',
                    text, re.S)
    r2 = {}
    if blk:
        for m in re.finditer(r'^\s{4}([A-Z][A-Z0-9_]*)\s+([\d.]+)\s+[\d.]+'
                             r'\s+[\d.]+\s+([\d.]+)\s*$', blk.group(1), re.M):
            r2[m.group(1)] = float(m.group(2))
    info['r2_ba_adv'] = r2.get('BA_ADV')
    info['r2_sii_log'] = r2.get('SII_LOG')
    info['r2_outcome'] = r2.get('PHQ9', r2.get('COG'))
    info['r2_outcome_is_latent'] = 'COG' in r2 and 'PHQ9' not in r2
    return info


def parse_file(path):
    path = Path(path)
    text = path.read_text(errors='replace')
    model = path.stem
    return (parse_estimates(text, model), parse_effects(text, model),
            parse_info(text, model))


def parse_dir(d='.', pattern='*.out'):
    est, eff, info = [], [], []
    for f in sorted(Path(d).glob(pattern)):
        if f.stem.endswith(('_tech3', '_results')):
            continue
        e, x, i = parse_file(f)
        est += e
        eff += x
        info.append(i)
    return (pd.DataFrame(est), pd.DataFrame(eff), pd.DataFrame(info))


# Model labels
def label_models(info):
    """Decode each model stem into analysis attributes; an unrecognised stem raises ValueError."""
    def decode(stem):
        d = dict(family=None, outcome=None, age_cell=None, exposure=None,
                 volume_adjusted=None, role=None)
        if stem.startswith('m_'):
            _, out, cell, rest = stem.split('_', 3)
            # m_*_crude: the unadjusted counterpart of a primary model (no
            # covariates, same participants; STROBE item 16a). Labelled as a
            # sensitivity family so that primary() and the main tables and
            # figures never select it.
            crude = rest.endswith('_crude')
            rest = rest.replace('_crude', '')
            d.update(family='sensitivity' if crude else 'mediation',
                     outcome={'dep': 'PHQ-9', 'cog': 'cognition'}[out],
                     age_cell={'young': '18-59', 'old': '60+'}[cell],
                     exposure=rest.replace('_vol', '').upper(),
                     volume_adjusted=rest.endswith('_vol'),
                     role='reporting: unadjusted' if crude else 'primary')
        elif stem.startswith('x_age_sii_'):
            d.update(family='interaction', outcome='log SII',
                     age_cell='18+',
                     exposure=stem.replace('x_age_sii_', '').replace('_vol', '').upper(),
                     volume_adjusted=stem.endswith('_vol'),
                     role='age moderation, log SII')
        elif stem.startswith('x_age_'):
            d.update(family='interaction', outcome='KDM-BA advancement',
                     age_cell='18+',
                     exposure=stem.replace('x_age_', '').replace('_vol', '').upper(),
                     volume_adjusted=stem.endswith('_vol'), role='central test')
        elif stem.endswith('_trimmed'):
            # KDM-BA tail-trimming sensitivity (script 16); checked before the
            # M1/S2/S3 branch.
            out = 'cognition' if 'cognition' in stem else 'PHQ-9'
            d.update(family='sensitivity', outcome=out,
                     age_cell='60+' if out == 'cognition' else '18+',
                     exposure='IV', volume_adjusted=False,
                     role='sensitivity: KDM-BA tails trimmed')
        elif stem.startswith(('M1', 'S2', 'S3')):
            out = 'cognition' if 'cognition' in stem else 'PHQ-9'
            exp = ('IV_Q' if 'ivquint' in stem else
                   'RA_Q' if 'raquint' in stem else
                   'IS' if stem.endswith('_is') else
                   'RA' if stem.endswith('_ra') else 'IV')
            # M1 and S3 pool ages 18+ instead of stratifying (secondary);
            # S2 codes the exposure in quintiles (sensitivity).
            fam = 'sensitivity' if stem.startswith('S2') else 'secondary'
            d.update(family=fam, outcome=out,
                     age_cell='60+' if out == 'cognition' else '18+',
                     exposure=exp, volume_adjusted=False,
                     role={'M1': 'age-unstratified',
                           'S2': 'sensitivity: quintile exposure',
                           'S3': 'age-unstratified'}[stem[:2]])
        else:
            raise ValueError(
                f'label_models does not recognise the model name {stem!r}. '
                'Add a branch for it in mplus_parse.decode() before parsing '
                'its output; silent all-None metadata is how a TypeError '
                'surfaced three cells downstream of the actual problem.')
        return d

    meta = pd.DataFrame([decode(s) for s in info.model])
    return pd.concat([info.reset_index(drop=True), meta], axis=1)
