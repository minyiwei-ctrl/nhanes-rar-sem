"""The analysis population and its age cells, defined once.

ADULT_MIN_AGE applies to the association analyses only (stages 5_6 to 18 and
the Mplus models). It does not change the Klemera-Doubal calibration sample
in 5_5_compute_kdm_ba.R, which is fitted on all adults with the complete
marker panel, nor the data file handed to Mplus, which keeps every adult so
that the survey design is intact; the Mplus models declare the population
through SUBPOPULATION (ADULT20 EQ 1) rather than by deleting records.

Why 20: the five-level adult educational-attainment variable used for
adjustment (DMDEDUC2) is recorded from age 20; 18- and 19-year-olds carry a
different variable (DMDEDUC3) and were never in the analytic samples.
"""

ADULT_MIN_AGE = 20     # association analyses: adults aged 20 and over
OLD_MIN_AGE = 60       # the older cell; also the age from which NHANES tests cognition

# Age-cell keys used throughout the code; nature_palette.AGE_LABEL maps them
# to display text.
YOUNG = f'{ADULT_MIN_AGE}-59'     # '20-59'
OLD = f'{OLD_MIN_AGE}+'           # '60+'
POOLED = f'{ADULT_MIN_AGE}+'      # '20+', age-unstratified

# (lower bound inclusive, upper bound exclusive or None)
CELL_BOUNDS = {YOUNG: (ADULT_MIN_AGE, OLD_MIN_AGE),
               OLD: (OLD_MIN_AGE, None),
               POOLED: (ADULT_MIN_AGE, None)}


def in_cell(age, cell):
    """Boolean mask: ages (array-like, years) inside `cell`."""
    import numpy as np
    lo, hi = CELL_BOUNDS[cell]
    age = np.asarray(age, dtype=float)
    m = age >= lo
    if hi is not None:
        m &= age < hi
    return m
