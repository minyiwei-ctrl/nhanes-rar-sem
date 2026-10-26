"""Assemble the title and caption of every display item and write CAPTIONS.md.

    python captions.py            # print
    python captions.py --write    # write CAPTIONS.md

Titles come from the TITLES registry below. Caption bodies are read from the
'legend' sheet of each figure's Source_Data workbook and the 'Notes' sheet of
each table. Checks that every display item on disk has a title, that every
title refers to an item on disk, and that no title contains claim wording.
"""
import re
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
FIG, FIG_SUPP = BASE / 'figure' / 'main', BASE / 'figure' / 'supplementary'
SRC = BASE / 'figure' / 'source_data'
MAIN, SUPP = BASE / 'result' / 'main', BASE / 'result' / 'supplementary'

# stem -> (number as it appears in the manuscript, title)
# Titles are descriptive and in sentence case (npj Aging style, e.g. Shim et
# al. 2026): they name what the display shows and the quantities it relates,
# with no direction, comparison or verb that asserts a relationship.
# check_titles() enforces this.
TITLES = {
    # main figures
    'Fig1_Study_Overview': (
        'Fig. 1',
        'Study framework and sample selection'),
    'Fig2_MediatorContrast': (
        'Fig. 2',
        'Rest-activity rhythm associations with the two candidate biological '
        'measures and the indirect associations through them'),
    'Fig3_PathDecomposition': (
        'Fig. 3',
        'Path decomposition of the associations with depressive symptoms and '
        'cognitive function for each rest-activity rhythm metric'),
    'Fig4_Age_Moderation_SimpleSlopes': (
        'Fig. 4',
        'Associations of rest-activity rhythm metrics with KDM-BA advancement '
        'at selected ages'),

    # main tables
    'Table1_Sample_Characteristics': (
        'Table 1',
        'Sample characteristics of the primary analytic sample'),
    'Table2_SEM_Mediation': (
        'Table 2',
        'Rest-activity rhythm associations with biological-age advancement, '
        'systemic inflammation, depressive symptoms and cognitive function'),
    'Table3_Age_Moderation': (
        'Table 3',
        'Age moderation of rest-activity rhythm associations with '
        'biological-age advancement'),

    # supplementary figures
    'SuppFigS1_Age_Moderation_WLS_Forest': (
        'Supplementary Fig. S1',
        'Rest-activity rhythm associations with biological-age advancement within four age groups'),
    'SuppFigS2_RAR_Dimensions_Forest': (
        'Supplementary Fig. S2',
        'Total and direct associations of each rest-activity rhythm metric with depressive symptoms and cognitive function'),
    'SuppFigS3_GAM_Partial_Effects': (
        'Supplementary Fig. S3',
        'Linearity of each rest-activity rhythm association with depressive symptoms and cognitive function'),
    'SuppFigS4_Exposure_Mediator_Distributions': (
        'Supplementary Fig. S4',
        'Distributions of rest-activity rhythm metrics, biological-age advancement and log SII, by age group'),
    'SuppFigS5_RhythmToBiologicalAge_VolumeAdjustment': (
        'Supplementary Fig. S5',
        'Rest-activity rhythm associations with biological-age advancement in the three structural models, core against volume-adjusted covariates'),

    'SuppFigS6_Variance_Decomposition': (
        'Supplementary Fig. S6',
        'Incremental variance explained by each predictor in the equations for biological-age advancement and log SII'),

    # supplementary tables
    'SuppTableS1_Sample_Cascade': (
        'Supplementary Table S1',
        'Sample selection cascade'),
    'SuppTableS2_Missingness': (
        'Supplementary Table S2',
        'Item-level missingness among adults'),
    'Supp_Tables': (
        'Supplementary Tables S3-S7',
        'All estimated models: structural paths, effect decompositions, age '
        'moderation, model fit, and rhythm-metric selection'),
    'SuppTableS8_Age_Moderation_WLS': (
        'Supplementary Table S8',
        'Age moderation of rest-activity rhythm associations with '
        'biological-age advancement, depressive symptoms and cognitive '
        'function, by weighted least squares'),
    # S9 is the pooled, age-unstratified dimension check; S15 is the
    # age-stratified mirror of the primary models with the volume-adjusted
    # specification added.
    'SuppTableS9_RAR_Dimension_Specificity': (
        'Supplementary Table S9',
        'Rest-activity rhythm associations with depressive symptoms and '
        'cognitive function across the three rhythm dimensions, total and '
        'direct, by weighted least squares in the pooled adult sample'),
    'SuppTableS10_GAM_Linearity': (
        'Supplementary Table S10',
        'Tests of linearity for rest-activity rhythm associations with '
        'depressive symptoms, cognitive function and the two biological '
        'measures, and linearity of the relative-amplitude associations on '
        'the quintile scale'),
    'SuppTableS11_KDM_Outlier_Sensitivity': (
        'Supplementary Table S11',
        'Rest-activity rhythm associations before and after trimming the '
        'tails of biological age'),
    'SuppTableS12_Sample_Accounting': (
        'Supplementary Table S12',
        'Sample accounting: variable roles, covariate attrition, and every '
        'analysis set'),
    'SuppTableS13_Distribution_Summary': (
        'Supplementary Table S13',
        'Distributional summary of every continuous characteristic'),
    'SuppTableS14_APaths_WLS': (
        'Supplementary Table S14',
        'Rest-activity rhythm associations with biological-age advancement '
        'and systemic inflammation, by weighted least squares'),
    'SuppTableS15_TotalDirect_WLS': (
        'Supplementary Table S15',
        'Rest-activity rhythm associations with depressive symptoms and '
        'cognitive function, total and direct, by weighted least squares '
        'within each age group and covariate set'),
    # The variable dictionary is VARIABLES.md, not a supplementary table.
    'SuppTableS16_KDM_Component_Specificity': (
        'Supplementary Table S16',
        'Rest-activity rhythm associations with each biological-age panel '
        'marker and each immune-inflammation index component, and the '
        'decomposition of the index into those components'),
    # S17-S19 are the data-screening tables (script 5_6), computed before any
    # model is fitted.
    'SuppTableS17_Model_Correlations': (
        'Supplementary Table S17',
        'Survey-weighted pairwise correlations among the model variables'),
    'SuppTableS18_VIF': (
        'Supplementary Table S18',
        'Variance inflation factors for the predictor set of each primary '
        'outcome equation'),
    'SuppTableS19_Distributions_Missingness': (
        'Supplementary Table S19',
        'Distributions, extreme values and missingness of the model '
        'variables'),
    # S20: STROBE item 16a, written by mplus_report from the m_*_crude models.
    'SuppTableS20_Unadjusted_vs_Adjusted': (
        'Supplementary Table S20',
        'Unadjusted and covariate-adjusted estimates from the primary '
        'structural models'),
}

