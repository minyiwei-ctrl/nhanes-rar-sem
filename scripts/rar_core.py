"""
Accelerometer ingest and rest-activity rhythm numerics for NHANES 2011-2014.

Reads chunks of minute-level PAXMIN records (SEQN, PAXDAYM, PAXSSNMP, PAXMTSM,
PAXQFM, PAXPREDM) and returns per person-day summaries, clock-aligned activity
profiles and the metrics IS, IV, M10, L5 and RA. Writes nothing. Called from
5_accelerometer_RAR.ipynb; checked against analytic answers in
_validate_rar_core.py.

A minute is valid when PAXQFM == 0, PAXPREDM in {1, 2} (wake wear or sleep
wear) and PAXMTSM >= 0 (-0.01 means the MIMS value could not be computed).
Invalid minutes are NaN, never zero.
Minute of day = (PAXSSNMP / 4800 - session minute at which PAXDAYM becomes 2)
mod 1440, where 4800 = 80 Hz x 60 s and every day after the first starts at
00:00.
A valid day has >= 600 valid minutes; a valid participant has >= 3 valid days.
Module A values (Wear_Time, obj_mvpa_min, obj_sed_min) are means over valid
days. Sedentary: MIMS < 1.05. MVPA: MIMS >= 19.614, the Montoye et al. (2020)
non-dominant-wrist activity-count cut-point (AC = 3940) mapped to MIMS by
Karas et al. (2022).
IS = V_between / (V_between + V_within) on the hourly grid; on a balanced grid
this equals Var(composite profile) / Var(all observations), and it stays in
[0, 1] under incomplete clock coverage.
IV is computed on the chronological hourly series of the whole recording
(Witting et al. 1990; Van Someren et al. 1999): the mean squared difference
between hours that are adjacent in time and both observed, divided by the
variance of the observed hours. No difference is taken across a missing hour
or a missing day, and the series does not wrap. On a complete series this is
N * sum((x_t - x_{t-1})^2) / ((N-1) * sum((x_t - xbar)^2)). The same ratio
on the composite 24-hour profile (the 2026-08 analytic file) is kept as
IV_profile_legacy for audit only.
M10 and L5 are the maximum 600-minute and minimum 300-minute rolling means of
the composite minute profile, complete windows only, wrapping past midnight.
RA = (M10 - L5) / (M10 + L5).
"""
import warnings
from contextlib import contextmanager

import numpy as np
import pandas as pd


@contextmanager
def _quiet_nan():
    """Silence numpy all-NaN-slice warnings; a never-observed clock minute is NaN by design."""
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', r'.*Mean of empty slice.*', RuntimeWarning)
        warnings.filterwarnings('ignore', r'.*Degrees of freedom <= 0.*', RuntimeWarning)
        with np.errstate(invalid='ignore', divide='ignore'):
            yield

# Intensity thresholds, in MIMS per minute. The MVPA cut-point is the Montoye
# et al. (2020) non-dominant-wrist ActiGraph light/MVPA boundary (AC = 3940)
# mapped to MIMS by Karas et al. (2022, medRxiv 2022.03.16.22272518).
SED_THRESHOLD = 1.05      # MIMS below this is sedentary
MVPA_THRESHOLD = 19.614   # MIMS at or above this is MVPA
MVPA_SENSITIVITY = (10.558, 19.614, 45.1)   # reported as a supplementary check
SAMPLES_PER_MIN = 4800    # 80 Hz x 60 s
WEAR_CLASSES = (1, 2)     # PAXPREDM: 1 = wake wear, 2 = sleep wear
MIN_VALID_MIN_PER_DAY = 600
MIN_VALID_DAYS = 3
MIN_ADJACENT_PAIRS = 24   # IV is NaN with fewer adjacent valid hour pairs than one day holds

# Two artefacts of the XPT -> CSV conversion, handled by _denum() and ZERO_EPS:
#   1. Character variables (PAXDAYM, PAXPREDM) arrive as the literal string
#      b'1', which pd.to_numeric would turn into NaN.
#   2. Zeros in PAXQFM and PAXSSNMP arrive as the denormalised float
#      5.397605346934028e-79, so an exact comparison with 0 fails.
ZERO_EPS = 1e-5

MIN_COLS = ['SEQN', 'PAXDAYM', 'PAXSSNMP', 'PAXMTSM', 'PAXQFM', 'PAXPREDM']


# Minute-level cleaning

def _denum(s):
    """Numeric conversion that survives the b'...' byte-string repr in the CSVs."""
    if s.dtype == object:
        s = (s.astype(str)
              .str.strip()
              .str.replace(r"^b?['\"](.*)['\"]$", r'\1', regex=True))
    return pd.to_numeric(s, errors='coerce')


