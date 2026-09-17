"""Map every display item to the script that produces it.

    python display_map.py            # print
    python display_map.py --write    # also write DISPLAY_ITEMS.md

Scans the notebooks and modules in scripts/ for the display-item filenames
they write and matches them against the files in figure/ and result/.
Reports orphans (on disk, produced by nothing), missing items (claimed by a
script, absent from disk), duplicates (two producers for one display number)
and unnumbered files (not matching the Table/Fig naming scheme).
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / 'scripts'

# Where each kind of display item lives, and how its number is read off the name.
LOCATIONS = [
    ('Main figure',  BASE / 'figure' / 'main',          '*.pdf',  r'^(Fig\d+)'),
    ('Supp figure',  BASE / 'figure' / 'supplementary', '*.pdf',  r'^(SuppFigS?\d*)'),
    ('Main table',   BASE / 'result' / 'main',          '*.xlsx', r'^(Table\d+)'),
    ('Supp table',   BASE / 'result' / 'supplementary', '*.xlsx', r'^(SuppTableS\d+)'),
    ('Supp table',   BASE / 'result' / 'supplementary', '*.csv',  r'^(SuppTableS\d+)'),
    ('Source data',  BASE / 'figure' / 'source_data',   '*.xlsx', r'^Source_Data_(.+)$'),
]


def script_sources():
    """{stem written -> [producing scripts]}, by scanning the code for filenames."""
    out = {}
    files = sorted(SCRIPTS.glob('*.ipynb')) + sorted(SCRIPTS.glob('*.py'))
    for f in files:
        if f.name in ('display_map.py', 'verify_figures.py'):
            continue
        if f.suffix == '.ipynb':
            nb = json.loads(f.read_text())
            code = '\n'.join(''.join(c['source']) for c in nb['cells']
                             if c['cell_type'] == 'code')
        else:
            code = f.read_text()
        # A filename inside a comment is a mention, not a write.
        code = re.sub(r'^\s*#.*$', '', code, flags=re.M)
        code = re.sub(r'\"\"\".*?\"\"\"', '', code, flags=re.S)
        # A filename inside a retirement block ('_superseded' or '.replace(_d'
        # within the next 400 characters) is a file the script moves away, not
        # one it writes.
        for m in re.finditer(r"['\"]((?:Fig|SuppFig|Table|SuppTable)[\w\-]*)"
                             r"(?:\.(?:pdf|png|csv|xlsx))?['\"]", code):
            window = code[m.start():m.start() + 400]
            if '_superseded' in window or '.replace(_d' in window:
                continue
            # 'SuppFig' as a startswith() test, or a bare prefix, is a routing
            # decision, not a filename.
            before = code[max(0, m.start() - 30):m.start()]
            if 'startswith' in before or 'endswith' in before:
                continue
            if m.group(1) in ('SuppFig', 'Fig', 'Table', 'SuppTable'):
                continue
            out.setdefault(m.group(1), set()).add(f.name)
        # Names built through the FIGNUM / TABNUM registries
        for m in re.finditer(r"(FIGNUM|TABNUM)\s*=\s*\{(.*?)\}", code, re.S):
            for v in re.findall(r":\s*'([^']+)'", m.group(2)):
                out.setdefault(v, set()).add(f.name)
    return {k: sorted(v) for k, v in out.items()}


def build():
    produced = script_sources()
    rows, problems = [], []

    for kind, d, pattern, numre in LOCATIONS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob(pattern)):
            if f.name.startswith('~$'):
                continue
            # A table delivered as both .csv and .xlsx is one item, not two.
            if f.suffix == '.csv' and f.with_suffix('.xlsx').exists():
                continue
            stem = f.stem
            m = re.match(numre, stem)
            number = m.group(1) if m else ''
            # who writes it: exact stem, else the registry value it came from
            who = produced.get(stem, [])
            if not who and kind == 'Source data':
                who = produced.get(stem.replace('Source_Data_', ''), [])
            if not who:
                for k, v in produced.items():
                    if k and (k in stem or stem in k):
                        who = v
                        break
            sheets = ''
            if f.suffix == '.xlsx':
                try:
                    sheets = ', '.join(pd.ExcelFile(f).sheet_names)
                except Exception as e:                      # pragma: no cover
                    sheets = f'(unreadable: {e})'
            rows.append(dict(kind=kind, number=number, file=f.name,
                             produced_by=', '.join(who) or '(UNKNOWN)',
                             sheets=sheets))
            if stem == 'Supp_Tables':
                who = who or ['mplus_report.py']
                number = 'S3-S7'
                rows[-1].update(number=number, produced_by=', '.join(who))
            if not who:
                problems.append(f'ORPHAN     {f.relative_to(BASE)} — no script writes this')
            if not number and kind != 'Source data':
                problems.append(
                    f'UNNUMBERED {f.name} — does not match {numre}. '
                    'Every other supplementary table is one numbered file; '
                    'this one bundles S3-S7 as sheets.')

    t = pd.DataFrame(rows)
    # Numeric sort: lexical order would put S10 before S1.
    t['_k'] = t.number.str.extract(r'(\d+)').astype(float).fillna(0)
    t = t.sort_values(['kind', '_k', 'file']).drop(columns='_k')

    # two producers for one number, within a kind
    for (kind, number), g in t[t.number != ''].groupby(['kind', 'number']):
        if g.produced_by.nunique() > 1:
            problems.append(f'DUPLICATE  {kind} {number} written by '
                            + ' and '.join(sorted(set(g.produced_by))))

    # Claimed by a script but not on disk. A name present in _superseded/ is
    # not missing: the script names it only to move it there.
    retired = {f.stem for f in (BASE / '_superseded').rglob('*')} \
        if (BASE / '_superseded').is_dir() else set()
    on_disk = set(t.file.str.replace(r'\.(xlsx|pdf)$', '', regex=True))
    for stem, who in produced.items():
        if not re.match(r'^(Fig\d|SuppFig|Table\d|SuppTableS)', stem):
            continue
        if stem in on_disk or stem in retired:
            continue
        problems.append(f'MISSING    {stem} — claimed by {", ".join(who)}, not on disk')

    return t, problems


def main():
    t, problems = build()
    with pd.option_context('display.width', 220, 'display.max_rows', None,
                           'display.max_colwidth', 46):
        for kind in ['Main figure', 'Main table', 'Supp figure', 'Supp table',
                     'Source data']:
            sub = t[t.kind == kind]
            if not len(sub):
                continue
            print(f'\n=== {kind} ({len(sub)}) ===')
            cols = ['number', 'file', 'produced_by'] + (
                ['sheets'] if sub.sheets.any() else [])
            print(sub[cols].to_string(index=False))

    print(f'\n{len(t)} display items across '
          f'{t.produced_by.nunique()} producing scripts')
    if problems:
        print('\nPROBLEMS')
        for p in sorted(set(problems)):
            print(' ', p)
    else:
        print('no orphans, duplicates, missing files or unnumbered items')

    if '--write' in sys.argv:
        out = BASE / 'DISPLAY_ITEMS.md'
        lines = ['# Display items and the scripts that produce them', '',
                 'Generated by `scripts/display_map.py`. Do not edit by hand — '
                 'rerun it after any rename.', '']
        for kind in ['Main figure', 'Main table', 'Supp figure', 'Supp table']:
            sub = t[t.kind == kind]
            if not len(sub):
                continue
            lines += [f'## {kind}s', '', '| number | file | produced by |',
                      '|---|---|---|']
            for _, r in sub.iterrows():
                lines.append(f'| {r.number or "—"} | `{r.file}` | `{r.produced_by}` |')
            lines.append('')
        lines += ['## Checks', '']
        lines += ([f'- {p}' for p in sorted(set(problems))] if problems
                  else ['- No orphans, duplicates, missing files or unnumbered items.'])
        out.write_text('\n'.join(lines) + '\n')
        print(f'\nwrote {out.relative_to(BASE)}')
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
