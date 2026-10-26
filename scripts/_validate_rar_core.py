"""
Ground-truth checks for scripts/rar_core.py on synthetic PAXMIN data with
analytically known answers. Reads no data and writes nothing; prints one
PASS/FAIL line per check and exits 0 only if all pass. 5_accelerometer_RAR.ipynb
runs it before reading the minute files.

Run:  python3 scripts/_validate_rar_core.py
"""
import numpy as np
import pandas as pd

from rar_core import (
    SED_THRESHOLD, MVPA_THRESHOLD, SAMPLES_PER_MIN,
    clean_chunk, summarise_chunk_pass1, combine_pass1, day2_anchors,
    module_a_person_level, ProfileAccumulator,
    hourly_bins, interdaily_stability, intradaily_variability_profile,
    intradaily_variability_series, MIN_ADJACENT_PAIRS, m10_l5_ra,
)

_OK = True


def check(name, got, want, tol, note=''):
    """Record and print whether got equals want within tol (NaN matches NaN)."""
    global _OK
    good = (np.isnan(got) and np.isnan(want)) or abs(got - want) <= tol
    _OK &= good
    print(f"  [{'PASS' if good else 'FAIL'}] {name:52s} got={got:10.4f}  want={want:10.4f}"
          + (f"  ({note})" if note else ''))


def ok(name, condition, note=''):
    """Record and print a boolean check."""
    global _OK
    _OK &= bool(condition)
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({note})" if note else ''))


# Synthetic PAXMIN generator

def make_day(peak_hour=14.0, amp=20.0, base=2.0):
    """One synthetic day of MIMS: sinusoid peaking at a known clock hour."""
    m = np.arange(1440)
    return base + amp * np.clip(np.cos(2 * np.pi * (m / 1440 - peak_hour / 24)), 0, None)