# S21 is written by p1_report.py after the P1 Mplus runs; registering it only
# once it exists keeps the checkers green in between.
if (SUPP / 'SuppTableS21_P1_FunctionalForm.xlsx').exists():
    TITLES['SuppTableS21_P1_FunctionalForm'] = (
        'Supplementary Table S21',
        'Design-corrected functional-form, age-interaction and education-coding '
        'analyses of the rhythm-to-biological-age equation')
# S22 and S23 are written by freeze_sensitivity_report.py after the cycle_audit,
# cycle_contrasts and selection_audit Mplus runs (stage 19), on the same terms.
if (SUPP / 'SuppTableS22_CycleSensitivity.xlsx').exists():
    TITLES['SuppTableS22_CycleSensitivity'] = (
        'Supplementary Table S22',
        'Survey-cycle sensitivity analyses of the structural models: '
        'cycle-adjusted estimates, functional-form tests and pooled '
        'between-cycle contrasts')
if (SUPP / 'SuppTableS23_CognitiveSelection.xlsx').exists():
    TITLES['SuppTableS23_CognitiveSelection'] = (
        'Supplementary Table S23',
        'Availability of the cognitive test scores among adults aged 60 '
        'years or older and complete-case refits of the cognition models')

# Words that make a title assert a finding rather than name a display.
# Matching is on whole words, so terms inside variable names ("relative
# amplitude", "biological-age advancement") are not caught.
CLAIM_WORDS = {
    # verbs that assert a relationship
    'tracks', 'track', 'accompany', 'accompanies', 'predicts', 'predict',
    'drives', 'drive', 'causes', 'cause', 'leads', 'lead', 'reflects',
    'reflect', 'explains', 'explain', 'mediates', 'determines', 'reveals',
    'demonstrates', 'shows', 'confirms', 'supports', 'dissociate',
    'dissociates', 'strengthens', 'strengthen', 'reverses', 'reverse',
    # comparatives and directional adjectives
    'greater', 'weaker', 'stronger', 'higher', 'lower', 'worse', 'better',
    'increased', 'decreased', 'reduced', 'elevated', 'more', 'less',
    'poorer', 'improved', 'accelerated',
    # rhetorical
    'but', 'novel', 'first', 'robust', 'strong',
}