def clean_chunk(chunk):
    """Normalise one raw PAXMIN chunk and mark valid minutes.

    Returns: SEQN, day, session_min, mims (NaN where not usable), valid (bool).
    """
    chunk = chunk.copy()
    chunk.columns = [c.upper().replace("B'", "").replace("'", "").strip()
                     for c in chunk.columns]

    mims = _denum(chunk['PAXMTSM'])
    mims = mims.mask(mims < 0)                    # -0.01 sentinel -> NaN, not 0

    qf = _denum(chunk['PAXQFM'])
    pred = _denum(chunk['PAXPREDM'])

    valid = (qf.abs() < ZERO_EPS) & pred.isin(WEAR_CLASSES) & mims.notna()

    ssn = _denum(chunk['PAXSSNMP'])
    ssn = ssn.where(ssn.abs() > ZERO_EPS, 0.0)

    day = _denum(chunk['PAXDAYM'])
    seqn = _denum(chunk['SEQN'])
    if day.isna().all() or seqn.isna().all():
        raise ValueError(
            'PAXDAYM or SEQN parsed entirely to NaN. The XPT->CSV byte-string '
            "repr (b'1') is probably not being stripped; see _denum().")

    return pd.DataFrame({
        'SEQN': seqn.astype('int64'),
        'day': day.astype('int16'),
        'session_min': np.rint(ssn / SAMPLES_PER_MIN).astype('int32'),
        'mims': mims.astype('float32'),
        'valid': valid.to_numpy(),
    })


# Pass 1: per person-day summaries (Module A) and the inclusion sets

PEAK_N = 30   # minutes in the peak-30 intensity summary (Zheng et al. 2023)


def summarise_chunk_pass1(clean):
    """Per (SEQN, day): first session minute, and valid / MVPA / sedentary counts."""
    v = clean['valid'].to_numpy()
    m = clean['mims'].to_numpy()
    tmp = pd.DataFrame({
        'SEQN': clean['SEQN'], 'day': clean['day'],
        'first_session_min': clean['session_min'],
        'n_valid': v.astype('int32'),
        'n_mvpa': (v & (m >= MVPA_THRESHOLD)).astype('int32'),
        'n_sed': (v & (m < SED_THRESHOLD)).astype('int32'),
    })
    g = tmp.groupby(['SEQN', 'day'], sort=False)
    return g.agg(first_session_min=('first_session_min', 'min'),
                 n_valid=('n_valid', 'sum'),
                 n_mvpa=('n_mvpa', 'sum'),
                 n_sed=('n_sed', 'sum'))


def top_minutes_chunk(clean, n=PEAK_N):
    """The n largest valid MIMS values per (SEQN, day) in this chunk.

    Chunks split days; combine_top_minutes takes the top n of the union of the
    per-chunk candidates, which equals the global top n.
    """
    c = clean[clean['valid']]
    if c.empty:
        return pd.DataFrame(columns=['SEQN', 'day', 'mims'])
    return (c[['SEQN', 'day', 'mims']]
            .sort_values('mims', ascending=False)
            .groupby(['SEQN', 'day'], sort=False)
            .head(n))


def combine_top_minutes(parts, n=PEAK_N):
    """Peak-30-minute MIMS per (SEQN, day): the mean of the n highest
    non-consecutive valid minute values in the day (Zheng et al. 2023).
    Days with fewer than n valid minutes return NaN.
    """
    allp = pd.concat(parts, ignore_index=True)
    if allp.empty:
        return pd.Series(dtype='float64', name='peak30')
    top = (allp.sort_values('mims', ascending=False)
               .groupby(['SEQN', 'day'], sort=False)
               .head(n))
    g = top.groupby(['SEQN', 'day'])['mims']
    peak = g.mean().where(g.size() >= n)
    peak.name = 'peak30'
    return peak


def combine_pass1(parts):
    """Fold the per-chunk pass-1 summaries into one person-day table."""
    all_ = pd.concat(parts)
    return all_.groupby(level=['SEQN', 'day']).agg(
        first_session_min=('first_session_min', 'min'),
        n_valid=('n_valid', 'sum'),
        n_mvpa=('n_mvpa', 'sum'),
        n_sed=('n_sed', 'sum'))


def day2_anchors(person_day):
    """Session minute at which day 2 starts, per participant, with a consistency check.

    Every day d >= 2 starts at day2_start + (d - 2) * 1440, so each day gives
    an estimate of day2_start. Returns (anchor Series, participants whose
    estimates disagree).
    """
    d = person_day.reset_index()
    d = d[d['day'] >= 2].copy()
    d['anchor'] = d['first_session_min'] - (d['day'] - 2) * 1440
    g = d.groupby('SEQN')['anchor']
    anchor = g.median().astype('int64')
    spread = (g.max() - g.min())
    inconsistent = spread[spread != 0]
    return anchor, inconsistent


