"""Run selected Mplus inputs, preserve prior outputs, and stop on any failed gate.

    python mplus_run.py 'p1_*.inp'                 # inputs in this directory
    python mplus_run.py 'cycle_audit/*.inp'        # inputs in a sub-directory
    MPLUS=/Applications/Mplus/mplus python mplus_run.py '*_edud.inp'
    python mplus_run.py --record 'm_*.inp'         # bind EXISTING outputs, no run

Unlike run_all.sh, every run writes a .run.json record next to the input
(status, sha256 of input, data file and output, the n / strata / PSU counts
and the Wald test where one is expected) and the output is accepted only if
mplus_output_qc.validate_output passes: normal termination, trustworthy
standard errors, an input echo identical to the input file, positive
cognition loadings. A failed output is kept as .failed.out; a previous
output is archived under _previous_runs/ before being replaced. The
sensitivity reports (p1_report.py, freeze_sensitivity_report.py) read only
outputs with a PASS record (mplus_output_qc.read_verified).

--record does not run Mplus. It validates an output that already exists
(the baseline models of the unified re-run, produced by run_all.sh) and
writes the same record with recorded_post_hoc = true and the run date
printed in the Mplus header, so that freeze_sensitivity_report.py can read
the baseline models it compares against. An input whose record already
matches the current input, data and output is left alone; a stale record
is rewritten; an output that fails validation gets no record and stops the
batch.

Imported from the F1 results freeze (2026-10-19) and extended to accept a
sub-directory in the pattern and the --record mode.
"""
import datetime
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from mplus_output_qc import data_file, sha256, validate_output  # noqa: E402


def record_existing(inputs, base):
    """Bind existing outputs to their inputs and data without running Mplus."""
    print(f'Recording {len(inputs)} existing outputs in {base.relative_to(HERE.parent)}', flush=True)
    done = skipped = 0
    for inp in inputs:
        out, record = inp.with_suffix('.out'), inp.with_suffix('.run.json')
        if not out.exists():
            print(f'SKIP {inp.stem}: not run yet (no output)', flush=True)
            skipped += 1
            continue
        shas = dict(input_sha256=sha256(inp), data_sha256=sha256(data_file(inp)), output_sha256=sha256(out))
        if record.exists():
            old = json.loads(record.read_text())
            if old.get('status') == 'PASS' and all(old.get(k) == v for k, v in shas.items()):
                print(f'KEEP {inp.stem}: record already matches input, data and output', flush=True)
                continue
        text = out.read_text(errors='replace')
        try:
            checks = validate_output(inp, text)
        except ValueError as exc:
            print(f'FAIL {inp.stem}: existing output not eligible: {exc}', file=sys.stderr, flush=True)
            return 1
        header = re.search(r'^\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)\s*$', text[:2000], re.M)
        r = dict(model=inp.stem, status='PASS', recorded_post_hoc=True,
                 recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 run_source='existing output (run_all.sh or an earlier Mplus run); validated and bound at record time',
                 mplus_output_date=header[1].strip() if header else None, **shas, checks=checks)
        record.write_text(json.dumps(r, indent=2))
        print(f'PASS {inp.stem}: recorded; n={checks["n"]}, strata={checks["strata"]}, PSUs={checks["psus"]}'
              f'{"; output dated " + r["mplus_output_date"] if header else ""}', flush=True)
        done += 1
    print(f'{done} records written; {skipped} inputs not run yet')
    return 0


def main():
    args = [a for a in sys.argv[1:] if a != '--record']
    record_only = '--record' in sys.argv[1:]
    pattern = args[0] if args else '*.inp'
    folder, _, pattern = pattern.rpartition('/')
    base = (HERE / folder).resolve() if folder else HERE
    inputs = sorted(p for p in base.glob('*.inp') if fnmatch.fnmatch(p.name, pattern))
    if not inputs:
        print(f'FAIL: no inputs match {pattern!r} in {base}', file=sys.stderr)
        return 1
    if record_only:
        return record_existing(inputs, base)
    candidates = [os.environ.get('MPLUS'), shutil.which('mplus'), '/Applications/Mplus/mplus', '/usr/local/bin/mplus', '/opt/mplus/mplus']
    mp = next((p for p in candidates if p and os.access(p, os.X_OK)), None)
    if not mp:
        print('FAIL: set MPLUS to an installed Mplus executable', file=sys.stderr)
        return 1
    print(f'Using {mp}; {len(inputs)} models in {base.relative_to(HERE.parent)}', flush=True)
    for inp in inputs:
        record = inp.with_suffix('.run.json')
        r = dict(model=inp.stem, status='RUNNING', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 executable=mp, input_sha256=sha256(inp), data_sha256=sha256(data_file(inp)))
        record.write_text(json.dumps(r, indent=2))
        fd, tmpname = tempfile.mkstemp(prefix=inp.stem + '.', suffix='.running', dir=base)
        os.close(fd); tmp = Path(tmpname)
        try:
            with inp.with_suffix('.run.log').open('w') as log:
                proc = subprocess.run([mp, inp.name, tmp.name], cwd=base, stdout=log, stderr=subprocess.STDOUT)
            if proc.returncode:
                raise ValueError(f'Mplus returned {proc.returncode}')
            if not tmp.stat().st_size:
                raise ValueError('Mplus produced no new output')
            checks = validate_output(inp, tmp.read_text(errors='replace'))
            if r['input_sha256'] != sha256(inp) or r['data_sha256'] != sha256(data_file(inp)):
                raise ValueError('input or data changed during estimation')
            out = inp.with_suffix('.out')
            if out.exists():
                archive = base / '_previous_runs' / datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                archive.mkdir(parents=True)
                shutil.copy2(out, archive / out.name)
            tmp.replace(out)
            r.update(status='PASS', output_sha256=sha256(out), checks=checks)
            print(f'PASS {inp.stem}: n={checks["n"]}, strata={checks["strata"]}, PSUs={checks["psus"]}', flush=True)
        except (ValueError, OSError) as exc:
            r.update(status='FAIL', error=str(exc))
            if tmp.exists():
                tmp.replace(inp.with_suffix('.failed.out'))
            record.write_text(json.dumps(r, indent=2))
            print(f'FAIL {inp.stem}: {exc}', file=sys.stderr, flush=True)
            return 1
        r['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record.write_text(json.dumps(r, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