def check_titles():
    """Flag any title that states a finding instead of naming a display."""
    bad = []
    for stem, (number, title) in TITLES.items():
        hits = sorted({w for w in re.findall(r"[a-z][a-z\-']+", title.lower())
                       if w in CLAIM_WORDS})
        if hits:
            bad.append(f'{number} title contains claim wording {hits}: "{title}"')
    return bad


ORDER = ['Fig. 1', 'Fig. 2', 'Fig. 3', 'Fig. 4',
         'Table 1', 'Table 2', 'Table 3']


def _sort_key(number):
    if number in ORDER:
        return (0, ORDER.index(number))
    m = re.search(r'S(\d+)', number)
    kind = 1 if 'Fig' in number else 2
    return (kind, int(m.group(1)) if m else 99)


def collect():
    """One record per display item: number, title, body, source file."""
    items = []
    seen = set()

    for d in (FIG, FIG_SUPP):
        for f in sorted(d.glob('*.pdf')):
            stem = f.stem
            seen.add(stem)
            body = []
            sd = SRC / f'Source_Data_{stem}.xlsx'
            if sd.exists():
                try:
                    lg = pd.read_excel(sd, 'legend').iloc[:, 0].astype(str).tolist()
                    # the first line is the legend's own title; the registry
                    # supplies the title, so drop it from the body
                    body = [x for x in lg[1:] if x and x != 'nan']
                except Exception as e:                       # pragma: no cover
                    body = [f'(legend unreadable: {e})']
            items.append(dict(stem=stem, kind='figure', body=body,
                              source=str(f.relative_to(BASE))))

    for d, kind in ((MAIN, 'main table'), (SUPP, 'supp table')):
        for f in sorted(d.glob('*.xlsx')):
            if f.name.startswith('~$'):
                continue
            stem = f.stem
            seen.add(stem)
            try:
                body = [x for x in pd.read_excel(f, 'Notes').iloc[:, 0]
                        .astype(str).tolist() if x and x != 'nan']
            except Exception as e:                           # pragma: no cover
                body = [f'(Notes unreadable: {e})']
            items.append(dict(stem=stem, kind=kind, body=body,
                              source=str(f.relative_to(BASE))))

    problems = check_titles()
    for it in items:
        t = TITLES.get(it['stem'])
        if not t:
            problems.append(f'{it["stem"]} has no title in the registry')
            it['number'], it['title'] = '', ''
        else:
            it['number'], it['title'] = t
    for stem in TITLES:
        if stem not in seen:
            problems.append(f'title registered for {stem}, which is not on disk')

    items = [i for i in items if i['number']]
    items.sort(key=lambda i: _sort_key(i['number']))
    return items, problems


def main():
    items, problems = collect()
    for it in items:
        print(f'\n{it["number"]} | {it["title"]}')
        print(f'   [{it["source"]}]')
        for line in it['body']:
            print(f'   {line}')
    print(f'\n{len(items)} display items with titles and captions')
    if problems:
        print('\nPROBLEMS')
        for p in problems:
            print(' ', p)
    else:
        print('every display item has a title; every title has an item')

    if '--write' in sys.argv:
        out = BASE / 'CAPTIONS.md'
        lines = ['# Titles and captions', '',
                 'Generated by `scripts/captions.py`. Titles live in that '
                 'file; caption bodies are read from each item\'s own legend '
                 'or Notes sheet, so they cannot drift from the item they '
                 'describe. Rerun after any change to a figure or table.', '']
        last = None
        for it in items:
            group = ('Main figures' if it['number'].startswith('Fig.')
                     else 'Main tables' if it['number'].startswith('Table')
                     else 'Supplementary figures' if 'Fig' in it['number']
                     else 'Supplementary tables')
            if group != last:
                lines += [f'## {group}', '']
                last = group
            lines += [f'**{it["number"]} | {it["title"]}.**', '']
            lines += [f'{b}' if b.endswith('.') else f'{b}.' for b in it['body']]
            lines += ['', f'*Source: `{it["source"]}`*', '']
        out.write_text('\n'.join(lines) + '\n')
        print(f'\nwrote {out.relative_to(BASE)}')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
