"""Build every reportable output from the Mplus results.

    python mplus_report.py

Reads the .out files in scripts/9_mplus_models through mplus_parse.py and writes:

  result/qc/QC_Mplus_Internal.xlsx          every parameter, check, duplicate and suppression flag
  result/main/Table2_SEM_Mediation.xlsx     manuscript Table 2 (plus .csv)
  result/main/Table3_Age_Moderation.xlsx    manuscript Table 3 (plus .csv)
  result/supplementary/Supp_Tables.xlsx     every model
  figure/main, figure/supplementary         PDF + PNG figures, each with a
                                            source-data workbook in figure/source_data
"""
import re
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).parent))
from mplus_parse import parse_dir, label_models
from nature_palette import PHQ9_COLOR, COG_COLOR, KDM_BA_COLOR, SII_COLOR
from nature_palette import age_label, AGE_LABEL
from population import YOUNG, OLD, POOLED, ADULT_MIN_AGE, OLD_MIN_AGE
from mplus_export import (flag_duplicates, path_table, effect_table,
                          interaction_table, indirect_with_holm,
                          mediation_proportion, fmt_ci, fmt_p)

BASE = Path(__file__).resolve().parent.parent
MODELS = BASE / 'scripts' / '9_mplus_models'
QC = BASE / 'result' / 'qc'
MAIN = BASE / 'result' / 'main'
SUPP = BASE / 'result' / 'supplementary'
FIG = BASE / 'figure' / 'main'
FIG_SUPP = BASE / 'figure' / 'supplementary'
SRC = BASE / 'figure' / 'source_data'
for p in (QC, MAIN, SUPP, FIG, FIG_SUPP, SRC):
    p.mkdir(parents=True, exist_ok=True)

# Manuscript table and figure numbering.
#
#   Table 1  sample characteristics                          script 6
#   Table 2  mediation, all rhythm metrics                   here
#   Table 3  age moderation                                  here
#
#   Fig 1    study overview and sample flow                  script 14
#   Fig 2    mediator contrast, KDM-BA against log SII       here, fig_dissociation
#   Fig 3    full path decomposition                         here, fig3_paths
#   Fig 4    age moderation, simple slopes                   here, fig2_moderation
#   Supp S5  rhythm -> biological age, core against
#            volume-adjusted covariates                      here, fig1_specificity
#   Supplementary Figs S1-S4 come from scripts 11, 12, 13 and 14.
TABNUM = {'mediation': 'Table2_SEM_Mediation',
          'moderation': 'Table3_Age_Moderation'}

# One main figure per question: Fig 2 which biological measure the rhythm
# relates to (and the indirect associations through each), Fig 3 the full
# decomposition, Fig 4 how the rhythm-to-biological-age association changes
# with age. The a1-by-covariate-set forest is supplementary. Panel letters
# are lower case (EJE); every figure is drawn at its final width.
FIGNUM = {'rhythm_to_ba': 'SuppFigS5_RhythmToBiologicalAge_VolumeAdjustment',
          'dissociation': 'Fig2_MediatorContrast',
          'decomposition': 'Fig3_PathDecomposition',
          'age_moderation': 'Fig4_Age_Moderation_SimpleSlopes'}

# Figure specification: single column 89 mm, double column 183 mm, maximum
# height 247 mm, vector output with embedded TrueType fonts. Text is sized for
# the final printed width (EJE: about 8-12 pt at final size; nothing below
# 7 pt), so the figures are drawn at their final dimensions.
MM = 1 / 25.4
W1, W2 = 89 * MM, 183 * MM
matplotlib.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],
    'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 8,
    'xtick.labelsize': 7, 'ytick.labelsize': 7, 'legend.fontsize': 7,
    'axes.linewidth': 0.5, 'xtick.major.width': 0.5, 'ytick.major.width': 0.5,
    'xtick.major.size': 2.5, 'ytick.major.size': 2.5,
    'lines.linewidth': 0.9, 'patch.linewidth': 0.5,
    'pdf.fonttype': 42, 'ps.fonttype': 42,      # editable text in the PDF
    # Arrows and subscripts use mathtext rather than literal unicode: macOS
    # Helvetica has no U+2192 glyph.
    'mathtext.fontset': 'dejavusans', 'mathtext.default': 'regular',
    'savefig.dpi': 600, 'figure.dpi': 200,
    'axes.spines.top': False, 'axes.spines.right': False,
})
# fontTools logs one informational line per unsubsettable macOS AAT table
# (Zapf, feat, morx) while embedding the font in each PDF; silence it.
import logging as _logging
for _n in ('fontTools', 'fontTools.subset', 'fontTools.ttLib'):
    _logging.getLogger(_n).setLevel(_logging.ERROR)

# Colours come from nature_palette, so each mediator and outcome is one hue
# in every figure.
DEP, COG, GREY = PHQ9_COLOR, COG_COLOR, '#9E9E9E'

# The rest-activity rhythm is summarised by five non-parametric metrics; three
# enter the models as exposures. The reasons for excluding M10 and L5 are
# computed in metric_selection() and printed to the supplement.
from nature_palette import EXP_ORDER
EXPOSURES = list(EXP_ORDER)   # RA, IS, IV; the order used in every table and figure
EXP_NAME = {'IV': 'Intradaily variability', 'IS': 'Interdaily stability',
            'RA': 'Relative amplitude', 'M10': 'Most active 10 h',
            'L5': 'Least active 5 h'}
# Metric colours, from nature_palette.
from nature_palette import EXP_COL

CELLS = [('PHQ-9', YOUNG), ('PHQ-9', OLD), ('cognition', OLD)]
ANALYTIC = BASE / 'data' / 'processed' / '8_nhanes_analytic.csv'


def save_fig(fig, stem, source_df, caption):
    """Write PDF + PNG + a source-data sheet, as Nature requires."""
    d = FIG_SUPP if stem.startswith('SuppFig') else FIG
    fig.savefig(d / f'{stem}.pdf', bbox_inches='tight')
    fig.savefig(d / f'{stem}.png', bbox_inches='tight', dpi=600)
    plt.close(fig)
    with pd.ExcelWriter(SRC / f'Source_Data_{stem}.xlsx', engine='openpyxl') as xw:
        source_df.to_excel(xw, sheet_name='source data', index=False)
        pd.DataFrame({'Notes': caption}).to_excel(xw, sheet_name='legend', index=False)
    return stem


# QC workbook
def qc_checks(est, info, paths, effects, holm, props):
    """Run the internal consistency checks; one row per check, status PASS or REVIEW."""
    c = []

    def add(name, ok, detail):
        c.append(dict(check=name, status='PASS' if ok else 'REVIEW', detail=detail))

    neg = info[info.loadings_positive == False]
    add('Latent factor orientation', not len(neg),
        'COG@1 identifies the factor only up to sign; a mirror solution flips '
        f'every coefficient on COG. Models with negative loadings: {list(neg.model) or "none"}')

    err = info[info.n_errors > 0]
    add('Mplus errors', not len(err), f'models with *** ERROR: {list(err.model) or "none"}')

    med = info[info.family == 'mediation']
    ns = med.groupby(['outcome', 'age_cell']).n.nunique()
    add('Sample size consistent within cell', (ns <= 2).all(),
        'mediation models sharing an outcome and age cell should share n (up '
        'to the volume-adjusted variant); sensitivity families are excluded -- '
        'trimmed and quintile models change the sample by design; '
        + ', '.join(f'{k}: {v}' for k, v in ns.items()))

    # Exactly one primary model per display cell. is_duplicate fires only on
    # an exact numeric match, so a sensitivity model fitted on a slightly
    # different sample is not excluded by it; the family filter is required.
    amb = []
    for outcome, cell in CELLS:
        for exp in EXPOSURES:
            hit = paths[(paths.outcome == outcome) & (paths.age_cell == cell)
                        & (paths.exposure == exp) & (~paths.volume_adjusted)
                        & (~paths.is_duplicate) & (paths.path == 'a1')]
            if len(hit) > 1:
                amb.append(f'{exp}/{outcome}/{cell}: {sorted(hit.model)}')
    n_prim = [len(paths[(paths.outcome == o) & (paths.age_cell == c)
                        & (paths.exposure == e) & (~paths.volume_adjusted)
                        & (paths.family == 'mediation') & (~paths.is_duplicate)
                        & (paths.path == 'a1')])
              for o, c in CELLS for e in EXPOSURES]
    add('One primary model per display cell', all(n == 1 for n in n_prim),
        f'{len(CELLS) * len(EXPOSURES)} display cells, each resolving to '
        f'exactly one family=="mediation" model. Without the family filter '
        f'{len(amb)} would be ambiguous'
        + (f' ({"; ".join(amb)}), and .iloc[0] would pick by row order'
           if amb else ''))

    dup = info[info.is_duplicate]
    add('Duplicate specifications identified', True,
        f'{len(dup)} model(s) are the same specification under a second name, '
        f'detected from n/a1/b1 rather than the filename: '
        + '; '.join(f'{r.model}={r.duplicate_of}' for _, r in dup.iterrows()))

    bad_prop = props[(props.reported == 'yes') & (props.proportion < 0)]
    add('No negative mediation proportion reported', not len(bad_prop),
        'a ratio against a null total effect has no reading. '
        f'Offending rows: {len(bad_prop)}')

    supp = props[props.reported != 'yes']
    add('Proportion suppressed where total is null', True,
        f'{len(supp)} of {len(props)} suppressed because the total effect is not '
        'distinguishable from zero')

    lost = holm[(holm.p < 0.05) & (~holm.survives_holm)]
    add('Holm correction applied', True,
        f'applied across the mediator family within each model; '
        f'{len(lost)} result(s) lose significance: '
        + ('; '.join(f'{r.model} via {r.via} p={r.p:.3f}->{r.p_holm:.3f}'
                     for _, r in lost.iterrows()) or 'none'))

    ci_missing = est[est.ci_lo.isna() & est.p.notna()]
    add('Confidence intervals parsed', len(ci_missing) == 0,
        f'{len(ci_missing)} estimate(s) without a parsed CI')

    d = effects[effects.effect == 'direct']
    add('Direct effects parsed', len(d) > 0,
        f'{len(d)} direct effects. Mplus prints Direct on four lines rather than '
        'one, so a one-line pattern misses it')

    strata = info.strata.dropna().unique()
    psu = info.clusters.dropna().unique()
    add('Survey design constant', len(strata) == 1 and len(psu) == 1,
        f'strata {strata}, PSUs {psu}')

    return pd.DataFrame(c)


def provenance(info):
    return pd.DataFrame({
        'model': info.model,
        'source_file': info.model + '.out',
        'family': info.family, 'role': info.role,
        'outcome': info.outcome, 'age_cell': info.age_cell,
        'exposure': info.exposure, 'volume_adjusted': info.volume_adjusted,
        'n': info.n, 'is_duplicate': info.is_duplicate,
        'duplicate_of': info.duplicate_of,
    })