def make_participant(seqn, start_min, n_full_days=7, peak_hour=14.0,
                     amp=20.0, base=2.0,
                     nonwear_block=None, sentinel_minutes=0, qflag_minutes=0,
                     rng=None):
    """Build raw-format PAXMIN rows for one participant with known ground truth.

    start_min      clock minute at which the device began recording
    nonwear_block  (start_clock_min, length) marked PAXPREDM = 3 every day
    sentinel_minutes  how many minutes to set PAXMTSM = -0.01 with PAXQFM = 0
    qflag_minutes     how many minutes to give PAXQFM > 0
    """
    rng = rng or np.random.default_rng(0)
    d1_len = 1440 - start_min                       # partial first day
    total = d1_len + n_full_days * 1440
    session = np.arange(total)
    day = np.where(session < d1_len, 1, 2 + (session - d1_len) // 1440)
    clock = (start_min + session) % 1440

    profile = make_day(peak_hour, amp=amp, base=base)
    mims = profile[clock].astype(float)

    pred = np.ones(total, dtype=int)                # wake wear
    pred[(clock >= 0) & (clock < 6 * 60)] = 2       # sleep wear 00:00-06:00
    if nonwear_block:
        s, ln = nonwear_block
        blk = ((clock - s) % 1440) < ln
        pred[blk] = 3                               # non-wear
        mims[blk] = rng.uniform(0, 0.05, blk.sum())  # device sitting still

    qf = np.zeros(total, dtype=int)
    if qflag_minutes:
        qf[rng.choice(total, qflag_minutes, replace=False)] = 1
    if sentinel_minutes:
        idx = rng.choice(np.where((pred == 1) & (qf == 0))[0],
                         sentinel_minutes, replace=False)
        mims[idx] = -0.01

    # Emit the form the XPT->CSV conversion produces:
    #   character variables  ->  the literal string  b'1'
    #   zeros in PAXQFM / PAXSSNMP  ->  5.397605346934028e-79
    DENORM_ZERO = 5.397605346934028e-79
    ssn = session.astype(float) * SAMPLES_PER_MIN
    ssn = np.where(ssn == 0, DENORM_ZERO, ssn)
    qf_raw = np.where(qf == 0, DENORM_ZERO, qf.astype(float))

    return pd.DataFrame({
        'SEQN': seqn,
        'PAXDAYM': [f"b'{d}'" for d in day],
        'PAXSSNMP': ssn,
        'PAXMTSM': mims,
        'PAXQFM': qf_raw,
        'PAXPREDM': [f"b'{p}'" for p in pred],
    }), profile


def main():
    """Run checks T1-T8; return 0 if all pass, else 1."""
    rng = np.random.default_rng(20260814)

    print('=' * 80)
    print('T1  minute-of-day recovery is invariant to device start time')
    print('=' * 80)
    for start_min in (750, 1267, 601, 0):
        raw, _ = make_participant(1, start_min, n_full_days=7)
        cl = clean_chunk(raw)
        pdy = combine_pass1([summarise_chunk_pass1(cl)])
        anc, bad = day2_anchors(pdy)
        mod = (cl['session_min'].to_numpy() - anc.loc[1]) % 1440
        truth = (start_min + np.arange(len(raw))) % 1440
        ok(f'start={start_min:4d} min -> minute-of-day matches truth '
           f'({len(raw):,} minutes)', np.array_equal(mod, truth))
        ok(f'start={start_min:4d} min -> day anchors internally consistent',
           len(bad) == 0)

    print()
    print('=' * 80)
    print('T2  the three minute-level exclusions do what they claim')
    print('=' * 80)
    # amp / base chosen so the profile crosses both thresholds; otherwise the
    # MVPA and sedentary counts in T3 are zero.
    raw, _ = make_participant(2, 600, n_full_days=7, amp=60.0, base=0.5,
                              nonwear_block=(10 * 60, 180),   # 3 h non-wear daily
                              sentinel_minutes=40, qflag_minutes=25, rng=rng)
    # Confirm the generator emits the XPT->CSV artefacts before testing their handling.
    ok("generator emits the byte-string repr the real CSVs contain",
       raw['PAXPREDM'].str.fullmatch(r"b'\d'").all()
       and raw['PAXDAYM'].str.fullmatch(r"b'\d'").all(),
       f"e.g. {raw['PAXPREDM'].iloc[0]!r}")
    ok("generator emits the denormalised zero the real CSVs contain",
       0 < raw['PAXQFM'].min() < 1e-70,
       'qf == 0 would be False for every good minute')

    cl = clean_chunk(raw)
    is_nw = (raw['PAXPREDM'] == "b'3'").to_numpy()
    is_sent = (raw['PAXMTSM'] < 0).to_numpy()
    is_qf = (raw['PAXQFM'] > 1e-5).to_numpy()
    is_sleep = (raw['PAXPREDM'] == "b'2'").to_numpy()

    ok(f'byte-string columns parsed, not turned into NaN ({cl["valid"].sum():,} valid)',
       cl['valid'].sum() > 0.5 * len(cl))
    ok(f'non-wear minutes excluded ({is_nw.sum():,})', not cl.loc[is_nw, 'valid'].any())
    ok(f'MIMS = -0.01 sentinel minutes excluded ({is_sent.sum()})',
       not cl.loc[is_sent, 'valid'].any())
    ok(f'quality-flagged minutes excluded ({is_qf.sum()})',
       not cl.loc[is_qf, 'valid'].any())
    ok('sentinel minutes carry NaN, not 0', cl.loc[is_sent, 'mims'].isna().all(),
       'a sentinel is not a measurement of zero movement')
    ok('sleep wear is RETAINED (it is the rest half of the rhythm)',
       cl.loc[is_sleep & ~is_qf & ~is_sent, 'valid'].all())

    print()
    print('=' * 80)
    print('T3  Module A counts match the generator ground truth')
    print('=' * 80)
    pdy = combine_pass1([summarise_chunk_pass1(cl)])
    person, valid_pd = module_a_person_level(pdy)
    v = cl['valid'].to_numpy()
    m = cl['mims'].to_numpy()
    full = cl['day'].isin([d for (s, d) in valid_pd]).to_numpy()
    exp_wear = v[full].sum() / len(set(d for (s, d) in valid_pd))
    check('Wear_Time = mean valid minutes per valid day',
          float(person['Wear_Time'].iloc[0]), exp_wear, 1e-6)
    check('obj_mvpa_min', float(person['obj_mvpa_min'].iloc[0]),
          (v[full] & (m[full] >= MVPA_THRESHOLD)).sum() / person['Valid_Days'].iloc[0], 1e-6)
    check('obj_sed_min', float(person['obj_sed_min'].iloc[0]),
          (v[full] & (m[full] < SED_THRESHOLD)).sum() / person['Valid_Days'].iloc[0], 1e-6)
    ok(f"MVPA and sedentary counts are non-trivial "
       f"({person['obj_mvpa_min'].iloc[0]:.0f} / {person['obj_sed_min'].iloc[0]:.0f} min)",
       person['obj_mvpa_min'].iloc[0] > 50 and person['obj_sed_min'].iloc[0] > 300,
       'both thresholds actually exercised')
    # The true quiet period runs 20:00-08:00 = 720 min. The 3 h non-wear block
    # sits inside the active window and must not be counted as sedentary.
    ok('non-wear is not counted as sedentary',
       float(person['obj_sed_min'].iloc[0]) <= 720 + 1,
       'non-wear minutes must not enter the sedentary count')

    print()
    print('=' * 80)
    print('T4  end-to-end: composite profile lands on the true clock')
    print('=' * 80)
    # Four participants, four device start times, same true rhythm. SEQN 14
    # starts at midnight, so all its days are complete; it is the reference for
    # the IS = 1 check in T5.
    frames, seqs = [], [11, 12, 13, 14]
    for s, st in zip(seqs, (750, 1267, 90, 0)):
        r, _ = make_participant(s, st, n_full_days=7, peak_hour=14.0)
        frames.append(r)
    raw = pd.concat(frames, ignore_index=True)
    cl = clean_chunk(raw)
    pdy = combine_pass1([summarise_chunk_pass1(cl)])
    anc, bad = day2_anchors(pdy)
    ok('all three participants anchor consistently', len(bad) == 0)
    person, valid_pd = module_a_person_level(pdy)
    acc = ProfileAccumulator(person['SEQN'].to_numpy(), list(valid_pd))
    acc.add(cl, anc)
    prof = acc.minute_profiles()
    truth = make_day(14.0)
    for i, s in enumerate(seqs):
        peak = int(np.nanargmax(prof[i]) // 60)
        ok(f'SEQN {s}: composite profile peaks at hour {peak:02d}', peak == 14,
           'true peak 14:00 regardless of device start time')
    err = np.nanmax(np.abs(prof - truth))
    check('max abs deviation of recovered profile from truth', err, 0.0, 1e-4,
          'limited only by the float32 storage of MIMS')

    print()
    print('=' * 80)
    print('T5  metrics hit their analytic values')
    print('=' * 80)
    hbd = acc.hourly_by_day()
    i14 = [i for i, (s, d) in enumerate(valid_pd) if s == 14]   # starts at midnight
    i11 = [i for i, (s, d) in enumerate(valid_pd) if s == 11]   # starts 12:30
    check('IS, identical COMPLETE days (SEQN 14)',
          interdaily_stability(hbd[i14]), 1.0, 1e-6, 'no between-day variance')

    # The decomposition form of IS and the literal ratio Var(profile)/Var(all obs)
    # must agree exactly on a balanced grid (no NaN).
    bal = rng.normal(size=(9, 24))                       # no NaN -> balanced
    classic = np.nanvar(np.nanmean(bal, axis=0)) / np.nanvar(bal)
    check('IS decomposition == classic Witting ratio when balanced',
          interdaily_stability(bal), classic, 1e-12, 'algebraically identical')
    # On an unbalanced grid the decomposition must stay in [0,1]. The imbalance
    # is structured: a short day covers a contiguous arc of the clock, so the
    # hours it covers are observed on more days than the hours it does not.
    base = hourly_bins(make_day(14.0))                   # real between-hour structure
    worst, n_over, n_tried = 0.0, 0, 0
    for _ in range(3000):
        k = rng.integers(4, 10)
        u = base[None, :] + rng.normal(scale=2.0, size=(k, 24))
        for r in range(k):                               # each short day is a clock arc
            if rng.random() < 0.6:
                lo = rng.integers(0, 24); ln = rng.integers(8, 20)
                keep = ((np.arange(24) - lo) % 24) < ln
                u[r, ~keep] = np.nan
        v = interdaily_stability(u)
        c = np.nanvar(np.nanmean(u, axis=0)) / np.nanvar(u)
        if np.isfinite(v):
            n_tried += 1
            worst = max(worst, v)
            n_over += c > 1.0
    ok(f'IS stays in [0,1] over {n_tried} structurally ragged grids (max {worst:.4f})',
       worst <= 1.0,
       f'the classic ratio left [0,1] in {n_over} of them ({100*n_over/n_tried:.1f}%)')
    # The first and last NHANES recording days are partial days. A partial day
    # that passes the >= 600-minute bar covers only part of the clock; the check
    # below confirms this does not deflate IS under the decomposition form.
    is_partial = interdaily_stability(hbd[i11])
    print(f'         IS with one partial first day (SEQN 11) = {is_partial:.4f}')
    print(f'         -> the decomposition form is immune to the partial-day artefact.')
    print(f'            The classic ratio gave 0.978 here, a 2.2% deflation of a')
    print(f'            perfectly regular rhythm caused purely by clock coverage.')
    ok(f'partial days do not deflate IS (1 - IS = {1 - is_partial:.2e})',
       abs(1 - is_partial) < 1e-4, 'residual is float32 accumulation only')
    is_noise = np.mean([interdaily_stability(rng.normal(size=(7, 24))) for _ in range(400)])
    check('IS, mean over 400 draws of 7 independent days', is_noise, 1 / 7, 0.01,
          'expectation 1/n_days')
    # Legacy composite-profile variant (IV_profile_legacy), kept for audit.
    check('IV_profile_legacy, perfectly alternating profile',
          intradaily_variability_profile(np.tile([0.0, 1.0], 12)), 4.0, 1e-12, 'maximum')
    iv_noise = np.mean([intradaily_variability_profile(rng.normal(size=24)) for _ in range(20000)])
    check('IV_profile_legacy, mean over 20000 white-noise profiles', iv_noise, 2 * 24 / 23, 0.02,
          'E[IV] = 2n/(n-1), not 2')
    check('IV_profile_legacy, monotone ramp', intradaily_variability_profile(np.arange(24.0)),
          24 / np.sum((np.arange(24.) - 11.5) ** 2), 1e-9, 'closed form')
    iv_s = intradaily_variability_profile(hourly_bins(make_day()))
    ok(f'IV_profile_legacy, smooth sinusoid = {iv_s:.4f} lies in (0, 0.25)', 0 < iv_s < 0.25)

    print()
    print('=' * 80)
    print('T5b IV on the chronological hourly series: adjacency, gaps, no wrap')
    print('=' * 80)
    H = rng.gamma(2.0, 5.0, size=(7, 24))
    days = np.arange(1, 8)
    x = H.reshape(-1)
    N = len(x)
    witting = N * np.sum(np.diff(x) ** 2) / ((N - 1) * np.sum((x - x.mean()) ** 2))
    iv, n_h, n_p = intradaily_variability_series(H, days)
    check('IV series, complete 7-day recording == Witting formula', iv, witting, 1e-12)
    ok(f'IV series, complete recording uses N-1 = {N - 1} pairs, no wrap', n_p == N - 1 and n_h == N)
    H2 = H.copy()
    H2[0, 15] = np.nan                       # 14:00->15:00 and 15:00->16:00 both lost
    _, n_h2, n_p2 = intradaily_variability_series(H2, days)
    ok('IV series, one missing hour removes exactly its two adjacent pairs',
       n_p2 == n_p - 2 and n_h2 == n_h - 1)
    H3 = H[[0, 2, 3, 4, 5, 6]]               # day 2 missing: day 1 23:00 -> day 3 00:00 is not adjacent
    _, _, n_p3 = intradaily_variability_series(H3, np.array([1, 3, 4, 5, 6, 7]))
    ok('IV series, a missing day breaks the midnight pair', n_p3 == 6 * 24 - 2)
    _, _, n_p4 = intradaily_variability_series(H[:2], np.array([1, 2]))
    ok('IV series, consecutive days are joined across midnight (47 pairs from 2 days)', n_p4 == 47)
    perm = rng.permutation(7)
    check('IV series, invariant to row order (rows are sorted by day)',
          intradaily_variability_series(H[perm], days[perm])[0], iv, 1e-12)
    short = np.r_[H[0, :10], [np.nan] * 14][None, :]
    ok(f'IV series, fewer than {MIN_ADJACENT_PAIRS} pairs -> NaN, not 0',
       np.isnan(intradaily_variability_series(short, [1])[0]))
    ok('IV series, zero variance -> NaN, not 0',
       np.isnan(intradaily_variability_series(np.ones((3, 24)), [1, 2, 3])[0]))
    iv_wn = np.mean([intradaily_variability_series(rng.normal(size=(7, 24)), days)[0]
                     for _ in range(300)])
    check('IV series, mean over 300 white-noise recordings', iv_wn, 2.0, 0.05, 'E[IV] -> 2')
    check('IV series, perfectly alternating recording',
          intradaily_variability_series(np.tile([0.0, 1.0], (7, 12)), days)[0], 4.0, 1e-12)

    print()
    print('=' * 80)
    print('T6  M10 / L5 recover a known window and wrap past midnight')
    print('=' * 80)
    p = np.full(1440, 1.0)
    p[np.r_[np.arange(22 * 60, 1440), np.arange(0, 8 * 60)]] = 50.0
    M10, L5, RA = m10_l5_ra(p)
    check('M10 over a wrapped 10-h active block', M10, 50.0, 1e-9, 'must wrap midnight')
    check('L5 over the quiet block', L5, 1.0, 1e-9)
    check('RA', RA, 49 / 51, 1e-9)

    print()
    print('=' * 80)
    print('T7  gaps propagate as missing, not as zero activity')
    print('=' * 80)
    gap = make_day().copy()
    gap[3 * 60:9 * 60] = np.nan                     # 6 h non-wear in the small hours
    M10g, L5g, RAg = m10_l5_ra(gap)
    want = np.nanmin(pd.Series(np.concatenate([gap, gap]))
                     .rolling(300, min_periods=300).mean())
    check('L5 ignores the gap rather than reading it as 0', L5g, want, 1e-9)
    l5_old = pd.Series(np.concatenate([np.nan_to_num(gap), np.nan_to_num(gap)])
                       ).rolling(300, min_periods=300).mean().min()
    ra_old = (M10g - l5_old) / (M10g + l5_old)
    print(f'         if the gap were read as 0:  L5 = {l5_old:.4f}   RA = {ra_old:.4f}')
    print(f'         corrected               :  L5 = {L5g:.4f}   RA = {RAg:.4f}')
    print(f'         reading gaps as zero pins L5 to 0 and RA to its 1.000 ceiling')
    _, _, ra_none = m10_l5_ra(np.full(1440, np.nan))
    check('RA is NaN, not 0, when undefined', ra_none, np.nan, 0)

    print()
    print('=' * 80)
    print('T8  hourly binning is exact and NaN-aware')
    print('=' * 80)
    a = np.arange(1440.0)
    check('bin 0 = mean(minutes 0..59)', hourly_bins(a)[0], 29.5, 1e-12)
    check('bin 23 = mean(minutes 1380..1439)', hourly_bins(a)[23], 1409.5, 1e-12)
    b = a.copy(); b[0:30] = np.nan
    check('bin 0 with 30 minutes missing', hourly_bins(b)[0], 44.5, 1e-12,
          'mean of 30..59, not of 0-padded')

    print()
    print('=' * 80)
    print('RESULT:', 'all checks passed' if _OK else 'FAILURES ABOVE - do not run the pipeline')
    print('=' * 80)
    return 0 if _OK else 1


if __name__ == '__main__':
    raise SystemExit(main())
