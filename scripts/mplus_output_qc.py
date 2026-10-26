"""Fail-closed checks shared by the Mplus runner and the sensitivity reports (stdlib only).

Imported from the F1 results freeze (2026-10-19): every output used by
p1_report.py and freeze_sensitivity_report.py is bound to its input and data
file by a .run.json record (written by 9_mplus_models/mplus_run.py) and is
checked for normal termination, trustworthy standard errors, an input echo
identical to the input file, the expected Wald test, and positive cognition
loadings before any number is read from it.
"""
import hashlib
import json
import math
import re
from pathlib import Path


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def data_file(inp):
    m = re.search(r'(?im)^\s*FILE\s*=\s*[\"\']?([^;\"\']+)', inp.read_text())
    if not m:
        raise ValueError(f'{inp.name}: DATA FILE not found')
    return (inp.parent / m.group(1).strip()).resolve()


def sections(text):
    text = re.sub(r'!.*', '', text)
    heads = list(re.finditer(r'(?im)^\s*(DATA|VARIABLE|DEFINE|ANALYSIS|MODEL(?: INDIRECT| CONSTRAINT| TEST)?|OUTPUT|SAVEDATA)\s*:', text))
    return {m.group(1).upper(): re.sub(r'\s+', '', text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]).upper()
            for i, m in enumerate(heads)}


def expected_wald_df(stem):
    if stem.endswith(('_spline', '_spline_age_nl')):
        return 3
    if stem.endswith(('_spline_age', '_quint_age')):
        return 4
    return None


def wald_result(text):
    m = re.search(r'Wald Test of Parameter Constraints\s+Value\s+([\d.Ee+-]+)\s+Degrees of Freedom\s+(\d+)\s+P-Value\s+([\d.Ee+-]+)', text)
    if not m:
        raise ValueError('required Wald test is absent or not numeric')
    w, df, p = float(m[1]), int(m[2]), float(m[3])
    if not all(map(math.isfinite, [w, p])) or w < 0 or not 0 <= p <= 1:
        raise ValueError('invalid Wald statistic or P value')
    return w, df, p


def validate_output(inp, text):
    """Validate actual output; ordinary missing-data warnings remain recorded."""
    if re.search(r'STANDARD ERRORS[\s\S]{0,150}(?:MAY NOT BE\s+TRUSTWORTHY|COULD NOT BE COMPUTED)|(?:NON-POSITIVE|NOT POSITIVE)\s+DEFINITE|MODEL NONIDENTIFICATION', text, re.I):
        raise ValueError('unreliable standard errors, non-positive-definite matrix, or identification warning; not eligible for inference')
    if re.search(r'\*\*\*\s*ERROR|DID NOT (?:CONVERGE|TERMINATE)|NO CONVERGENCE|STANDARD ERRORS.*COULD NOT BE COMPUTED|MODEL ESTIMATION DID NOT TERMINATE', text, re.I):
        raise ValueError('Mplus error, nonconvergence, or unavailable standard errors')
    for marker in ['MODEL FIT INFORMATION', 'MODEL RESULTS', 'CONFIDENCE INTERVALS OF MODEL RESULTS']:
        if marker not in text:
            raise ValueError(f'missing completed-results section: {marker}')
    if 'THE MODEL ESTIMATION TERMINATED NORMALLY' not in text:
        # With STARTS, Mplus 9 replaces that sentence with a ranked solution list.
        m = re.search(r'RANDOM STARTS RESULTS RANKED.*?Fit function values.*?:\s*(.*?)MODEL FIT INFORMATION', text, re.S)
        fits = re.findall(r'^\s*([-\d.]+)\s+([-\d.]+)\s+(?:\d+|unperturbed)\s*$', m[1], re.M) if m else []
        if len(fits) < 2 or sum(abs(float(v[0]) - float(fits[0][0])) < 1e-4 for v in fits) < 2:
            raise ValueError('no normal termination or replicated random-start optimum')
    echo = text.split('INPUT INSTRUCTIONS', 1)[-1]
    echo = re.split(r'\*\*\*\s*(?:WARNING|ERROR)|SUMMARY OF ANALYSIS|INPUT READING TERMINATED', echo, maxsplit=1)[0]
    expected, actual = sections(inp.read_text()), sections(echo)
    for name, body in expected.items():
        if actual.get(name) != body:
            raise ValueError(f'input echo differs in {name}')
    counts = {}
    for key, label in [('n', 'Number of observations'), ('strata', 'Number of strata'), ('psus', 'Number of clusters')]:
        m = re.search(re.escape(label) + r'\s+(\d+)', text)
        if not m or int(m[1]) < 1:
            raise ValueError(f'missing {label}')
        counts[key] = int(m[1])
    wanted = expected_wald_df(inp.stem)
    if wanted:
        w, df, p = wald_result(text)
        if df != wanted:
            raise ValueError(f'Wald df {df}, expected {wanted}')
        counts.update(wald=w, wald_df=df, wald_p=p)
    if re.search(r'COG\s+BY', inp.read_text()):
        stdyx = text.split('STDYX Standardization', 1)[-1].split('R-SQUARE', 1)[0]
        m = re.search(r'COG\s+BY\s*\n(.*?)(?:\n\s*\n)', stdyx, re.S)
        vals = re.findall(r'^\s*(?:MEM_Z|FLUEN_Z|SPEED_Z)\s+([-\d.]+)', m[1], re.M) if m else []
        if len(vals) != 3 or any(float(v) <= 0 for v in vals):
            raise ValueError('three positive cognition loadings not verified')
    return counts


def read_verified(inp):
    """A sensitivity model must have a successful run record binding input, data, and output."""
    out, record = inp.with_suffix('.out'), inp.with_suffix('.run.json')
    if not out.exists() or not record.exists():
        raise ValueError(f'{inp.stem}: output or verified run record missing')
    r = json.loads(record.read_text())
    if r.get('status') != 'PASS':
        raise ValueError(f'{inp.stem}: last run did not pass')
    for key, path in [('input_sha256', inp), ('data_sha256', data_file(inp)), ('output_sha256', out)]:
        if r.get(key) != sha256(path):
            raise ValueError(f'{inp.stem}: stale {key}')
    text = out.read_text(errors='replace')
    return text, validate_output(inp, text)