def write_qc(est, eff, info, paths, effects, inter, holm, props):
    out = QC / 'QC_Mplus_Internal.xlsx'
    readme = [
        ('Purpose', 'Internal double-check. Not for submission.'),
        ('', ''),
        ('Checks', 'Consistency checks on the parsed output. '
                   'Any REVIEW row needs a human before the tables are used.'),
        ('Provenance', 'Which .out file each model came from, and which models are '
                       'the same specification under two names.'),
        ('All estimates', 'Every parameter, standardized and unstandardized, with CIs.'),
        ('All effects', 'Total, direct, total indirect and each specific indirect.'),
        ('Paths / Effects / Interaction', 'Reshaped for tables and figures.'),
        ('Holm / Proportion', 'The two derived quantities, with their guards.'),
        ('', ''),
        ('Known traps', ''),
        ('  Factor sign', 'COG@1 identifies the factor only up to sign. Check loadings first.'),
        ('  Mplus truncation', 'Parameter names are cut to 8 characters: SLOPE_MID -> SLOPE_MI.'),
        ('  Direct effect layout', 'Printed on four lines, not one.'),
        ('  Duplicate models', 'Detected from numbers, not filenames.'),
        ('  Delta-method CIs', 'Bootstrap unavailable under TYPE=COMPLEX with weights.'),
    ]
    with pd.ExcelWriter(out, engine='openpyxl') as xw:
        pd.DataFrame(readme).to_excel(xw, sheet_name='README', index=False, header=False)
        qc_checks(est, info, paths, effects, holm, props).to_excel(xw, sheet_name='Checks', index=False)
        provenance(info).to_excel(xw, sheet_name='Provenance', index=False)
        info.to_excel(xw, sheet_name='Model inventory', index=False)
        paths.to_excel(xw, sheet_name='Paths', index=False)
        effects.to_excel(xw, sheet_name='Effects', index=False)
        inter.to_excel(xw, sheet_name='Interaction', index=False)
        holm.to_excel(xw, sheet_name='Holm', index=False)
        props.to_excel(xw, sheet_name='Proportion', index=False)
        est.to_excel(xw, sheet_name='All estimates', index=False)
        eff.to_excel(xw, sheet_name='All effects', index=False)
        _autofit(xw)
    return out


def _autofit(xw):
    for ws in xw.book.worksheets:
        for col in ws.columns:
            w = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max(w + 2, 10), 55)
        ws.freeze_panes = 'A2'


# Selecting a primary model
def primary(frame, **conds):
    """The one primary-analysis row matching `conds`, or None if no row matches.

    Restricts to family == 'mediation', not volume-adjusted (unless
    volume_adjusted is given) and not is_duplicate, then applies `conds`.
    Raises if more than one row remains: sensitivity and age-unstratified
    models share an outcome, age cell and exposure with a primary model, and
    is_duplicate does not exclude them because it requires an exact match of
    n, a1 and b1.
    """
    m = pd.Series(True, index=frame.index)
    if 'family' in frame.columns:
        m &= frame.family == 'mediation'
    if 'volume_adjusted' in frame.columns and 'volume_adjusted' not in conds:
        m &= ~frame.volume_adjusted
    if 'is_duplicate' in frame.columns:
        m &= ~frame.is_duplicate
    for k, v in conds.items():
        m &= frame[k].isna() if v is None else frame[k] == v
    hit = frame[m]
    if len(hit) == 1:
        return hit.iloc[0]
    what = ', '.join(f'{k}={v!r}' for k, v in conds.items())
    if not len(hit):
        return None                     # a cell that was never modelled
    raise ValueError(
        f'{len(hit)} primary rows match {what}; expected exactly one. '
        f'Models: {sorted(hit.model.unique())}. Two primary models cannot '
        f'describe the same cell -- fix the manifest rather than the query.')


# Main tables
def table_main_mediation(paths, effects, holm, props, exposures=EXPOSURES):
    """Table 2: mediation decomposition for every rhythm metric in each analysis cell."""
    blank = {'Rhythm metric': '', 'Effect': '', 'β (95% CI)': '', 'P': '',
             'P (Holm)': '', 'Indirect/total ratio': ''}
    rows = []
    for outcome, cell in CELLS:
        cell_rows = []
        for exposure in exposures:
            p = paths[(paths.outcome == outcome) & (paths.age_cell == cell)
                      & (paths.exposure == exposure) & (~paths.volume_adjusted)
                      & (paths.family == 'mediation') & (~paths.is_duplicate)]
            if not len(p):
                continue
            cell_rows.append(blank | {'Rhythm metric': f'{EXP_NAME[exposure]} ({exposure}), '
                                                       f'n = {int(p.iloc[0].n):,}'})
            for name, lab in [('a1', 'Rhythm → biological-age advancement'),
                              ('b1', 'Biological-age advancement → outcome'),
                              ('a2', 'Rhythm → log SII'),
                              ('b2', 'log SII → outcome')]:
                r = p[p.path == name]
                if len(r):
                    r = r.iloc[0]
                    cell_rows.append(blank | {
                        'Effect': lab, 'β (95% CI)': fmt_ci(r.beta, r.ci_lo, r.ci_hi),
                        'P': fmt_p(r.p)})

            for key, lab in [('total', 'Total effect'), ('direct', 'Direct effect')]:
                x = primary(effects, outcome=outcome, age_cell=cell,
                            exposure=exposure, effect=key, via=None)
                if x is not None:
                    cell_rows.append(blank | {
                        'Effect': lab,
                        'β (95% CI)': fmt_ci(x.estimate, x.ci_lo, x.ci_hi),
                        'P': fmt_p(x.p)})
            for med, lab in [('BA_ADV', 'Indirect via biological-age advancement'),
                             ('SII_LOG', 'Indirect via log SII')]:
                h = primary(holm, outcome=outcome, age_cell=cell,
                            exposure=exposure, via=med)
                pr = primary(props, outcome=outcome, age_cell=cell,
                             exposure=exposure, mediator=med)
                if h is None:
                    continue
                prop = ''
                if pr is not None:
                    # 'Not reported' marks a ratio suppressed by the reporting
                    # rule (null total, null indirect, or opposite signs); the
                    # ratio itself is always computable, so 'not estimable'
                    # would misdescribe it.
                    prop = ('Not reported' if pd.isna(pr.proportion)
                            else f'{pr.proportion*100:.1f}% ({pr.prop_lo*100:.1f}–'
                                 f'{pr.prop_hi*100:.1f})')
                cell_rows.append(blank | {
                    'Effect': lab, 'β (95% CI)': fmt_ci(h.estimate, h.ci_lo, h.ci_hi),
                    'P': fmt_p(h.p), 'P (Holm)': fmt_p(h.p_holm),
                    'Indirect/total ratio': prop})
        if cell_rows:
            rows.append(blank | {'Rhythm metric': f'{outcome}, {age_label(cell)}'.upper()})
            rows += cell_rows
    return pd.DataFrame(rows)


def table_main_moderation(inter, outcome='KDM-BA advancement', include_volume=False):
    """Table 3 (core covariates only) and, with include_volume, Supplementary
    Tables S5 / S5b, which add the volume-adjusted block of each exposure."""
    rows = []
    d = inter[inter.outcome == outcome].copy()
    if not include_volume:
        d = d[~d.volume_adjusted.astype(bool)]
    d['_o'] = d.exposure.map({e: i for i, e in enumerate(EXPOSURES)})
    d['_v'] = d.volume_adjusted.astype(bool).astype(int)
    # The coefficient column is named b, not β: these are unstandardised
    # coefficients on the common reference-standardised scale (see the notes),
    # not the STDYX values of Table 2. The main effect of the rhythm metric in
    # a model with a mean-centred product term IS the simple slope at the mean
    # age, so that row is reported once, under its simple-slope name.
    for _, r in d.sort_values(['_o', '_v']).iterrows():
        head = {'Exposure': r.exposure, 'Term': '', 'b (95% CI)': '', 'P': ''}
        if include_volume:
            head = {'Exposure': r.exposure, 'Covariate set': 'Core covariates + total activity volume' if r._v else 'Core covariates',
                    'n': f'{int(r.n):,}', 'Term': '', 'b (95% CI)': '', 'P': ''}
        rows.append(head)
        for key, lab in [('interaction', 'Rhythm metric × age'),
                         ('SLOPE_LO', 'Simple slope, age −1 s.d.'),
                         ('SLOPE_MID', 'Simple slope, mean age (main effect)'),
                         ('SLOPE_HI', 'Simple slope, age +1 s.d.')]:
            if f'{key}_beta' not in r or pd.isna(r[f'{key}_beta']):
                continue
            row = {'Exposure': '', 'Term': lab,
                   'b (95% CI)': fmt_ci(r[f'{key}_beta'], r[f'{key}_lo'], r[f'{key}_hi']),
                   'P': fmt_p(r[f'{key}_p'])}
            if include_volume:
                row = {'Exposure': '', 'Covariate set': '', 'n': '', **row}
                row.pop('Exposure'); row = {'Exposure': '', 'Covariate set': '', 'n': '', 'Term': lab,
                                            'b (95% CI)': row['b (95% CI)'], 'P': row['P']}
            rows.append(row)
    return pd.DataFrame(rows)


# Table 2 notes, keyed so that SHARED_NOTES can select entries by name.
MAIN_NOTES = {
    'design':
    'Complex-survey structural equation models (Mplus 9, TYPE = COMPLEX, MLR '
    'estimator) with the four-year mobile examination centre weight, 29 strata '
    'and 61 primary sampling units.',
    'standardisation':
    'β are STDYX standardised coefficients: change in s.d. of the outcome per '
    '1 s.d. of the exposure. Standardisation is within each model, so the '
    'conversion to natural units differs by cell; the "Scale" sheet gives the '
    'standard deviation of every standardised variable in every cell. For '
    'example β = -0.151 for relative amplitude at 60+ is 0.151 x 11.37 = 1.7 '
    'years of biological-age advancement, whereas the same coefficient scaled '
    'by the full-sample standard deviation would be 1.6 years.',

    'metrics':
    'Rest-activity rhythm metrics: intradaily variability (IV, fragmentation), '
    'interdaily stability (IS, day-to-day reproducibility) and relative '
    'amplitude (RA). The most active 10-h and least active 5-h periods are not '
    'modelled as exposures — the former is largely total activity volume and '
    'the latter is nearly collinear with relative amplitude, which is derived '
    'from it. The collinearity is quantified in the supplementary tables.',
    'covariates':
    'Covariates in every equation: age, sex, body mass index, education, '
    'accelerometer wear time and self-reported sleep duration.',

    'primary_only':
    'Every estimate here comes from the primary model for that cell. '
    'Secondary and sensitivity variants — the age-unstratified all-adult '
    'specification, biological-age tails trimmed, quintile-coded exposure — '
    'are reported in Supplementary Tables S3 and S4, where the "Analysis" '
    'column identifies each one.',

    'cells':
    'The three cells vary age while holding the outcome fixed for depressive '
    'symptoms. Cognition is available only at 60 years and over, because NHANES '
    'administers the battery only to that age group; comparing depression across '
    'all adults against cognition at 60+ would confound outcome with age range.',

    'holm':
    'P (Holm): Holm–Bonferroni adjustment across the two mediators within each '
    'model.',

    'proportion': 'PROPORTION_MEDIATED_NOTES',

    'intervals':
    'Confidence intervals for indirect effects are delta-method. Bootstrap '
    'resampling is not available for complex-survey designs with sampling '
    'weights in Mplus; the parameter covariance matrix (TECH3) is retained so '
    'that Monte Carlo intervals can be constructed.',
}


# Notes shared by Tables 2 and 3. 'cells' and 'primary_only' are not shared:
# Table 3 is not fitted within the three analysis cells and the age-moderation
# family has no sensitivity counterpart. 'standardisation' (the STDYX note) is
# Table 2 only: Table 3 reports the unstandardised solution on the common
# reference-standardised scale and carries its own scale note.
SHARED_NOTES = ['design', 'metrics', 'covariates']


