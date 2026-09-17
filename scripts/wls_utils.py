"""
Pure-numpy regression utilities for the supportive analyses (notebooks 6-8 and
11-18): wls_fit() (weighted least squares, HC3 by default), exact t, chi-square
and F tail probabilities without scipy, natural cubic spline and tensor-product
spline bases, partial-dependence curves, and variance inflation factors.
Reads and writes no files.
"""
import warnings
from math import lgamma, log, exp

import numpy as np


# Exact t p-value without scipy
def _betacf(a, b, x, itmax=300, eps=3e-16):
    """Continued fraction for the incomplete beta (Lentz). Scalar."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < 1e-300:
            d = 1e-300
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < 1e-300:
            d = 1e-300
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def _betainc(a, b, x):
    """Regularised incomplete beta I_x(a, b). Scalar."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log(1.0 - x)
    if x < (a + 1.0) / (a + b + 2.0):
        return exp(lbeta) * _betacf(a, b, x) / a
    return 1.0 - exp(lbeta) * _betacf(b, a, 1.0 - x) / b


def student_t_p(t, df):
    """Exact two-sided Student-t p-value, I_{df/(df+t^2)}(df/2, 1/2); no normal approximation."""
    t = np.asarray(t, dtype=float)
    scalar = (t.ndim == 0)
    out = np.empty(np.atleast_1d(t).shape, dtype=float)
    for i, tv in enumerate(np.atleast_1d(t).ravel()):
        if not np.isfinite(tv):
            out.flat[i] = np.nan
        else:
            out.flat[i] = _betainc(df / 2.0, 0.5, df / (df + tv * tv))
    out = np.clip(out, 0.0, 1.0)
    return float(out[0]) if scalar else out


def _gamma_p(a, x, itmax=500, eps=3e-16):
    """Regularised lower incomplete gamma P(a, x): series for x < a + 1, Lentz continued fraction otherwise (Numerical Recipes gammp/gammq)."""
    if x <= 0.0:
        return 0.0
    if x < a + 1.0:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(itmax):
            ap += 1.0
            d *= x / ap
            s += d
            if abs(d) < abs(s) * eps:
                break
        return s * exp(-x + a * log(x) - lgamma(a))
    tiny = 1e-300
    b, c, d, h = x + 1.0 - a, 1.0 / tiny, 0.0, 0.0
    d = 1.0 / b
    h = d
    for i in range(1, itmax + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return 1.0 - exp(-x + a * log(x) - lgamma(a)) * h


def chi2_sf(x, k):
    """Chi-square survival function P(X > x) with k df, via the incomplete gamma."""
    x = float(x)
    if not np.isfinite(x):
        return np.nan
    if x <= 0.0:
        return 1.0
    return float(np.clip(1.0 - _gamma_p(k / 2.0, x / 2.0), 0.0, 1.0))


def f_sf(x, d1, d2):
    """F-distribution survival function P(F > x) = I_{d2/(d2 + d1 x)}(d2/2, d1/2)."""
    x = float(x)
    if not np.isfinite(x):
        return np.nan
    if x <= 0.0:
        return 1.0
    return float(np.clip(_betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * x)),
                         0.0, 1.0))


def norm_cdf(z):
    """Standard normal CDF, pure numpy."""
    return 0.5 * (1.0 + np.tanh(np.sqrt(2.0/np.pi)*(z + 0.044715*z**3)))


