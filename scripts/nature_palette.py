"""
Colour palette and display conventions shared by the manuscript figures and tables.

Defines one colour per rest-activity rhythm metric (EXP_COL) and the metric
display order (EXP_ORDER), the age-stratum labels (AGE_LABEL, age_label) and
the number format for estimates (fmt_est, fmt_ci). Colours sit in two tiers:
an ordered pink-purple-blue gradient for exposure levels and age strata, and
separate hues for each mediator pathway and outcome.
"""
import logging as _logging


def quiet_fonttools():
    """Silence fontTools' informational log lines during PDF export.

    With pdf.fonttype = 42 matplotlib embeds TrueType glyphs (editable text);
    fontTools then logs one line per macOS AAT table (Zapf, feat, morx) it
    drops from the subset. Called at import.
    """
    for name in ('fontTools', 'fontTools.subset', 'fontTools.ttLib'):
        _logging.getLogger(name).setLevel(_logging.ERROR)


quiet_fonttools()

# Tier 1: IV / age gradient
IV_LOW  = '#ff7c9c'   # pink — Low IV / youngest stratum
IV_MEAN = '#9575CD'   # purple — Mean IV / young-mid
IV_HIGH = '#63baf8'   # sky blue — High IV / mid-old
IV_DEEP = '#1565C0'   # deep blue — oldest stratum (4-level only)

IV_GRADIENT_3 = [IV_LOW, IV_MEAN, IV_HIGH]
IV_GRADIENT_4 = [IV_LOW, IV_MEAN, IV_HIGH, IV_DEEP]

# Rhythm-metric identity colours: one colour per metric wherever a metric is a
# hue, taken from the Tier 1 trio so the palette stays in one family. Purple
# (the darkest) goes to IV, pink to RA, sky blue to IS. Metric hues and
# mediator hues never share a figure. Every script imports this dict.
EXP_COL = {'RA': IV_LOW, 'IS': IV_HIGH, 'IV': IV_MEAN}

# Display order for the three metrics wherever they appear as rows, dodge
# positions or legend entries: amplitude, stability, fragmentation.
EXP_ORDER = ['RA', 'IS', 'IV']

# Tier 2: mediator pathways. Brick sits 162 RGB units from RA's pink (#ff7c9c),
# and its luminance (0.10, against 0.38 for pink and 0.30 for teal) keeps
# Figure 2 legible in greyscale.
KDM_BA_COLOR = '#9C3A2E'   # brick — biological-aging mediator
SII_COLOR    = '#26A69A'   # teal — inflammation mediator
MVPA_COLOR   = '#FFA726'   # amber — behavioural mediator (objective MVPA)

# Tier 2: outcomes
PHQ9_COLOR = '#C2185B'   # magenta — PHQ-9 depression
COG_COLOR  = '#1565C0'   # deep blue — cognition composite

# Divergent scale for signed values (e.g. KDM-BA advancement)
DIV_NEG = '#1565C0'   # blue — biologically younger
DIV_MID = '#E0E0E0'   # grey — at expected age
DIV_POS = '#D32F2F'   # red — biologically older

# Neutral / annotation
BLACK = '#000000'
GREY  = '#757575'

# Wong (2011) colour-blind safe palette, fall-back for up to 8 categories
WONG = ['#000000', '#E69F00', '#56B4E9', '#009E73',
        '#F0E442', '#0072B2', '#D55E00', '#CC79A7']


# Display conventions shared by every table and figure. The age-cell keys
# come from population.py ('20-59', '60+', '20+'); only the printed label is
# defined here.
from population import YOUNG, OLD, POOLED, ADULT_MIN_AGE, OLD_MIN_AGE

AGE_LABEL = {YOUNG: f'{ADULT_MIN_AGE}–59', OLD: f'≥{OLD_MIN_AGE}', POOLED: f'≥{ADULT_MIN_AGE}'}


def age_label(cell, prefix=''):
    """'60+' -> '>=60' (typeset with a real >= glyph)."""
    lab = AGE_LABEL.get(cell, cell)
    return f'{prefix}{lab}' if prefix else lab


def fmt_est(v, dp=3):
    """Format v to dp decimals: no plus sign, and a value that rounds to zero is printed unsigned (0.000, not -0.000)."""
    if v is None or v != v:          # None or NaN, without importing numpy
        return ''
    s = f'{v:.{dp}f}'
    if s.startswith('-') and float(s) == 0:
        s = s[1:]
    return s


def fmt_ci(est, lo=None, hi=None, dp=3):
    """Point estimate with its interval, under the fmt_est sign convention."""
    e = fmt_est(est, dp)
    if not e:
        return ''
    l, h = fmt_est(lo, dp), fmt_est(hi, dp)
    return f'{e} ({l}, {h})' if l and h else e