def moderation_facts(inter):
    """Sentences about the age-moderation results, written from the parsed
    estimates so that the notes cannot outlive the numbers.

    Returns (sii_sentence, support_sentence, direction_sentence)."""
    core = inter[~inter.volume_adjusted]
    sii = core[core.outcome == 'log SII']
    ba = core[core.outcome == 'KDM-BA advancement']
    name = {'IV': 'intradaily variability', 'IS': 'interdaily stability',
            'RA': 'relative amplitude'}
    if len(sii):
        sig = sii[sii.interaction_p < 0.05]
        if len(sig) == 0:
            sii_s = (f'are non-significant for all three metrics (P \u2265 '
                     f'{sii.interaction_p.min():.3f}; Supplementary Table S5b)')
        else:
            sii_s = ('are significant for '
                     + ', '.join(name[e] for e in sig.exposure)
                     + ' and non-significant for the other metric(s) '
                       '(Supplementary Table S5b)')
    else:
        sii_s = 'are reported in Supplementary Table S5b'
    def join(items):
        return ' and '.join(items) if len(items) <= 2 else ', '.join(items[:-1]) + ' and ' + items[-1]
    sup = ba[ba.interaction_p < 0.05]
    unsup = ba[ba.interaction_p >= 0.05]
    support = []
    if len(sup):
        pmax = sup.interaction_p.max()
        support.append(f'The interaction is supported for {join([name[e] for e in sup.exposure])} '
                       + ('(both ' if len(sup) == 2 else '(all ' if len(sup) > 2 else '(')
                       + (f'P < 0.001)' if pmax < 0.001 else f'P \u2264 {pmax:.3f})'))
    for _, r in unsup.iterrows():
        support.append(f'for {name[r.exposure]} the estimate is {r.interaction_beta:+.3f} '
                       f'(95% CI {r.interaction_lo:.3f} to {r.interaction_hi:.3f}; P = {r.interaction_p:.3f}) and no age trend is claimed')
    support_s = '; '.join(support) + '.' if support else ''
    # direction, only for the metrics whose interaction is supported
    groups = {'changes sign across the age range': [],
              'keeps its direction and strengthens with age': [],
              'keeps its direction and weakens with age': []}
    for _, r in sup.iterrows():
        lo, hi = r.SLOPE_LO_beta, r.SLOPE_HI_beta
        if np.sign(lo) != np.sign(hi) and lo != 0 and hi != 0:
            groups['changes sign across the age range'].append(name[r.exposure])
        elif abs(hi) >= abs(lo):
            groups['keeps its direction and strengthens with age'].append(name[r.exposure])
        else:
            groups['keeps its direction and weakens with age'].append(name[r.exposure])
    parts = []
    for behaviour, metrics in groups.items():
        if metrics:
            verb = behaviour if len(metrics) == 1 else behaviour.replace('changes', 'change').replace('keeps', 'keep').replace('strengthens', 'strengthen').replace('weakens', 'weaken').replace('its', 'their')
            parts.append(join(metrics) + ' ' + verb)
    direction_s = ('; '.join(parts).capitalize() + '.') if parts else ''
    for _, r in unsup.iterrows():
        signs = {np.sign(r.SLOPE_LO_beta), np.sign(r.SLOPE_MID_beta), np.sign(r.SLOPE_HI_beta)}
        same = 'the same sign' if len(signs) == 1 else 'mixed signs'
        direction_s += (f' The simple slopes for {name[r.exposure]} have {same} at the three ages '
                        f'({r.SLOPE_LO_beta:+.3f}, {r.SLOPE_MID_beta:+.3f}, {r.SLOPE_HI_beta:+.3f}).')
    return sii_s, support_s, direction_s.strip()


def moderation_notes(inter, est=None):
    """Table 3 notes: the shared notes plus the interaction and simple-slope
    definitions. `est` (parsed estimates) supplies the STDYX-versus-common-scale
    contrast for the example; without it the example is omitted."""
    sii_s, support_s, direction_s = moderation_facts(inter)
    example = ''
    core = inter[(~inter.volume_adjusted) & (inter.outcome == 'KDM-BA advancement') & (inter.exposure == 'RA')]
    if est is not None and len(core):
        sx = est[(est.model == core.iloc[0].model) & (est.solution == 'STDYX') & (est.parameter == 'RA_AGE')]
        if len(sx):
            example = (f' (Mplus STDYX rescales the product term by its own standard deviation and is not '
                       f'used here; it would give {sx.iloc[0].estimate:.3f} rather than '
                       f'{core.iloc[0].interaction_beta:.3f} for relative amplitude.)')
    missing = [k for k in SHARED_NOTES if k not in MAIN_NOTES]
    if missing:
        raise KeyError(f'SHARED_NOTES names no longer in MAIN_NOTES: {missing}')
    keep = [MAIN_NOTES[k] for k in SHARED_NOTES
            if MAIN_NOTES[k] != 'PROPORTION_MEDIATED_NOTES']
    return keep + [
        'Scale of this table: the rhythm metric, age and biological-age '
        'advancement were z-standardised on the reference sample (adults aged '
        '20 and over in the depressive-symptom analytic universe; script 9) '
        'before the product term was formed, and every coefficient is from the '
        'unstandardised solution on that common scale, so the interaction '
        'term is the change in the rhythm-to-biological-age coefficient per '
        '1 reference s.d. of age and equals the difference between adjacent '
        'simple slopes.' + example + ' Simple slopes are the coefficient '
        'evaluated at one standard deviation below the mean age, at the mean, '
        'and one standard deviation above, within the same model. Coefficients '
        'are not STDYX values and are not comparable with Table 2.',
        'The dependent variable is biological-age advancement because that '
        'is the leg carrying the indirect associations. The corresponding '
        'rhythm-by-age interactions on log SII, estimated under the same '
        f'complex-survey specification, {sii_s}; the weighted least-squares '
        'version by age band is in Supplementary Table S8.',
        'These models are fitted on all adults with biological-age '
        'advancement observed, not within the three analysis cells of '
        'Table 2. Biological-age advancement is their only dependent '
        'variable, so full-information estimation recovers nothing and the '
        'sample is the set in whom it was measured.',
        f'{support_s} A supported interaction means the association changes '
        'with age; whether it changes direction is a separate question, '
        f'answered by the simple slopes. {direction_s}'.strip(),
        'Supplementary Table S8 and Supplementary Fig. S1 give the same '
        'moderation estimated by survey-weighted least squares within four '
        'age bands, which these linear interactions can only bracket.',
    ]


def proportion_notes(effects, holm, props):
    """Notes for the indirect/total ratio column; the worked examples are looked up from the results."""
    def eff(model, kind, via=None):
        d = effects[(effects.model == model) & (effects.effect == kind)
                    & (effects.solution == 'STDYX')]
        if via is not None:
            d = d[d.via == via]
        return d.iloc[0] if len(d) else None

    # Worked example: the largest reported proportion.
    rep = props[props.reported == 'yes'].copy()
    ex = ''
    if len(rep):
        r = rep.loc[rep.proportion.idxmax()]
        ind = eff(r.model, 'indirect', r.mediator)
        tot = eff(r.model, 'total')
        if ind is not None and tot is not None:
            ex = (f' As an example, an indirect effect of {ind.estimate:.3f} '
                  f'against a total effect of {tot.estimate:.3f} gives '
                  f'{r.proportion * 100:.1f}%: that share of the association '
                  f'is accounted for by the mediator within this model, and '
                  f'the remainder runs through paths the model does not '
                  f'contain.')

    # Worked example: a significant indirect effect with a null total effect.
    trap = ''
    cand = holm[(holm.p < 0.05) & (~holm.is_duplicate)]
    for _, h in cand.iterrows():
        tot = eff(h.model, 'total')
        if tot is not None and tot.p > 0.5:
            direct = eff(h.model, 'direct')
            trap = (f' A significant indirect effect alongside a null total '
                    f'effect is not a contradiction: in {h.outcome} at '
                    f'{h.age_cell}, {h.exposure} reaches the outcome through '
                    f'{"biological age" if h.via == "BA_ADV" else "log SII"} '
                    f'(indirect {h.estimate:.3f}, Holm P = {h.p_holm:.3f}) '
                    f'while the total effect is flat ({tot.estimate:.3f}, '
                    f'P = {tot.p:.3f})'
                    + (f', because the indirect and direct paths '
                       f'({direct.estimate:.3f}) have opposite signs and '
                       f'cancel.' if direct is not None else '.'))
            break

    n_sup = int((props.reported != 'yes').sum())
    return [
        'Indirect/total ratio: the indirect association through that measure '
        'divided by the total association, reported as a descriptive quantity '
        'for models in which both are supported and share a direction.' + ex,
        'It is a model-implied decomposition, not a causal attribution. These '
        'data are cross-sectional, so the ordering from exposure to measure '
        'to outcome is imposed by the model rather than established by the '
        'design; the ratio is not the fraction of an effect that the measure '
        'mediates, which is why the column is not named "proportion '
        'mediated".',
        f'The ratio is always computable; it is withheld and shown as '
        f'"Not reported" under any of three conditions set in advance: the '
        f'total effect is not distinguishable from zero, the indirect effect '
        f'is not, or the two have opposite signs. In each case the ratio has '
        f'no interpretation (for example a negative ratio against a null '
        f'total effect). {n_sup} of {len(props)} ratios are withheld on '
        f'this rule.',
        'Suppression is a property of the ratio alone.' + trap
        + ' Read this column together with the total and indirect rows above '
          'it, never on its own.',
    ]


def main_notes(effects, holm, props):
    """MAIN_NOTES with the proportion placeholder expanded."""
    out = []
    for n in MAIN_NOTES.values():
        if n == 'PROPORTION_MEDIATED_NOTES':
            out += proportion_notes(effects, holm, props)
        else:
            out.append(n)
    return out


