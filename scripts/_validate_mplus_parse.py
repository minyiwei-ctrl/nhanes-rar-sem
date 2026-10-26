"""Regression tests for the Mplus output parser and the effect/interaction
reporting logic, on fixtures that reproduce the Mplus 9 output layout.

    python _validate_mplus_parse.py

Exit code 1 on any failure. Written after the October 2026 finding that the
95% interval of the specific indirect effects had been read from the wrong
columns (lower 5% and upper 0.5%); every interval parsed here is checked
against the 2.5% / 97.5% columns of the fixture, for a positive, a negative
and a near-zero effect, in the standardised and the unstandardised block.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mplus_parse import parse_effects, parse_estimates  # noqa: E402

_OK = True


def ok(name, cond, note=''):
    global _OK
    _OK &= bool(cond)
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f'  ({note})' if note else ''))


# One fixture: the effects blocks of a two-mediator model, with distinct
# numbers in every CI column so that a wrong column cannot pass by
# coincidence. Columns: Lower .5%  Lower 2.5%  Lower 5%  Estimate  Upper 5%
# Upper 2.5%  Upper .5%.
def effects_block(sol_header, tot, ti, ind1, ind2, dirct):
    def row(name, e, se, z, p):
        return f'  {name:<18s}{e:9.3f}{se:11.3f}{z:11.3f}{p:11.3f}\n'
    def ci(name, e, w):
        cols = [e - 2.58 * w, e - 1.96 * w, e - 1.65 * w, e, e + 1.65 * w, e + 1.96 * w, e + 2.58 * w]
        return f'  {name:<16s}' + ''.join(f'{c:12.3f}' for c in cols) + '\n'
    est = (f'{sol_header}\n\n                                                    Two-Tailed\n'
           f'                    Estimate       S.E.  Est./S.E.    P-Value\n\n'
           f'Effects from IV to PHQ9\n\n'
           + row('Total', *tot) + row('Total indirect', *ti) + '\n'
           + '  Specific indirect 1\n    PHQ9\n    BA_ADV\n' + row('  IV', *ind1) + '\n'
           + '  Specific indirect 2\n    PHQ9\n    SII_LOG\n' + row('  IV', *ind2) + '\n'
           + '  Direct\n    PHQ9\n' + row('  IV', *dirct) + '\n\n'
           + 'Effects from IV to PHQ9\n\n' + row('Sum of indirect', *ti) + '\n'
           + '  Specific indirect 1\n    PHQ9\n    BA_ADV\n' + row('  IV', *ind1) + '\n'
           + '  Specific indirect 2\n    PHQ9\n    SII_LOG\n' + row('  IV', *ind2) + '\n')
    w = 0.01
    cis = ((sol_header + '\n\n' if sol_header else '')
           + '                  Lower .5%  Lower 2.5%    Lower 5%    Estimate    Upper 5%  Upper 2.5%   Upper .5%\n\n'
           'Effects from IV to PHQ9\n\n'
           + ci('Total', tot[0], w) + ci('Total indirect', ti[0], w) + '\n'
           + '  Specific indirect 1\n    PHQ9\n    BA_ADV\n' + ci('  IV', ind1[0], w) + '\n'
           + '  Specific indirect 2\n    PHQ9\n    SII_LOG\n' + ci('  IV', ind2[0], w) + '\n'
           + '  Direct\n    PHQ9\n' + ci('  IV', dirct[0], w) + '\n\n'
           + 'Effects from IV to PHQ9\n\n' + ci('Sum of indirect', ti[0], w) + '\n'
           + '  Specific indirect 1\n    PHQ9\n    BA_ADV\n' + ci('  IV', ind1[0], w) + '\n'
           + '  Specific indirect 2\n    PHQ9\n    SII_LOG\n' + ci('  IV', ind2[0], w) + '\n')
    return est, cis


def fixture():
    # (estimate, se, z, p): positive total, positive indirect via BA_ADV,
    # negative indirect via SII_LOG, near-zero direct.
    u = effects_block('', (0.120, 0.030, 4.0, 0.000), (0.040, 0.010, 4.0, 0.000),
                      (0.045, 0.010, 4.5, 0.000), (-0.005, 0.004, -1.25, 0.211),
                      (0.080, 0.028, 2.857, 0.004))
    s = effects_block('STDYX Standardization', (0.110, 0.028, 3.9, 0.000), (0.036, 0.009, 4.0, 0.000),
                      (0.041, 0.009, 4.6, 0.000), (-0.004, 0.003, -1.3, 0.194),
                      (0.001, 0.025, 0.04, 0.968))
    text = ('\n\nTOTAL, TOTAL INDIRECT, SPECIFIC INDIRECT, AND DIRECT EFFECTS\n\n' + u[0]
            + '\n\nSTANDARDIZED TOTAL, TOTAL INDIRECT, SPECIFIC INDIRECT, AND DIRECT EFFECTS\n\n\n' + s[0]
            + '\n\nCONFIDENCE INTERVALS OF TOTAL, TOTAL INDIRECT, SPECIFIC INDIRECT, AND DIRECT EFFECTS\n\n' + u[1]
            + '\n\nCONFIDENCE INTERVALS OF STANDARDIZED TOTAL, TOTAL INDIRECT, SPECIFIC INDIRECT, AND DIRECT EFFECTS\n\n\n' + s[1]
            + '\n\nMODEL COMMAND WITH FINAL ESTIMATES USED AS STARTING VALUES\n')
    return text


def main():
    print('=' * 80)
    print('T1  effect estimates and 95% intervals are read from the right columns')
    print('=' * 80)
    rows = pd.DataFrame(parse_effects(fixture(), 'fixture'))
    want = {  # (solution, effect, via): (estimate, lo, hi) with lo/hi = est -/+ 1.96 * 0.01
        ('unstandardized', 'total', None): 0.120, ('unstandardized', 'direct', None): 0.080,
        ('unstandardized', 'indirect', 'BA_ADV'): 0.045, ('unstandardized', 'indirect', 'SII_LOG'): -0.005,
        ('STDYX', 'total', None): 0.110, ('STDYX', 'direct', None): 0.001,
        ('STDYX', 'indirect', 'BA_ADV'): 0.041, ('STDYX', 'indirect', 'SII_LOG'): -0.004,
    }
    for (sol, eff, via), e in want.items():
        r = rows[(rows.solution == sol) & (rows.effect == eff) & ((rows.via == via) if via else rows.via.isna())]
        ok(f'{sol:14s} {eff:8s} {via or "":8s} estimate', len(r) == 1 and abs(r.estimate.iloc[0] - e) < 1e-9)
        if len(r) == 1:
            ok(f'{sol:14s} {eff:8s} {via or "":8s} 95% CI = estimate -/+ 1.96 SE (columns 2 and 6)',
               abs(r.ci_lo.iloc[0] - round(e - 1.96 * 0.01, 3)) < 1e-9
               and abs(r.ci_hi.iloc[0] - round(e + 1.96 * 0.01, 3)) < 1e-9,
               f'got {r.ci_lo.iloc[0]:.3f}, {r.ci_hi.iloc[0]:.3f}')
    ok('the three columns that were misread in 2026 are NOT what is reported',
       not any(abs(rows[(rows.effect == 'indirect')].ci_lo - (rows[(rows.effect == 'indirect')].estimate - 1.65 * 0.01).round(3)).abs() < 1e-9))

    print()
    print('=' * 80)
    print('T2  interaction scale: simple slopes differ by exactly the interaction coefficient')
    print('=' * 80)
    # Fixture of the unstandardized MODEL RESULTS for an age-moderation model.
    mr = ('\nMODEL RESULTS\n\n                                                    Two-Tailed\n'
          '                    Estimate       S.E.  Est./S.E.    P-Value\n\n'
          ' BA_ADV   ON\n    RA                -0.112      0.016     -6.876      0.000\n'
          '    RA_AGE            -0.054      0.014     -3.898      0.000\n'
          '    AGE               -0.034      0.008     -4.136      0.000\n\n'
          ' Residual Variances\n    BA_ADV             0.876      0.030     29.200      0.000\n\n'
          'New/Additional Parameters\n    SLOPE_LO          -0.058      0.014     -4.132      0.000\n'
          '    SLOPE_MI          -0.112      0.016     -6.876      0.000\n'
          '    SLOPE_HI          -0.166      0.027     -6.210      0.000\n\n\n'
          'STANDARDIZED MODEL RESULTS\n\n\nSTDYX Standardization\n\n'
          '                                                    Two-Tailed\n'
          '                    Estimate       S.E.  Est./S.E.    P-Value\n\n'
          ' BA_ADV   ON\n    RA                -0.127      0.018     -7.018      0.000\n'
          '    RA_AGE            -0.058      0.015     -3.934      0.000\n'
          '    AGE               -0.037      0.009     -3.948      0.000\n\n'
          'R-SQUARE\n')
    est = pd.DataFrame(parse_estimates(mr, 'x_fixture'))
    u = est[est.solution == 'unstandardized']
    get = lambda p: float(u[u.parameter == p].estimate.iloc[0])
    ok('unstandardized RA_AGE equals SLOPE_HI - SLOPE_MI (to printed precision)',
       abs((get('SLOPE_HI') - get('SLOPE_MI')) - get('RA_AGE')) < 1.5e-3,
       f'{get("SLOPE_HI") - get("SLOPE_MI"):.3f} vs {get("RA_AGE"):.3f}')
    sx = est[(est.solution == 'STDYX') & (est.parameter == 'RA_AGE')]
    ok('STDYX RA_AGE is not the slope difference (why Table 3 uses the unstandardized solution)',
       len(sx) == 1 and abs(float(sx.estimate.iloc[0]) - (get('SLOPE_HI') - get('SLOPE_MI'))) > 2e-3)

    print()
    print('=' * 80)
    print('RESULT: ' + ('all checks passed' if _OK else 'FAILURES above'))
    print('=' * 80)
    return 0 if _OK else 1


if __name__ == '__main__':
    raise SystemExit(main())