def norm_quantile(p):
    """Approximate inverse normal CDF (Beasley-Springer / Moro)."""
    p = np.asarray(p, dtype=float)
    a = [-3.969683028665376e+01,  2.209460984245205e+02,
         -2.759285104469687e+02,  1.383577518672690e+02,
         -3.066479806614716e+01,  2.506628277459239e+00]
    b = [-5.447609879822406e+01,  1.615858368580409e+02,
         -1.556989798598866e+02,  6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    out = np.zeros_like(p)
    mask_lo = p < plow
    mask_hi = p > phigh
    mask_mid = ~(mask_lo | mask_hi)
    q = np.sqrt(-2 * np.log(p[mask_lo]))
    out[mask_lo] = (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                   ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    q = np.sqrt(-2 * np.log(1 - p[mask_hi]))
    out[mask_hi] = -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                    ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    q = p[mask_mid] - 0.5
    r = q*q
    out[mask_mid] = (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q / \
                    (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    return out


# Weighted least squares with robust standard errors
def wls_fit(X, y, w=None, se='hc3', add_const=True):
    """Weighted least squares with HC3, HC1 or classical standard errors.

    Args:
        X: (n, k) predictors; no intercept column when add_const=True.
        y: (n,) outcome.
        w: (n,) positive weights; None gives OLS.
        se: 'hc3' (default), 'hc1' or 'classical'.
        add_const: prepend an intercept column.

    Returns dict with params, se, t, p, ci_lo, ci_hi, n, k, r2, names, cov.

    Survey weights enter the point estimate only: there is no stratum or PSU
    adjustment, so the standard errors are not design-based and are smaller
    than those from Mplus TYPE = COMPLEX.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if w is None:
        w = np.ones(len(y))
    w = np.asarray(w, dtype=float)
    # Drop nan / non-positive weight
    mask = np.isfinite(y) & (w > 0) & np.all(np.isfinite(X), axis=1)
    X = X[mask]; y = y[mask]; w = w[mask]
    n = len(y)
    if add_const:
        X = np.column_stack([np.ones(n), X])
    k = X.shape[1]
    # Scale weights so sum = n (for sensible df)
    w = w * (n / w.sum())
    Wsqrt = np.sqrt(w)
    Xw = X * Wsqrt[:, None]
    yw = y * Wsqrt
    beta, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
    resid = y - X @ beta
    # R^2
    y_mean = np.average(y, weights=w)
    ss_tot = np.sum(w * (y - y_mean)**2)
    ss_res = np.sum(w * resid**2)
    r2 = 1 - ss_res / ss_tot
    # SE
    XtWX_inv = np.linalg.pinv(Xw.T @ Xw)
    if se == 'classical':
        sigma2 = ss_res / (n - k)
        cov = XtWX_inv * sigma2
    elif se == 'hc3':
        # HC3 (MacKinnon-White): meat = X' diag(u^2 / (1-h)^2) X.
        # For WLS, leverage is computed in the whitened design:
        #   h_ii = diag(Xw (Xw' Xw)^{-1} Xw').
        u = Wsqrt * resid
        # Leverage diagonal (avoid forming hat matrix)
        XtWX_pinv = XtWX_inv
        h = np.einsum('ij,jk,ik->i', Xw, XtWX_pinv, Xw)
        h = np.clip(h, 0, 1 - 1e-9)  # numerical safety
        denom = (1 - h) ** 2
        meat = (Xw.T * (u ** 2 / denom)) @ Xw
        cov = XtWX_inv @ meat @ XtWX_inv
    else:  # HC1 (White) using weighted residuals
        u = Wsqrt * resid
        meat = (Xw.T * (u**2)) @ Xw  # X' diag(u^2) X
        cov = XtWX_inv @ meat @ XtWX_inv
        cov = cov * (n / (n - k))  # HC1 correction
    se_arr = np.sqrt(np.maximum(np.diag(cov), 0))
    tstat = beta / se_arr
    p = student_t_p(tstat, df=n - k)
    # 95 % CI using normal approx (close to t for n>~80)
    z95 = 1.959963984540054
    ci_lo = beta - z95 * se_arr
    ci_hi = beta + z95 * se_arr
    names = (['const'] if add_const else []) + [f'x{i}' for i in range(k - int(add_const))]
    return dict(params=beta, se=se_arr, t=tstat, p=p, ci_lo=ci_lo, ci_hi=ci_hi,
                n=n, k=k, r2=r2, names=names, cov=cov)


# Natural cubic spline basis
def ns_basis(x, df=4, knots=None, boundary=None):
    """Natural cubic spline basis with df columns including the linear term (Hastie et al., ESL Ex. 5.4).

    Returns an (n, df) matrix: truncated power basis, linear beyond the
    boundary knots. When knots are not given, boundary knots are the 5th and
    95th percentiles of x; duplicate knots are dropped and no interior knot
    coincides with a boundary.
    """
    x = np.asarray(x, dtype=float)
    if knots is None:
        # use 5%–95% range as boundary knots (mgcv-style)
        b_lo, b_hi = np.quantile(x, [0.05, 0.95])
        k = max(df - 1, 1)
        q = np.linspace(0.0, 1.0, k + 2)[1:-1]
        knots = np.quantile(x, np.clip(q, 0.06, 0.94))
        if boundary is None:
            boundary = (b_lo - 1e-6, b_hi + 1e-6)
    if boundary is None:
        boundary = (np.min(x) - 1e-6, np.max(x) + 1e-6)
    # Drop knots that coincide with boundaries
    knots = np.unique(knots)
    knots = knots[(knots > boundary[0] + 1e-9) & (knots < boundary[1] - 1e-9)]
    if len(knots) < 1:
        # No interior knots: the fallback is a polynomial basis, not a spline.
        warnings.warn('ns_basis: no interior knots survived; falling back to a '
                      'polynomial basis. The result is not a spline fit.',
                      RuntimeWarning, stacklevel=2)
        return np.column_stack([x, x**2])[:, :max(df-1, 1)]
    K = len(knots)
    all_knots = np.concatenate([[boundary[0]], knots, [boundary[1]]])
    Kn = len(all_knots)  # K + 2 total
    # d_k(x) = ((x-xi_k)+^3 - (x-xi_K)+^3) / (xi_K - xi_k)
    def pos_cube(u):
        return np.maximum(u, 0.0) ** 3
    xi_last = all_knots[-1]
    cols = [x.copy()]  # linear column
    for kk in range(Kn - 2):
        denom_a = all_knots[-1] - all_knots[kk]
        denom_b = all_knots[-1] - all_knots[-2]
        dk = (pos_cube(x - all_knots[kk]) - pos_cube(x - xi_last)) / denom_a
        dKm1 = (pos_cube(x - all_knots[-2]) - pos_cube(x - xi_last)) / denom_b
        cols.append(dk - dKm1)
    B = np.column_stack(cols)
    if B.shape[1] != df:
        # Interior knots collapse when x is degenerate or heavily tied; a Wald
        # test on this basis then has fewer degrees of freedom than df implies.
        warnings.warn(f'ns_basis: asked for df={df}, returning {B.shape[1]} '
                      f'columns ({len(knots)} interior knots survived). Any '
                      f'non-linearity test on this basis has different degrees '
                      f'of freedom than intended.', RuntimeWarning, stacklevel=2)
    return B  # (n, K+1), normally == df


def tensor_basis(x1, x2, df1=4, df2=4):
    """Tensor-product natural cubic spline basis for two continuous predictors.

    Returns (B1, B2, Bint): the marginal bases and the centred interaction
    basis B1_c ⊗ B2_c with the main effects partialled out, so Bint spans the
    interaction space only (as mgcv::ti()).
    """
    B1 = ns_basis(x1, df=df1)
    B2 = ns_basis(x2, df=df2)
    # Centre marginal basis columns
    B1c = B1 - B1.mean(axis=0)
    B2c = B2 - B2.mean(axis=0)
    n = len(x1)
    # Build all pairwise products
    cols = []
    for i in range(B1c.shape[1]):
        for j in range(B2c.shape[1]):
            cols.append(B1c[:, i] * B2c[:, j])
    Bint = np.column_stack(cols)
    # Partial out the marginal main effects from interaction (orthogonalize)
    M = np.column_stack([B1, B2])
    Q, _ = np.linalg.qr(M)
    Bint = Bint - Q @ (Q.T @ Bint)
    return B1, B2, Bint


def smooth_pdep(x, beta_smooth, B_grid, x_grid, cov, idx_smooth):
    """Partial-dependence curve and 95% pointwise CI for a smooth term.

    Args:
        beta_smooth: coefficients of the smooth columns.
        B_grid: basis matrix evaluated on x_grid.
        cov: full parameter covariance from wls_fit.
        idx_smooth: indices of the smooth columns in the full parameter vector.

    Returns (f, lower, upper) on x_grid.
    """
    sub_cov = cov[np.ix_(idx_smooth, idx_smooth)]
    f = B_grid @ beta_smooth
    var_f = np.einsum('ij,jk,ik->i', B_grid, sub_cov, B_grid)
    se_f = np.sqrt(np.maximum(var_f, 0))
    return f, f - 1.96 * se_f, f + 1.96 * se_f


def vif(X):
    """Variance inflation factor per column of X (no intercept assumed)."""
    X = np.asarray(X, dtype=float)
    k = X.shape[1]
    out = np.zeros(k)
    for j in range(k):
        y = X[:, j]
        Xm = np.delete(X, j, axis=1)
        Xm = np.column_stack([np.ones(len(y)), Xm])
        beta, *_ = np.linalg.lstsq(Xm, y, rcond=None)
        rss = np.sum((y - Xm @ beta)**2)
        tss = np.sum((y - y.mean())**2)
        r2 = 1 - rss / max(tss, 1e-12)
        out[j] = 1 / max(1 - r2, 1e-12)
    return out