def cell_scales():
    """Survey-weighted s.d. per analysis cell, for converting STDYX coefficients to natural units.

    STDYX standardises within each model's own sample, so the conversion
    factor differs between cells (for example 0.151 s.d. of biological-age
    advancement is 1.7 years at 60+, s.d. 11.4, but 1.6 years at the
    full-sample s.d.).
    """
    if not ANALYTIC.exists():
        return None
    d = pd.read_csv(ANALYTIC, low_memory=False)
    d = d[d.RIDAGEYR >= ADULT_MIN_AGE].copy()
    dpq = [f'DPQ{i:03d}' for i in [10, 20, 30, 40, 50, 60, 70, 80, 90]]
    d['PHQ9'] = d[dpq].replace({7: np.nan, 9: np.nan}).sum(axis=1, min_count=9)
    # Cognition indicators, z-scored within ages 60+, are needed before the
    # analysis sets are cut so the cognition cell can apply its own rule.
    elig = d.RIDAGEYR >= 60
    for _src, _dst in [('memory_score', 'MEM_Z'), ('fluency_score', 'FLUEN_Z'),
                       ('speed_score', 'SPEED_Z')]:
        _raw = d[_src]          # scores of 0 are valid results and are kept
        _s = _raw[elig].dropna()
        d[_dst] = np.where(elig, (_raw - _s.mean()) / _s.std(), np.nan)

    covs = ['RIDAGEYR', 'RIAGENDR', 'BMXBMI', 'DMDEDUC2', 'Wear_Time', 'SLD010H']
    xc = d.dropna(subset=['IV', 'WTMEC4YR'] + covs)
    sem = xc[~xc[['KDM_BA_advance', 'SII_log', 'PHQ9']].isna().all(axis=1)]

    # The cognition cell has its own inclusion rule (n = 2,908), distinct from
    # the depression 60+ cell (n = 2,909).
    x60 = xc[xc.RIDAGEYR >= 60]
    sem_cog = x60[~x60[['KDM_BA_advance', 'SII_log',
                        'MEM_Z', 'FLUEN_Z', 'SPEED_Z']].isna().all(axis=1)]

    def wsd(sub, c):
        m = sub[c].notna()
        v, w = sub.loc[m, c].values, sub.loc[m, 'WTMEC4YR'].values
        mu = np.average(v, weights=w)
        return float(np.sqrt(np.average((v - mu) ** 2, weights=w)))

    cells = [(f'PHQ-9, {age_label(YOUNG)}', sem[sem.RIDAGEYR < OLD_MIN_AGE]),
             ('PHQ-9, 60+', sem[sem.RIDAGEYR >= 60]),
             ('cognition, 60+', sem_cog)]
    rows = []
    for lab, sub in cells:
        rows.append({
            'Analysis cell': lab,
            'n': f'{len(sub):,}',
            'KDM-BA advancement, years': f'{wsd(sub, "KDM_BA_advance"):.2f}',
            'PHQ-9, points': (f'{wsd(sub, "PHQ9"):.2f}'
                              if sub['PHQ9'].notna().sum() > 30 else '\u2014'),
            'Relative amplitude': f'{wsd(sub, "RA"):.3f}',
            'Interdaily stability': f'{wsd(sub, "IS"):.3f}',
            'Intradaily variability': f'{wsd(sub, "IV"):.3f}',
        })
    return pd.DataFrame(rows)


def write_main(paths, effects, holm, props, inter, est=None):
    """Write one workbook and one CSV per main-text table, named by TABNUM."""
    sc = cell_scales()
    notes = main_notes(effects, holm, props)
    written = []

    out = MAIN / f"{TABNUM['mediation']}.xlsx"
    t = table_main_mediation(paths, effects, holm, props)
    with pd.ExcelWriter(out, engine='openpyxl') as xw:
        t.to_excel(xw, sheet_name='Table 2', index=False)
        if sc is not None:
            sc.to_excel(xw, sheet_name='Scale', index=False)
        pd.DataFrame({'Notes': notes}).to_excel(xw, sheet_name='Notes', index=False)
        _autofit(xw)
    t.to_csv(out.with_suffix('.csv'), index=False)
    written.append(out)

    out = MAIN / f"{TABNUM['moderation']}.xlsx"
    m = table_main_moderation(inter)
    with pd.ExcelWriter(out, engine='openpyxl') as xw:
        m.to_excel(xw, sheet_name='Table 3', index=False)
        if sc is not None:
            sc.to_excel(xw, sheet_name='Scale', index=False)
        pd.DataFrame({'Notes': moderation_notes(inter, est)}).to_excel(
            xw, sheet_name='Notes', index=False)
        _autofit(xw)
    m.to_csv(out.with_suffix('.csv'), index=False)
    written.append(out)

    # Output files under older names are moved to _superseded/, not deleted.
    for stale in ('Main_Tables.xlsx', 'Table4_SEM_Mediation.xlsx',
                  'Table4_SEM_Mediation.csv'):
        f = MAIN / stale
        if f.exists():
            dest = BASE / '_superseded' / stale
            dest.parent.mkdir(exist_ok=True)
            f.replace(dest)
            print(f'  superseded -> _superseded/{stale}')
    return written


# Supplementary tables
# "Analysis" column labels by model role, for S3, S4 and S6. Age-unstratified
# models are labelled secondary rather than sensitivity: they pool all adults
# instead of stratifying, so they answer a different question from the
# primary age-cell models and do not corroborate them.
ANALYSIS = {
    'primary': 'Primary',
    'reporting: unadjusted': 'Unadjusted counterpart of the primary model (no covariates, same participants)',
    'age-unstratified': 'Secondary: age-unstratified (all adults)',
    'sensitivity: KDM-BA tails trimmed': 'Sensitivity: biological-age tails trimmed',
    'sensitivity: quintile exposure': 'Sensitivity: quintile-coded rhythm metric',
    'central test': 'Age moderation',
}
# Row order within a cell: primary, then secondary, then sensitivity.
ANALYSIS_ORDER = {v: i for i, v in enumerate(ANALYSIS.values())}


def _label_analysis(d):
    """Add the Analysis column and sort primary rows to the top of each cell."""
    unknown = set(d.role.dropna()) - set(ANALYSIS)
    if unknown:
        raise ValueError(
            f'no Analysis label for role(s) {sorted(unknown)}. Add them to '
            'ANALYSIS rather than letting the column go blank -- a blank here '
            'is indistinguishable from a primary model.')
    d = d.copy()
    d['Analysis'] = d.role.map(ANALYSIS)
    d['_ord'] = d.Analysis.map(ANALYSIS_ORDER)
    return d.sort_values(['outcome', 'age_cell', 'exposure', '_ord',
                          'volume_adjusted']).drop(columns='_ord')


def table_supp_all_paths(paths):
    d = _label_analysis(paths[~paths.is_duplicate])
    d['β (95% CI)'] = [fmt_ci(r.beta, r.ci_lo, r.ci_hi) for _, r in d.iterrows()]
    d['P'] = d.p.apply(fmt_p)
    d['age_cell'] = d.age_cell.map(age_label)
    d['Volume-adjusted'] = np.where(d.volume_adjusted, 'Yes', 'No')
    return d[['outcome', 'age_cell', 'exposure', 'Analysis', 'Volume-adjusted',
              'n', 'path', 'description', 'β (95% CI)', 'P', 'model']].rename(
                  columns={'outcome': 'Outcome', 'age_cell': 'Age group',
                           'exposure': 'Rhythm metric', 'n': 'n', 'path': 'Path',
                           'description': 'Description', 'model': 'Model file'})


def table_supp_all_effects(effects, holm):
    d = _label_analysis(effects[~effects.is_duplicate])

    # Mplus prints "Total indirect" and "Sum of indirect" as separate lines.
    # With two parallel mediators and no chained path they are the same
    # quantity, so the two are asserted equal and only one is listed.
    _ti = d[d.label == 'total_indirect'].set_index('model').estimate
    _si = d[d.label == 'sum_indirect'].set_index('model').estimate
    _both = _ti.index.intersection(_si.index)
    _gap = (_ti[_both] - _si[_both]).abs()
    if len(_gap) and _gap.max() > 1e-9:
        raise ArithmeticError(
            'Mplus "Total indirect" and "Sum of indirect" disagree (max '
            f'{_gap.max():.2e}, worst model {_gap.idxmax()}). With two '
            'parallel mediators they must be identical; a mismatch means '
            'parse_effects matched a pattern against the wrong block.')
    d = d[d.label != 'sum_indirect']

    d = d.merge(holm[['model', 'via', 'p_holm']], on=['model', 'via'], how='left')
    d['β (95% CI)'] = [fmt_ci(r.estimate, r.ci_lo, r.ci_hi) for _, r in d.iterrows()]
    d['P'] = d.p.apply(fmt_p)
    d['P (Holm)'] = d.p_holm.apply(fmt_p)
    d['age_cell'] = d.age_cell.map(age_label)
    d['Volume-adjusted'] = np.where(d.volume_adjusted, 'Yes', 'No')
    return d[['outcome', 'age_cell', 'exposure', 'Analysis', 'Volume-adjusted',
              'n', 'label', 'β (95% CI)', 'P', 'P (Holm)', 'model']].rename(
                  columns={'outcome': 'Outcome', 'age_cell': 'Age group',
                           'exposure': 'Rhythm metric', 'label': 'Effect',
                           'model': 'Model file'})


def table_supp_fit(info):
    d = info[~info.is_duplicate].copy()
    d['Analysis'] = d.role.map(ANALYSIS)
    d['χ² (df)'] = [('' if pd.isna(r.chi2) else f'{r.chi2:.1f} ({int(r.chi2_df)})')
                    for _, r in d.iterrows()]
    d['RMSEA (90% CI)'] = [('' if pd.isna(r.rmsea) else
                            f'{r.rmsea:.3f} ({r.rmsea_lo:.3f}–{r.rmsea_hi:.3f})')
                           for _, r in d.iterrows()]
    # The outcome R-square is split into an observed (PHQ-9) and a latent
    # (cognition factor) column. For the cognition models it is the share of
    # the factor's variance explained by the structural part (about 0.58).
    d['R² biological-age advancement'] = d.r2_ba_adv
    d['R² log SII'] = d.r2_sii_log
    d['R² PHQ-9 (observed)'] = [r.r2_outcome if not r.r2_outcome_is_latent else None
                                for _, r in d.iterrows()]
    d['R² cognition factor (latent)'] = [r.r2_outcome if r.r2_outcome_is_latent else None
                                         for _, r in d.iterrows()]
    d['age_cell'] = d.age_cell.map(age_label)
    return d[['model', 'Analysis', 'family', 'outcome', 'age_cell', 'exposure',
              'volume_adjusted', 'n', 'free_parameters', 'missing_patterns',
              'χ² (df)', 'cfi', 'tli', 'RMSEA (90% CI)', 'srmr',
              'R² biological-age advancement', 'R² log SII',
              'R² PHQ-9 (observed)', 'R² cognition factor (latent)',
              'loglik', 'aic', 'bic', 'loadings_positive']]