def module_a_person_level(person_day):
    """Apply the inclusion criteria and average Module A metrics over valid days.

    Returns (person_level_frame, valid_person_day_index).
    """
    valid_days = person_day[person_day['n_valid'] >= MIN_VALID_MIN_PER_DAY]
    counts = valid_days.groupby(level='SEQN').size()
    keep = counts[counts >= MIN_VALID_DAYS].index
    valid_days = valid_days.loc[valid_days.index.get_level_values('SEQN').isin(keep)]

    person = valid_days.groupby(level='SEQN').agg(
        obj_mvpa_min=('n_mvpa', 'mean'),
        obj_sed_min=('n_sed', 'mean'),
        Wear_Time=('n_valid', 'mean'),
        Valid_Days=('n_valid', 'size'))
    if 'peak30' in valid_days.columns:
        person['peak30_mims'] = valid_days.groupby(level='SEQN')['peak30'].mean()
    return person.reset_index(), valid_days.index


# Pass 2: clock-aligned profiles for the included person-days

class ProfileAccumulator:
    """Stream valid minutes into clock-aligned sums and counts (per person x 1440, per person-day x 24)."""

    def __init__(self, seqns, person_days):
        self.seqn_ix = {s: i for i, s in enumerate(np.sort(np.asarray(seqns)))}
        self.pd_ix = {k: i for i, k in enumerate(person_days)}
        n_p, n_pd = len(self.seqn_ix), len(self.pd_ix)
        self.prof_sum = np.zeros((n_p, 1440), dtype='float64')
        self.prof_cnt = np.zeros((n_p, 1440), dtype='int32')
        self.hour_sum = np.zeros((n_pd, 24), dtype='float64')
        self.hour_cnt = np.zeros((n_pd, 24), dtype='int32')

    def add(self, clean, anchors):
        c = clean[clean['valid']]
        if c.empty:
            return
        pdk = list(zip(c['SEQN'].to_numpy(), c['day'].to_numpy()))
        pdi = np.array([self.pd_ix.get(k, -1) for k in pdk], dtype='int64')
        m = pdi >= 0
        if not m.any():
            return
        c = c[m]
        pdi = pdi[m]
        seq = c['SEQN'].to_numpy()
        pi = np.array([self.seqn_ix[s] for s in seq], dtype='int64')
        anc = anchors.reindex(seq).to_numpy()
        mod = (c['session_min'].to_numpy() - anc) % 1440
        vals = c['mims'].to_numpy().astype('float64')

        np.add.at(self.prof_sum, (pi, mod), vals)
        np.add.at(self.prof_cnt, (pi, mod), 1)
        np.add.at(self.hour_sum, (pdi, mod // 60), vals)
        np.add.at(self.hour_cnt, (pdi, mod // 60), 1)

    def minute_profiles(self):
        """[n_person x 1440] composite profile; NaN where a clock minute was never observed."""
        with _quiet_nan():
            out = self.prof_sum / self.prof_cnt
        out[self.prof_cnt == 0] = np.nan
        return out

    def hourly_by_day(self):
        """[n_person_day x 24] hourly means; NaN where an hour was never observed."""
        with _quiet_nan():
            out = self.hour_sum / self.hour_cnt
        out[self.hour_cnt == 0] = np.nan
        return out


# Metrics

def hourly_bins(minute_profile):
    """Collapse [... x 1440] to [... x 24] by the NaN-ignoring mean of each 60-minute bin."""
    a = np.asarray(minute_profile, dtype=float)
    with _quiet_nan():
        return np.nanmean(a.reshape(*a.shape[:-1], 24, 60), axis=-1)


def interdaily_stability(hourly_by_day):
    """Interdaily stability on an hourly epoch (Witting et al. 1990).

    hourly_by_day : [n_days x 24], NaN allowed.
    IS = V_between / (V_between + V_within), where V_between is the variance
    over the 24 hours of the composite profile and V_within is the mean over
    hours of the across-day variance at that hour. On a balanced grid (every
    hour observed on the same number of days) this equals
    Var(profile) / Var(all observations); under incomplete clock coverage it
    stays in [0, 1] because both components are non-negative.
    IS = 1 when every day is identical; IS -> 1/n_days for independent days.
    """
    a = np.asarray(hourly_by_day, dtype=float)
    if a.ndim == 1:
        a = a[None, :]
    if a.size == 0 or np.all(np.isnan(a)):
        return np.nan
    with _quiet_nan():
        profile = np.nanmean(a, axis=0)                 # composite 24-h profile
        v_between = np.nanvar(profile)                  # across hours
        within = np.nanvar(a, axis=0)                   # across days, per hour
        # An hour observed on one day has across-day variance 0; only
        # never-observed hours are NaN.
        within = np.where(np.isnan(profile), np.nan, within)
        v_within = np.nanmean(within)
    if not np.isfinite(v_between) or not np.isfinite(v_within):
        return np.nan
    total = v_between + v_within
    if total <= 0:
        return np.nan
    return v_between / total


def intradaily_variability_series(hourly_by_day, days):
    """IV on the chronological hourly series of one participant.

    hourly_by_day : [n_days x 24] hourly means, NaN where an hour was not observed.
    days          : calendar day index of each row (PAXDAYM); rows are sorted by it.

    A squared difference enters the numerator only for two hours that are
    adjacent in time and both observed: hour h to h+1 within a day, and hour
    23 to hour 0 only when the next row is the next calendar day. Nothing is
    differenced across a missing hour, across a missing day, or from the end
    of the recording back to its start.

        IV = mean over adjacent valid pairs of (x_{t+1} - x_t)^2
             / population variance of the observed hours

    On a complete series this equals Witting's
    N * sum((x_t - x_{t-1})^2) / ((N-1) * sum((x_t - xbar)^2)). Range [0, 4]:
    2 for white noise, 4 for a perfectly alternating series.

    Returns (iv, n_hours, n_pairs). iv is NaN when fewer than
    MIN_ADJACENT_PAIRS valid pairs exist or the variance is zero; it is never 0
    by default.
    """
    a = np.asarray(hourly_by_day, dtype=float)
    if a.ndim == 1:
        a = a[None, :]
    days = np.asarray(days)
    order = np.argsort(days, kind='stable')
    a, days = a[order], days[order]
    x = a.reshape(-1)
    n_rows, per = a.shape
    valid = np.isfinite(x)
    n_hours = int(valid.sum())
    if len(x) < 2:
        return np.nan, n_hours, 0
    pair = valid[:-1] & valid[1:]
    # the last hour of row i is adjacent to the first hour of row i+1 only
    # when row i+1 is the next calendar day
    for i in range(n_rows - 1):
        if days[i + 1] != days[i] + 1:
            pair[(i + 1) * per - 1] = False
    n_pairs = int(pair.sum())
    if n_pairs < MIN_ADJACENT_PAIRS or n_hours < 2:
        return np.nan, n_hours, n_pairs
    xo = x[valid]
    var = np.mean((xo - xo.mean()) ** 2)
    if var <= 0:
        return np.nan, n_hours, n_pairs
    d = x[1:] - x[:-1]
    return float(np.mean(d[pair] ** 2) / var), n_hours, n_pairs


def intradaily_variability_profile(profile_24h):
    """The 2026-08 variant, kept for audit as IV_profile_legacy: the von
    Neumann ratio n * sum((x_i - x_{i-1})^2) / ((n-1) * sum((x_i - xbar)^2))
    on the length-24 composite profile, after dropping missing hours (so two
    hours either side of a gap are differenced) and without wrapping past
    midnight. Not the conventional IV; see intradaily_variability_series.
    """
    x = np.asarray(profile_24h, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n <= 1:
        return np.nan
    denom = (n - 1) * np.sum((x - x.mean()) ** 2)
    if denom <= 0:
        return np.nan
    return n * np.sum(np.diff(x) ** 2) / denom


def m10_l5_ra(profile_1440):
    """Most-active 10 h (M10) and least-active 5 h (L5) window means, and RA.

    Windows wrap past midnight and must be complete (no NaN), so a window that
    overlaps a data gap is not counted as a low-activity period.
    RA = (M10 - L5) / (M10 + L5); NaN, never 0, when M10 or L5 is undefined or
    M10 + L5 <= 0.
    """
    x = np.asarray(profile_1440, dtype=float)
    if np.all(np.isnan(x)):
        return np.nan, np.nan, np.nan
    s = pd.Series(np.concatenate([x, x]))

    def window(w, how):
        r = s.rolling(window=w, min_periods=w).mean()
        r = r.iloc[:1440 + w - 1]
        if r.notna().sum() == 0:
            return np.nan
        return r.max() if how == 'max' else r.min()

    M10 = window(600, 'max')
    L5 = window(300, 'min')
    if not np.isfinite(M10) or not np.isfinite(L5) or (M10 + L5) <= 0:
        return M10, L5, np.nan
    return M10, L5, (M10 - L5) / (M10 + L5)