def metric_selection():
    """Supp Table S7: why three of the five non-parametric metrics enter the models.

    Computed from the analytic file. M10 regressed on log total MIMS gives
    R2 ~ 0.78, so a volume-adjusted M10 model would estimate an effect of the
    ~22% of its variance that remains. L5 is not redundant with volume
    (R2 ~ 0.05) but is nearly collinear with RA, which is built from it
    (r ~ -0.88), so RA already carries the night-time signal.
    Returns None if the analytic file is absent.
    """
    if not ANALYTIC.exists():
        return None
    d = pd.read_csv(ANALYTIC, low_memory=False)
    need = EXPOSURES + ['M10', 'L5', 'TOTAL_MIMS']
    if any(c not in d.columns for c in need):
        return None
    s = d[need].dropna()
    lv = np.log(s.TOTAL_MIMS.values)
    X = np.c_[np.ones(len(s)), lv]
    rows = []
    for m in EXPOSURES + ['M10', 'L5']:
        y = s[m].values
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        r2 = 1 - ((y - X @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        rows.append({
            'Rhythm metric': f'{EXP_NAME[m]} ({m})',
            'Modelled as exposure': 'Yes' if m in EXPOSURES else 'No',
            'r with total activity volume': round(float(np.corrcoef(y, s.TOTAL_MIMS)[0, 1]), 2),
            'R² on log total volume': round(float(r2), 3),
            'Residual s.d. retained after volume adjustment':
                f'{np.sqrt(max(1.0 - r2, 0.0)) * 100:.0f}%',
            'r with relative amplitude': round(float(np.corrcoef(y, s.RA)[0, 1]), 2),
            'Reason': {
                'IV': 'Fragmentation of the rest-activity cycle; near-orthogonal to volume.',
                'IS': 'Day-to-day reproducibility of the cycle; near-orthogonal to volume.',
                'RA': 'Amplitude of the cycle; independent of volume. Built from M10 and L5.',
                'M10': 'Not modelled: largely total activity volume, so the '
                       'volume-adjusted estimate has no clean interpretation.',
                'L5': 'Not modelled: nearly collinear with relative amplitude, '
                      'which is derived from it. RA carries the night-time signal.',
            }[m],
        })
    out = pd.DataFrame(rows)
    out.attrs['n'] = len(s)
    return out


SUPP_NOTES = [
    # Scope
    'Scope. These sheets report every structural equation model estimated in '
    'this study, including those not reported in the main text. Supplementary '
    'Table S3 lists the structural paths of each model, S4 the derived total, '
    'direct and indirect effects, S5 the age-moderation models, S6 model fit, '
    'and S7 the selection of rhythm metrics.',
    'The "Analysis" column identifies what each model is. Rows marked Primary '
    'are the models reported in Table 2 and Figures 2-4; every other row is a '
    'secondary or sensitivity variant. Several of them share an outcome, age '
    'group and rhythm metric with a primary model and differ only in the '
    'sample or the coding of the exposure, so two rows can look like the same '
    'analysis: read the Analysis column, not the row order, and compare n. '
    'Where a sensitivity model is fitted on a trimmed sample its n is smaller '
    'than the primary n for the same cell. Rows marked "Unadjusted counterpart '
    'of the primary model" are the same specification as the primary row '
    'without the six covariates, fitted to the same participants (identical '
    'n); they are reported for STROBE item 16a, side by side with the adjusted '
    'estimates, in Supplementary Table S20, and support no inference.',
    'The "Model file" column names the Mplus input/output pair in the code '
    'repository (scripts/9_mplus_models/) that produced the row, so any '
    'estimate can be traced to the model that generated it.',

    # Estimation
    'Design and estimation. All models are complex-survey structural equation '
    'models (Mplus 9, TYPE = COMPLEX, MLR robust maximum likelihood) using '
    'the four-year mobile examination centre weight (WTMEC2YR/2), 29 strata '
    'and 61 primary sampling units. Age-restricted models retain the full '
    'design via SUBPOPULATION rather than deleting out-of-cell cases, so '
    'design-based standard errors are computed on the complete survey '
    'structure.',
    'Covariates. Every structural equation in every model except the '
    'unadjusted counterparts — both mediator equations and the outcome '
    'equation, including the latent cognition factor — adjusts for age, sex, '
    'body mass index, education, accelerometer '
    'wear time and self-reported sleep duration. Age is adjusted as a '
    'continuous covariate within each age cell as well: stratification at 60 '
    'does not replace age adjustment inside the stratum. Rows marked '
    'Volume-adjusted = Yes add total daily activity volume (total MIMS) to '
    'all three equations on top of the six core covariates, not in place of '
    'them.',
    'Missing data. Exogenous variables (rhythm metric and covariates) are '
    'required to be observed; endogenous variables (mediators and outcomes) '
    'may be missing and are handled by full-information maximum likelihood. A '
    'participant enters a model if at least one of its dependent variables is '
    'observed. Supplementary Table S12 gives the row-by-row accounting.',
    'Coefficients are STDYX-standardised: the change in standard deviations '
    'of the dependent variable per one standard deviation of the predictor, '
    'standardised within each model sample. Conversion to natural units '
    'therefore differs by cell; the Scale sheets of Tables 2 and 3 give the '
    'per-cell standard deviations.',
    'Confidence intervals are delta-method (Mplus CINTERVAL). Bootstrap '
    'resampling is unavailable under TYPE = COMPLEX with weights; the '
    'parameter covariance matrix (TECH3) is retained for Monte Carlo '
    'intervals.',

    # S3
    'S3, Path column. a1 = rhythm metric to biological-age advancement; a2 = '
    'rhythm metric to log SII; b1 = biological-age advancement to outcome; '
    'b2 = log SII to outcome; c_prime = the direct association of the rhythm '
    'metric with the outcome, conditional on both mediators. All five are '
    'estimated jointly within one model per row group.',

    # S4
    'S4, Effect column. "total" is the sum of the direct and all indirect '
    'paths; "direct" equals c_prime in Table S3; "indirect via BA_ADV" and '
    '"indirect via SII_LOG" are the products a1×b1 and a2×b2; '
    '"total_indirect" is their sum. Mplus additionally prints a "sum of '
    'indirect" line, which with two parallel mediators and no chained path '
    'is the same quantity as "total indirect"; the two are checked for '
    'equality when this table is built and only one is listed. P (Holm) applies the Holm-Bonferroni '
    'step-down across the indirect-effect family within each model — the two '
    'mediators are tested together, so the pair is the family. Total and '
    'direct effects are single pre-specified quantities and are not '
    'multiplicity-adjusted.',

    # S5
    'S5b. The same interaction specification fitted with log SII as the '
    'dependent variable (n = 8,710-8,716; the index has less missingness '
    'than biological age). All six interaction terms, core and '
    'volume-adjusted, are non-significant (P >= 0.125), and no simple slope '
    'reaches significance.',

    'S5. Age-moderation models are fitted on all adults with biological-age '
    'advancement observed (n = 8,523 or 8,517 by metric), with the rhythm '
    'metric, continuous age, and their product predicting biological-age '
    'advancement. Simple slopes are the rhythm coefficient evaluated at one '
    'standard deviation below the mean age, at the mean, and one above, '
    'within the same model. These models take biological-age advancement as '
    'the dependent variable and involve no mediation structure.',

    # S6
    'S6, R-square columns. Each is the proportion of variance in that '
    'dependent variable explained by everything predicting it in the model -- '
    'the rhythm metric AND the six covariates -- not the share attributable to '
    'the rhythm metric alone; the per-predictor decomposition is in '
    'Supplementary Fig. S6. Chronological age contributes almost '
    'nothing to the biological-age equations, because the dependent variable '
    'is biological minus chronological age and the latter is therefore '
    'removed by construction; body mass index is the dominant covariate. '
    'The equations for biological-age advancement reach R-square about 0.09 to '
    '0.11; those for the log immune-inflammation index reach 0.01 to 0.04. '
    'That order-of-magnitude difference is independent of the path counts and '
    'points the same way: the index is close to unpredictable from these '
    'variables as a whole, not merely unrelated to rhythm.',
    'The cognition column is kept separate because Mplus reports it under a '
    'different heading, not because it is a different kind of quantity. For an '
    'endogenous latent factor it is the proportion of the FACTOR variance '
    'explained by its structural predictors -- the rhythm metric, both '
    'biological measures and the six covariates -- and is therefore the same '
    'quantity as the PHQ-9 column, not a measurement statistic. It is large '
    '(about 0.57) mainly because chronological age and education predict '
    'cognitive performance strongly within the 60-and-over sample. How well '
    'the three sub-tests converge on the factor is a separate matter, read '
    'from the standardised loadings (0.64, 0.64, 0.85) and the corresponding '
    'observed-variable R-squares (0.41, 0.41, 0.72), which are the squares of '
    'those loadings.',

    'S6. Fit indices are reported for completeness. Saturated path models '
    '(the depression models, which have no latent factor) have zero degrees '
    'of freedom, so their chi-square, CFI, TLI and RMSEA carry no '
    'information; fit is informative only for the cognition models, where '
    'the three-indicator factor imposes restrictions. loadings_positive '
    'confirms every cognition loading is positive, i.e. the factor is '
    'oriented so that higher scores mean better performance.',

    # S7
    'S7. The rest-activity rhythm is summarised by five non-parametric '
    'metrics; three are modelled as exposures. The most active 10-h period '
    '(M10) is excluded because it is largely total activity volume '
    '(R² = 0.78 on log total MIMS; only 47% of its variance survives volume '
    'adjustment), and the least active 5-h period (L5) because it is nearly '
    'collinear with relative amplitude (r = -0.88), which is derived from '
    'it. All quantities in S7 are computed from the analytic sample, not '
    'assumed.',

    # Secondary and sensitivity models
    f'Depression models labelled {age_label(POOLED)} pool the full adult sample rather than '
    f'stratifying by age. The {age_label(YOUNG)} and {age_label(OLD)} cells are the primary '
    'analysis; the pooled models are reported so that the effect of age '
    'stratification can be read directly, not because they corroborate the '
    'primary result.',
    'IV_Q and RA_Q are quintile-coded versions of the corresponding rhythm '
    'metric: the observed values are cut at their own quintiles within adults '
    'and scored 1 to 5, then entered as a single linear term. Cut-points are '
    'unweighted. IV_Q addresses the skew of intradaily variability (skewness '
    '2.98, kurtosis 13.6, maximum 9.6 s.d.), which robust maximum '
    'likelihood protects the standard error against but not the point '
    'estimate; RA_Q was added after spline models rejected linearity for '
    'relative amplitude against both outcomes. Like every other row in this '
    'table these coefficients are STDYX-standardised, so they are per 1 s.d. '
    'of the quintile score, not per quintile step. They are not expected to '
    'equal the continuous rows: the quintile coding is a rank recoding, and '
    'the difference between the two is the sensitivity result rather than a '
    'difference of units.',
    'Three cognition specifications were estimated twice under different '
    'file names; the duplicate is omitted here and identified in the code '
    'repository.',
]


def write_supp(paths, effects, holm, info, inter):
    out = SUPP / 'Supp_Tables.xlsx'
    with pd.ExcelWriter(out, engine='openpyxl') as xw:
        # Supplementary table series: S1-S2 sample cascade and missingness
        # (script 6), S3-S7 here, S8-S12 the notebook robustness tables.
        table_supp_all_paths(paths).to_excel(xw, sheet_name='Supp Table S3 all paths', index=False)
        table_supp_all_effects(effects, holm).to_excel(
            xw, 'Supp Table S4 all effects', index=False)
        table_main_moderation(inter, include_volume=True).to_excel(xw, sheet_name='Supp Table S5 moderation', index=False)
        if (inter.outcome == 'log SII').any():
            table_main_moderation(inter, outcome='log SII', include_volume=True).to_excel(
                xw, sheet_name='Supp Table S5b moderation SII', index=False)
        table_supp_fit(info).to_excel(xw, sheet_name='Supp Table S6 model fit', index=False)
        sel = metric_selection()
        if sel is not None:
            sel.to_excel(xw, sheet_name='Supp Table S7 metric selection', index=False)
        pd.DataFrame({'Notes': SUPP_NOTES}).to_excel(xw, sheet_name='Notes', index=False)
        _autofit(xw)
    return out


# Supplementary Table S20: unadjusted against adjusted estimates (STROBE 16a)
S20_STEM = 'SuppTableS20_Unadjusted_vs_Adjusted'
S20_ROWS = [  # (source, key, label)
    ('path', 'a1', 'Rhythm → biological-age advancement'),
    ('path', 'a2', 'Rhythm → log SII'),
    ('path', 'b1', 'Biological-age advancement → outcome'),
    ('path', 'b2', 'log SII → outcome'),
    ('effect', 'direct', 'Direct association'),
    ('holm', 'BA_ADV', 'Indirect via biological-age advancement'),
    ('holm', 'SII_LOG', 'Indirect via log SII'),
    ('effect', 'total', 'Total association'),
]


def _model_rows(paths, effects, holm, outcome, cell, exposure, role):
    """{key: (estimate, ci_lo, ci_hi)} and n for one model, selected by role."""
    sel = dict(outcome=outcome, age_cell=cell, exposure=exposure, role=role)
    p = paths[(~paths.volume_adjusted) & (~paths.is_duplicate)]
    for k, v in sel.items():
        p = p[p[k] == v]
    if not len(p):
        return None, None
    if p.model.nunique() != 1:
        raise ValueError(f'{p.model.nunique()} models match {sel}: {sorted(p.model.unique())}')
    model = p.model.iloc[0]
    e = effects[(effects.model == model) & (~effects.is_duplicate)]
    h = holm[holm.model == model]
    out = {}
    for src, key, _ in S20_ROWS:
        if src == 'path':
            r = p[p.path == key]
            out[key] = (r.beta.iloc[0], r.ci_lo.iloc[0], r.ci_hi.iloc[0]) if len(r) else None
        elif src == 'effect':
            r = e[(e.effect == key) & e.via.isna()]
            out[key] = (r.estimate.iloc[0], r.ci_lo.iloc[0], r.ci_hi.iloc[0]) if len(r) else None
        else:
            r = h[h.via == key]
            out[key] = (r.estimate.iloc[0], r.ci_lo.iloc[0], r.ci_hi.iloc[0]) if len(r) else None
    return out, int(p.n.iloc[0])


def table_supp_unadjusted(paths, effects, holm):
    """Unadjusted (m_*_crude) against adjusted (primary) STDYX estimates, one
    block per primary model. Raises if any unadjusted model is missing or was
    fitted to a different n from its adjusted counterpart."""
    missing, unequal, rows = [], [], []
    for outcome, cell in CELLS:
        for exposure in EXPOSURES:
            adj, n_adj = _model_rows(paths, effects, holm, outcome, cell, exposure, 'primary')
            crude, n_crude = _model_rows(paths, effects, holm, outcome, cell, exposure,
                                         'reporting: unadjusted')
            if adj is None:
                continue
            if crude is None:
                missing.append(f'{outcome}/{cell}/{exposure}')
                continue
            if n_crude != n_adj:
                unequal.append(f'{outcome}/{cell}/{exposure}: unadjusted n = {n_crude:,}, '
                               f'adjusted n = {n_adj:,}')
            for src, key, lab in S20_ROWS:
                u, a = crude.get(key), adj.get(key)
                rows.append({'Outcome': outcome, 'Age group': age_label(cell),
                             'Rhythm metric': f'{EXP_NAME[exposure]} ({exposure})',
                             'Association': lab,
                             'Unadjusted β (95% CI)': fmt_ci(*u) if u else '',
                             'Adjusted β (95% CI)': fmt_ci(*a) if a else '',
                             'n, unadjusted': n_crude, 'n, adjusted': n_adj})
    if missing:
        raise FileNotFoundError(
            f'{len(missing)} unadjusted model(s) have no output: {missing}. Run '
            "them first: cd scripts/9_mplus_models && bash run_all.sh 'm_*_crude.inp'")
    if unequal:
        raise ValueError(
            'an unadjusted model was not fitted to the same participants as its '
            'adjusted counterpart, so the two are not comparable: ' + '; '.join(unequal)
            + '. Check the SUBPOPULATION statement (AND COVOK EQ 1) and '
            'nhanes_sem_covok.dat (script 9).')
    return pd.DataFrame(rows)


S20_NOTES = [
    'Supplementary Table S20 | Unadjusted and covariate-adjusted estimates from '
    'the primary structural models.',
    'Unadjusted and adjusted estimates come from otherwise identical '
    'complex-survey structural equation models fitted to the same participants. '
    'Unadjusted models contain the rhythm metric, KDM biological-age advancement '
    'and log SII in the prespecified parallel-pathway structure and no '
    'covariates; adjusted models are the primary models, which add chronological '
    'age, sex, body mass index, education, accelerometer wear time and '
    'self-reported sleep duration to each structural equation. Both use the '
    'NHANES sampling weights, strata and primary sampling units (Mplus TYPE = '
    'COMPLEX), robust maximum likelihood, full-information maximum likelihood '
    'for the dependent variables, the residual covariance between the two '
    'biological measures and, for cognition, the same latent-factor '
    'specification.',
    'The adjusted models drop participants with a missing covariate; the '
    'unadjusted models select the same participants explicitly, by adding an '
    'indicator that all six covariates are observed (COVOK EQ 1) to the '
    'SUBPOPULATION statement that defines the age cell, so n is identical '
    'within each block and the two columns differ only in covariate '
    'adjustment. The comparison is descriptive: the adjusted '
    'models are the prespecified primary analysis, and no inference is drawn '
    'from the unadjusted estimates.',
    'Coefficients are Mplus STDYX standardised solutions (per SD of the '
    'predictor and of the outcome; the latent cognition factor has unit '
    'residual variance) with delta-method 95% confidence intervals. Rows: the '
    'two rhythm-to-biological-measure paths, the two biological-measure-to-'
    'outcome paths, the direct association, the two specific indirect '
    'associations and the total association. Model files: '
    'm_{dep,cog}_{young,old}_{ra,is,iv}.inp (adjusted) and the same names '
    'with the suffix _crude (unadjusted).',
    'KDM, Klemera-Doubal method; PHQ-9, 9-item Patient Health Questionnaire; '
    'SII, systemic immune-inflammation index.',
]


def write_supp_unadjusted(paths, effects, holm):
    t = table_supp_unadjusted(paths, effects, holm)
    out = SUPP / f'{S20_STEM}.xlsx'
    with pd.ExcelWriter(out, engine='openpyxl') as xw:
        t.to_excel(xw, sheet_name='Supp Table S20', index=False)
        pd.DataFrame({'Notes': S20_NOTES}).to_excel(xw, sheet_name='Notes', index=False)
        _autofit(xw)
    t.to_csv(out.with_suffix('.csv'), index=False)
    return out


# Figures
def fig1_specificity(paths):
    """Supp Fig S5: the a1 path (rhythm -> KDM-BA advancement) for each rhythm
    metric, in each of the three structural models, core against
    volume-adjusted covariates."""
    d = paths[(paths.family == 'mediation') & (paths.path == 'a1')
              & (~paths.is_duplicate)]
    fig, axes = plt.subplots(1, 3, figsize=(W2, 62 * MM), sharex=True)
    src = []
    model_title = {('PHQ-9', YOUNG): f'Depressive-symptom model,\n{age_label(YOUNG)} years',
                   ('PHQ-9', OLD): f'Depressive-symptom model,\n{age_label(OLD)} years',
                   ('cognition', OLD): f'Cognitive model,\n{age_label(OLD)} years'}
    for ax, (outcome, cell) in zip(axes, CELLS):
        sub = d[(d.outcome == outcome) & (d.age_cell == cell)]
        y, yt, yl = 0, [], []
        for exp in EXPOSURES:
            for vol, off, mk in [(False, 0.15, 'o'), (True, -0.15, 's')]:
                r = sub[(sub.exposure == exp) & (sub.volume_adjusted == vol)]
                if not len(r):
                    continue
                r = r.iloc[0]
                sig = r.p < 0.05
                # Hue identifies the metric; fill encodes significance
                # (open = P >= 0.05).
                col = EXP_COL[exp]
                ax.errorbar(r.beta, y + off,
                            xerr=[[r.beta - r.ci_lo], [r.ci_hi - r.beta]],
                            fmt=mk, ms=3.4, color=col, mfc=col if sig else 'white',
                            ecolor=col, elinewidth=0.9, capsize=1.8, mew=0.9)
                src.append(dict(panel=f'{outcome}, {age_label(cell)}', metric=exp,
                                volume_adjusted=vol, beta=r.beta, ci_lo=r.ci_lo,
                                ci_hi=r.ci_hi, p=r.p, n=int(r.n)))
            yt.append(y); yl.append(exp); y -= 1
        ax.axvline(0, color='0.4', lw=0.5, ls=(0, (3, 2)))
        ax.set_yticks(yt); ax.set_yticklabels(yl)
        ax.set_ylim(y + 0.5, 0.55)
        ax.set_title(model_title[(outcome, cell)],
                     color=DEP if outcome == 'PHQ-9' else COG, pad=3)
        ax.set_xlabel('Rhythm\u2013KDM-BA advancement\nassociation (\u03b2)')
    axes[0].set_ylabel('Rhythm metric')
    h = [Line2D([], [], marker='o', ls='', color='0.35', ms=3.4, label='Core covariates'),
         Line2D([], [], marker='s', ls='', color='0.35', ms=3.4,
                label='Core covariates + activity volume'),
         Line2D([], [], marker='o', ls='', mfc='white', mec=GREY, color=GREY, ms=3.4,
                label='P \u2265 0.05')]
    fig.legend(handles=h, loc='lower center', ncol=3, frameon=False,
               bbox_to_anchor=(0.5, -0.10))
    fig.tight_layout()
    for ax, letter in zip(axes, 'abc'):
        fig.text(ax.get_position().x0 - 0.03, 0.99, letter, ha='right', va='top',
                 fontsize=10, fontweight='bold')
    cap = ['Supplementary Fig. S5 | Rhythm-to-biological-age association, core '
           'against volume-adjusted covariates.',
           'All three panels show the same path, the association of each rhythm '
           'metric with KDM biological-age advancement (a1), as estimated inside '
           'each of the three structural models: a, the depressive-symptom model, '
           f'adults aged {age_label(YOUNG)} years; b, the depressive-symptom model, '
           f'{age_label(OLD)} years; c, the cognitive model, {age_label(OLD)} years. '
           'They are not associations of the rhythm metric with depressive symptoms '
           'or cognition.',
           'Points are Mplus STDYX coefficients, standardized within each model; '
           'bars are 95% delta-method confidence intervals; open markers indicate '
           'P \u2265 0.05. Intervals and P values are not adjusted for multiple '
           'comparisons. Hue identifies the metric.',
           'Circles adjust for core covariates (age, sex, body mass index, '
           'education, accelerometer wear time, sleep duration); squares add '
           'total daily activity volume. Both use the same participants. '
           'Estimates are in Supplementary Table S3.']
    return save_fig(fig, FIGNUM['rhythm_to_ba'], pd.DataFrame(src), cap)


def reference_age():
    """Mean and s.d. of age in the standardisation reference sample (adults
    aged 20+ in the depressive-symptom analytic universe), read from the
    stage-9 manifest so that the ages quoted on Fig. 4 are the ones the
    product term was built with. None if the manifest is absent."""
    f = BASE / 'data' / 'mplus' / 'nhanes_sem_vars.txt'
    if not f.exists():
        return None
    m = re.search(r'^#\s+AGE\s+source = RIDAGEYR\s+mean =\s+([\d.]+)\s+sd =\s+([\d.]+)',
                  f.read_text(), re.M)
    return (float(m.group(1)), float(m.group(2))) if m else None


def fig2_moderation(inter):
    """Fig 4: simple slopes of the rhythm-to-biological-age association at -1 s.d., mean and +1 s.d. of age.

    One point with its 95% confidence interval at each of the three ages at
    which the slope was estimated (the model gives intervals at those ages
    only); the connecting line is a visual guide, not an interval."""
    fig, axes = plt.subplots(1, 2, figsize=(W2, 62 * MM), sharey=True)
    src = []
    keys = ['SLOPE_LO', 'SLOPE_MID', 'SLOPE_HI']
    xs = np.array([-1.0, 0.0, 1.0])
    # metrics are dodged slightly so that the intervals do not overprint
    dodge = {e: o for e, o in zip(EXPOSURES, np.linspace(-0.09, 0.09, len(EXPOSURES)))}
    ref = reference_age()
    for ax, vol in zip(axes, (False, True)):
        blk = inter[(inter.volume_adjusted.astype(bool) == vol)
                    & (inter.outcome == 'KDM-BA advancement')].copy()
        blk['_o'] = blk.exposure.map({e: i for i, e in enumerate(EXPOSURES)})
        blk = blk.sort_values('_o')
        for _, r in blk.iterrows():
            ys = np.array([r.get(f'{k}_beta', np.nan) for k in keys], float)
            lo = np.array([r.get(f'{k}_lo', np.nan) for k in keys], float)
            hi = np.array([r.get(f'{k}_hi', np.nan) for k in keys], float)
            ok = np.isfinite(ys)
            if not ok.any():
                continue
            c = EXP_COL[r.exposure]
            x = xs + dodge[r.exposure]
            ax.plot(x[ok], ys[ok], '-', color=c, lw=0.8, alpha=0.8, zorder=2)
            b = ok & np.isfinite(lo) & np.isfinite(hi)
            ax.errorbar(x[b], ys[b], yerr=[ys[b] - lo[b], hi[b] - ys[b]], fmt='o',
                        color=c, mfc=c, ecolor=c, ms=3.6, elinewidth=0.9,
                        capsize=2.2, mew=0.9, label=r.exposure, zorder=3)
            for k, xv in zip(keys, xs):
                src.append(dict(panel='+ activity volume' if vol else 'core covariates',
                                metric=r.exposure, age_point=k.replace('SLOPE_', ''),
                                age_sd=xv,
                                age_years=(ref[0] + xv * ref[1]) if ref else np.nan,
                                b=r.get(f'{k}_beta'),
                                ci_lo=r.get(f'{k}_lo'), ci_hi=r.get(f'{k}_hi'),
                                p=r.get(f'{k}_p'), interaction_b=r.interaction_beta,
                                interaction_p=r.interaction_p, n=int(r.n)))
        ax.axhline(0, color='0.4', lw=0.5, ls=(0, (3, 2)), zorder=1)
        ax.set_xticks([-1, 0, 1])
        if ref:
            ax.set_xticklabels([f'\u22121 s.d.\n({ref[0] - ref[1]:.0f} y)',
                                f'Mean\n({ref[0]:.0f} y)',
                                f'+1 s.d.\n({ref[0] + ref[1]:.0f} y)'])
        else:
            ax.set_xticklabels(['\u22121 s.d.', 'Mean', '+1 s.d.'])
        ax.set_xlim(-1.45, 1.45)
        ax.set_xlabel('Age')
        ax.set_title('+ activity volume' if vol else 'Core covariates', pad=3,
                     loc='left')
    axes[0].set_ylabel('Association with KDM-BA advancement, b')
    axes[1].legend(frameon=False, loc='lower left', handlelength=1.4,
                   handletextpad=0.6)
    fig.tight_layout()
    for ax, letter in zip(axes, 'ab'):
        fig.text(ax.get_position().x0 - 0.045, 0.985, letter,
                 ha='left', va='top', fontsize=10, fontweight='bold')
    sii_s, support_s, direction_s = moderation_facts(inter)
    ba = inter[inter.outcome == 'KDM-BA advancement']
    core, volb = ba[~ba.volume_adjusted.astype(bool)], ba[ba.volume_adjusted.astype(bool)]
    name = {'IV': 'intradaily variability', 'IS': 'interdaily stability',
            'RA': 'relative amplitude'}

    def fmt_inter(r):
        p = 'P < 0.001' if r.interaction_p < 0.001 else f'P = {r.interaction_p:.3f}'
        return (f'{name[r.exposure]} {r.interaction_beta:+.3f} '
                f'(95% CI {r.interaction_lo:.3f} to {r.interaction_hi:.3f}; {p})')
    vol_s = ('With activity volume added, the interaction estimates are '
             + '; '.join(fmt_inter(r) for _, r in volb.sort_values('exposure', key=lambda s: s.map({e: i for i, e in enumerate(EXPOSURES)})).iterrows())
             + '.') if len(volb) else ''
    ages_s = (f' (approximately {ref[0] - ref[1]:.0f}, {ref[0]:.0f} and {ref[0] + ref[1]:.0f} '
              'years in the reference sample)') if ref else ''
    n_s = '; '.join(f'{int(n):,} ({", ".join(sorted(g.exposure))})'
                    for n, g in core.groupby('n'))
    spline_s = ('Tests of the age interaction with a flexible (natural-spline) '
                'functional form are separate models, reported in Supplementary Table 21.'
                if (SUPP / 'SuppTableS21_P1_FunctionalForm.xlsx').exists() else '')
    cap = ['Fig. 4 | Associations of rest-activity rhythm metrics with KDM-BA '
           'advancement at selected ages.',
           'Points are the simple slopes of the linear age-interaction models '
           '(Table 3) at one standard deviation below the mean age, at the mean '
           f'and one standard deviation above{ages_s}; vertical bars are 95% '
           'confidence intervals, estimated at those three ages only; the '
           'connecting lines are visual guides.',
           'Coefficients (b) are from the unstandardised solution on the common '
           'reference-standardised scale: the rhythm metric, age and '
           'biological-age advancement were z-standardised on the reference '
           'sample before the product term was formed. They are not STDYX '
           'values and are not comparable with Table 2.',
           'a, models adjusted for age, sex, body mass index, education, '
           'accelerometer wear time and sleep duration; b, additionally adjusted '
           'for total daily activity volume.',
           support_s, vol_s, direction_s,
           'The corresponding interactions with log SII as the dependent '
           f'variable, under the same complex-survey specification, {sii_s}.',
           spline_s,
           f'n = {n_s}.',
           'KDM-BA, Klemera-Doubal biological age; RA, relative amplitude; IS, '
           'interdaily stability; IV, intradaily variability.']
    cap = [c for c in cap if c]
    return save_fig(fig, FIGNUM['age_moderation'], pd.DataFrame(src), cap)


MED_COL = {'BA_ADV': KDM_BA_COLOR, 'SII_LOG': SII_COLOR}
MED_NAME = {'BA_ADV': 'KDM biological-age advancement',
            'SII_LOG': 'Systemic immune-inflammation index'}


def fig_dissociation(paths, holm):
    """Fig 2: a 2x2 grid of a-paths (top row) and indirect associations (bottom row) by biological measure.

    Columns are the measure (KDM-BA left, log SII right). Panels a/b facet by
    age and draw the depression-model a-paths; the cognition-model estimates
    of the same paths at 60+ agree to within 0.001. Panels c/d facet by
    outcome cell. Hue is the rhythm metric. Open markers mean P >= 0.05:
    unadjusted P in a/b (structural paths, the rule of Fig. 3), Holm-adjusted
    P in c/d (Holm within each model, across its two indirect associations).
    """
    METRICS = EXPOSURES
    MET_LAB = {'RA': 'RA', 'IS': 'IS', 'IV': 'IV'}
    AGES = [(YOUNG, f'Aged {age_label(YOUNG)}'), (OLD, f'Aged {OLD_MIN_AGE} and over')]
    CELLS3 = [('PHQ-9', YOUNG, f'PHQ-9, {age_label(YOUNG)}'),
              ('PHQ-9', OLD, f'PHQ-9, {age_label(OLD)}'),
              ('cognition', OLD, f'Cognition, {age_label(OLD)}')]

    fig = plt.figure(figsize=(W2, 128 * MM))
    gs = fig.add_gridspec(2, 2, height_ratios=[6.2, 8.8], hspace=0.42,
                          wspace=0.08)
    axA = fig.add_subplot(gs[0, 0]); axB = fig.add_subplot(gs[0, 1], sharey=axA)
    axC = fig.add_subplot(gs[1, 0]); axD = fig.add_subplot(gs[1, 1], sharey=axC)
    src, n_sig = [], {}

    # Top row: a-paths, faceted by age, depression-model estimates.
    def draw_apath(ax, key, med_name, panel):
        sig = tot = 0
        yt, yl = [], []
        y = 0
        for cell, cell_lab in AGES:
            ax.text(0.01, -y + 0.62, cell_lab, transform=ax.get_yaxis_transform(),
                    fontsize=7, color='0.35', va='bottom')
            for exp in METRICS:
                r = primary(paths, outcome='PHQ-9', age_cell=cell,
                            exposure=exp, path=key)
                if r is None:
                    continue
                c = EXP_COL[exp]
                keep = r.p < 0.05          # fill encodes unadjusted P, as in Fig. 3
                ax.errorbar(r.beta, -y, xerr=[[r.beta - r.ci_lo], [r.ci_hi - r.beta]],
                            fmt='o', ms=3.4, color=c, mfc=c if keep else 'white',
                            ecolor=c, elinewidth=0.9, capsize=1.8, mew=0.9)
                yt.append(-y); yl.append(MET_LAB[exp])
                tot += 1; sig += int(r.p < 0.05)
                src.append(dict(panel=panel, group=cell_lab, metric=exp,
                                beta=r.beta, ci_lo=r.ci_lo, ci_hi=r.ci_hi,
                                p=r.p, p_holm=np.nan, model=r.model))
                y += 1
            y += 0.9
        ax.axvline(0, color='0.4', lw=0.5, ls=(0, (3, 2)))
        ax.set_yticks(yt); ax.set_yticklabels(yl)
        ax.set_ylim(min(yt) - 0.7, 1.0)
        ax.set_xlabel(r'Standardized a-path coefficient, $\beta$')
        ax.set_title(f'Associations with {med_name}', pad=3, loc='left')
        n_sig[panel] = (sig, tot)

    draw_apath(axA, 'a1', 'KDM-BA advancement', 'a')
    draw_apath(axB, 'a2', 'log SII', 'b')

    # Bottom row: indirect associations, faceted by outcome cell.
    def draw_indirect(ax, med, med_name, panel):
        sig = tot = 0
        yt, yl = [], []
        y = 0
        for outcome, cell, cell_lab in CELLS3:
            ax.text(0.01, -y + 0.62, cell_lab, transform=ax.get_yaxis_transform(),
                    fontsize=7, color='0.35', va='bottom')
            for exp in METRICS:
                h = primary(holm, outcome=outcome, age_cell=cell,
                            exposure=exp, via=med)
                if h is None:
                    continue
                c = EXP_COL[exp]
                keep = h.p_holm < 0.05
                ax.errorbar(h.estimate, -y,
                            xerr=[[h.estimate - h.ci_lo], [h.ci_hi - h.estimate]],
                            fmt='o', ms=3.4, color=c, mfc=c if keep else 'white',
                            ecolor=c, elinewidth=0.9, capsize=1.8, mew=0.9)
                yt.append(-y); yl.append(MET_LAB[exp])
                tot += 1; sig += int(keep)
                src.append(dict(panel=panel, group=cell_lab, metric=exp,
                                beta=h.estimate, ci_lo=h.ci_lo, ci_hi=h.ci_hi,
                                p=h.p, p_holm=h.p_holm, model=h.model))
                y += 1
            y += 0.9
        ax.axvline(0, color='0.4', lw=0.5, ls=(0, (3, 2)))
        ax.set_yticks(yt); ax.set_yticklabels(yl)
        ax.set_ylim(min(yt) - 0.7, 1.0)
        ax.set_xlabel(r'Standardized indirect association, $\beta_{indirect}$')
        ax.set_title(f'Indirect via {med_name}', pad=3, loc='left')
        n_sig[panel] = (sig, tot)

    draw_indirect(axC, 'BA_ADV', 'KDM-BA advancement', 'c')
    draw_indirect(axD, 'SII_LOG', 'log SII', 'd')

    for ax in (axB, axD):
        plt.setp(ax.get_yticklabels(), visible=False)
    # A and B share one x-range; C and D share another.
    for pair in ((axA, axB), (axC, axD)):
        lo = min(ax.get_xlim()[0] for ax in pair)
        hi = max(ax.get_xlim()[1] for ax in pair)
        for ax in pair:
            ax.set_xlim(lo, hi)

    h = [Line2D([], [], marker='o', ls='', color=EXP_COL[e], ms=3.4,
                label={'RA': 'Relative amplitude (RA)',
                       'IS': 'Interdaily stability (IS)',
                       'IV': 'Intradaily variability (IV)'}[e])
         for e in METRICS]
    h.append(Line2D([], [], marker='o', ls='', mfc='white', mec='#555555',
                    color='#555555', ms=3.4,
                    label='open = P \u2265 0.05 (a, b unadjusted; c, d Holm-adjusted)'))
    fig.legend(handles=h, loc='lower center', ncol=2, frameon=False,
               bbox_to_anchor=(0.5, -0.06), columnspacing=2.5)
    fig.tight_layout()
    for ax, letter in zip((axA, axB, axC, axD), 'abcd'):
        fig.text(ax.get_position().x0 - 0.055, ax.get_position().y1 + 0.012,
                 letter, ha='left', va='bottom', fontsize=10, fontweight='bold')

    cap = ['Fig. 2 | Rest-activity rhythm associations with the two candidate '
           'biological measures and the indirect associations through them.',
           'a, b, associations of the three rest-activity rhythm metrics with '
           'KDM-BA advancement (a) and log SII (b), by age group, from the '
           'depressive-symptom models; the cognition-model estimates of the '
           'same paths at 60 years and over agree to within 0.001 '
           '(Supplementary Table S3). c, d, indirect associations with '
           'depressive symptoms and cognitive function through KDM-BA '
           'advancement (c) and log SII (d), by outcome cell.',
           'Points are STDYX standardised coefficients from the core '
           'complex-survey structural equation models; bars are 95% '
           'delta-method confidence intervals, which are not '
           'multiplicity-adjusted. Hue identifies the rhythm metric throughout.',
           'Open markers indicate P \u2265 0.05: unadjusted P in a and b, '
           'Holm-adjusted P in c and d, where the adjustment is applied within '
           'each model to its two indirect associations.',
           'The sign of an indirect association is the product of the '
           'rhythm-to-measure and measure-to-outcome paths, so it need not '
           'match the a-path: two negative paths give a positive indirect '
           'association, one of each gives a negative one.',
           'Core-covariate models. Volume-adjusted counterparts are in '
           'Supplementary Tables S3-S4 and Supplementary Fig. S5.',
           'KDM-BA, Klemera-Doubal biological age; SII, systemic '
           'immune-inflammation index.']
    return save_fig(fig, FIGNUM['dissociation'], pd.DataFrame(src), cap)


def fig3_paths(paths, effects, holm):
    """Fig 3: full path decomposition for every rhythm metric across the three cells.

    Rows: the four structural paths, the direct association, the two
    indirect associations (one per biological measure) and the total.
    Fill encodes P < 0.05: unadjusted for the structural paths, the direct and
    the total association; Holm-adjusted (within each model, across its two
    indirect associations) for the two indirect rows, as in Fig. 2."""
    fig, axes = plt.subplots(1, 3, figsize=(W2, 92 * MM), sharex=True)
    src = []
    labels = {'a1': r'a$_1$  rhythm $\rightarrow$ KDM-BA advancement',
              'b1': r'b$_1$  KDM-BA advancement $\rightarrow$ outcome',
              'a2': r'a$_2$  rhythm $\rightarrow$ log SII',
              'b2': r'b$_2$  log SII $\rightarrow$ outcome',
              'c_prime': "c\u2032  direct association"}
    order = ['a1', 'b1', 'a2', 'b2', 'c_prime']
    terms = [(k, labels[k], 'o', None) for k in order] + \
            [('indirect', 'Indirect via KDM-BA advancement', 'D', 'BA_ADV'),
             ('indirect', 'Indirect via log SII', 'D', 'SII_LOG'),
             ('total', 'Total association', 'D', None)]
    # one row per term, three metrics dodged within the row
    offs = {e: o for e, o in zip(EXPOSURES, np.linspace(0.27, -0.27, len(EXPOSURES)))}

    for ax, (outcome, cell) in zip(axes, CELLS):
        # Alternating pale bands separate the rows; they carry no meaning.
        for y in range(len(terms)):
            if y % 2 == 0:
                ax.axhspan(-y - 0.5, -y + 0.5, color='#F4F4F4', lw=0, zorder=0)
        yt, yl = [], []
        for y, (key, lab, mk, via) in enumerate(terms):
            for exp in EXPOSURES:
                if mk == 'o':
                    r = primary(paths, outcome=outcome, age_cell=cell,
                                exposure=exp, path=key)
                    if r is None:
                        continue
                    est, lo, hi, pv, p_adj, rule = r.beta, r.ci_lo, r.ci_hi, r.p, np.nan, 'unadjusted'
                elif key == 'indirect':
                    h = primary(holm, outcome=outcome, age_cell=cell,
                                exposure=exp, via=via)
                    if h is None:
                        continue
                    est, lo, hi, pv, p_adj, rule = (h.estimate, h.ci_lo, h.ci_hi,
                                                    h.p, h.p_holm, 'Holm-adjusted')
                else:
                    x = primary(effects, outcome=outcome, age_cell=cell,
                                exposure=exp, effect=key, via=None)
                    if x is None:
                        continue
                    est, lo, hi, pv, p_adj, rule = x.estimate, x.ci_lo, x.ci_hi, x.p, np.nan, 'unadjusted'
                sig = (p_adj if rule == 'Holm-adjusted' else pv) < 0.05
                col = EXP_COL[exp]      # hue = metric; fill = significance
                ax.errorbar(est, -y + offs[exp],
                            xerr=[[est - lo], [hi - est]], fmt=mk, ms=3.4,
                            color=col, mfc=col if sig else 'white', ecolor=col,
                            elinewidth=0.9, capsize=1.8, mew=0.9, zorder=3)
                src.append(dict(panel=f'{outcome}, {age_label(cell)}', metric=exp, term=lab,
                                beta=est, ci_lo=lo, ci_hi=hi, p=pv, p_holm=p_adj,
                                fill_rule=rule, filled=bool(sig)))
            yt.append(-y); yl.append(lab)
        ax.axvline(0, color='0.4', lw=0.5, ls=(0, (3, 2)), zorder=1)
        ax.set_yticks(yt); ax.set_yticklabels(yl if ax is axes[0] else [''] * len(yt))
        ax.set_ylim(-len(terms) + 0.4, 0.6)
        ax.set_title(f'{outcome}, {age_label(cell)}',
                     color=DEP if outcome == 'PHQ-9' else COG, pad=4)
        ax.set_xlabel(r'Standardized coefficient, $\beta$')
    h = [Line2D([], [], marker='o', ls='', color=EXP_COL[e], ms=3.4,
                label=f'{EXP_NAME[e]} ({e})') for e in EXPOSURES]
    h += [Line2D([], [], marker='o', ls='', mfc='white', mec='#555555',
                 color='#555555', ms=3.4,
                 label='open = P \u2265 0.05 (indirect rows: Holm-adjusted)')]
    fig.legend(handles=h, loc='lower center', ncol=4, frameon=False,
               bbox_to_anchor=(0.5, -0.05))
    fig.tight_layout()
    for ax, letter in zip(axes, 'abc'):
        fig.text(ax.get_position().x0 - (0.19 if ax is axes[0] else 0.02),
                 ax.get_position().y1 + 0.03, letter, ha='left', va='bottom',
                 fontsize=10, fontweight='bold')
    cap = ['Fig. 3 | Path decomposition for each rest-activity rhythm metric.',
           'a, depressive symptoms (PHQ-9) among adults aged 20-59 years; b, '
           'depressive symptoms among adults aged 60 years and over; c, cognitive '
           'function among adults aged 60 years and over.',
           'Rows: the association of the rhythm metric with KDM-BA advancement '
           '(a1) and with log SII (a2); the associations of KDM-BA advancement '
           '(b1) and log SII (b2) with the outcome; the direct association '
           'conditional on both biological measures (c\u2032); the indirect '
           'association through each biological measure; and the total '
           'association.',
           'Points are STDYX standardised coefficients from the core '
           'complex-survey structural equation models (circles, structural '
           'paths; diamonds, effect decompositions); bars are 95% delta-method '
           'confidence intervals, which are not multiplicity-adjusted. Hue '
           'identifies the metric throughout.',
           'Open markers indicate P \u2265 0.05: unadjusted P for the structural '
           'paths, the direct and the total association; Holm-adjusted P for '
           'the two indirect rows, where the adjustment is applied within each '
           'model to its two indirect associations (the rule of Fig. 2).',
           'Estimates are adjusted for core covariates; the volume-adjusted '
           'counterparts are in Supplementary Tables S3-S4.',
           'Alternating shading separates the rows and carries no other meaning.',
           'KDM-BA, Klemera-Doubal biological age; SII, systemic '
           'immune-inflammation index; RA, relative amplitude; IS, interdaily '
           'stability; IV, intradaily variability.']
    return save_fig(fig, FIGNUM['decomposition'], pd.DataFrame(src), cap)


def main():
    est, eff, info = parse_dir(MODELS)
    info = flag_duplicates(est, label_models(info))
    paths = path_table(est, info)
    effects = effect_table(eff, info)
    inter = interaction_table(est, info)
    holm = indirect_with_holm(effects)
    props = mediation_proportion(est, effects)

    neg = info[info.loadings_positive == False]
    if len(neg):
        print('STOP: negative factor loadings in', list(neg.model))
        return 1

    q = write_qc(est, eff, info, paths, effects, inter, holm, props)
    mains = write_main(paths, effects, holm, props, inter, est)
    s = write_supp(paths, effects, holm, info, inter)
    s20 = write_supp_unadjusted(paths, effects, holm)
    figs = [fig1_specificity(paths), fig_dissociation(paths, holm),
            fig3_paths(paths, effects, holm), fig2_moderation(inter)]

    checks = qc_checks(est, info, paths, effects, holm, props)
    review = checks[checks.status == 'REVIEW']

    print(f'models {len(info)}  parameters {len(est):,}  effects {len(eff):,}')
    for f in [q, *mains, s, s20]:
        print(f'wrote {f.relative_to(BASE)}')
    for f in figs:
        d = 'figure/supplementary' if f.startswith('SuppFig') else 'figure/main'
        print(f'wrote {d}/{f}.pdf + .png  and figure/source_data/Source_Data_{f}.xlsx')
    print(f'\nQC: {len(checks) - len(review)}/{len(checks)} pass')
    for _, r in review.iterrows():
        print(f'  REVIEW  {r.check}: {r.detail}')
    return dict(qc_workbook=q, main_tables=mains, supp_tables=s,
                figures=figs, checks=checks, n_models=len(info))


def build_all():
    """Every Mplus-derived output in one call; notebook 10 calls this."""
    return main()


def _cli():
    r = main()
    review = r['checks'][r['checks'].status == 'REVIEW']
    return 1 if len(review) else 0


if __name__ == '__main__':
    raise SystemExit(_cli())
