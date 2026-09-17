"""Check that every display item on disk is cited in the manuscript body and
that every citation points at an item that exists.

    python verify_citations.py

Exit code 1 on any failure, one line per finding. The body is
manuscript/1_Introduction.md, 2_Methods.md, MANUSCRIPT_RESULTS.md and
4_Discussion.md; MANUSCRIPT_RESULTS.md is cut at the first horizontal rule
after its last '## ' results heading, before its provenance appendix.
A citation is "Supplementary Table S4", "Supplementary Tables S3 and S4",
"Supplementary Tables S2, S3, S12 and S15", "Supplementary Tables S8-S11"
(a range), "Supplementary Fig. S3" or "Supp Table S4", case-insensitive;
a bare "S4" or "Fig. S3" without the word Supplementary does not count.
Main-text items (Table 1-3, Fig. 1-4) are matched by their own pattern.
Supplementary Tables S3-S7 are sheets of Supp_Tables.xlsx, named by number.
"""
import re
import sys
from pathlib import Path


def find_root(start=None):
    p = Path(start or __file__).resolve()
    for q in [p, *p.parents]:
        if (q / 'data' / 'processed').is_dir() and (q / 'scripts').is_dir():
            return q
    raise RuntimeError('project root not found')


BASE = find_root()
MS = BASE / 'manuscript'
BODY = {
    'Introduction': MS / '1_Introduction.md',
    'Methods':      MS / '2_Methods.md',
    'Results':      MS / 'MANUSCRIPT_RESULTS.md',
    'Discussion':   MS / '4_Discussion.md',
}

SUPP_CITE = re.compile(
    r'Suppl?(?:ementary|\.)?\s+(Table|Fig)(?:ure)?s?\.?\s+'
    r'((?:S\d+[a-z]?)(?:\s*(?:,|and|to|–|—|-|;)\s*(?:and\s+)?S\d+[a-z]?)*)',
    re.I)
MAIN_CITE = re.compile(
    r'(?<![A-Za-z])(Table|Fig)(?:ure)?s?\.?\s+'
    r'((?:\d+[A-Za-z]?)(?:\s*(?:,|and|to|–|—|-|;)\s*(?:and\s+)?\d+[A-Za-z]?)*)'
    r'(?!\s*S\d)',
    re.I)
RANGE = re.compile(r'S?(\d+)\s*(?:–|—|-|to)\s*S?(\d+)')


def results_prose(text):
    """Cut MANUSCRIPT_RESULTS.md at the rule that ends its prose."""
    lines = text.split('\n')
    last_heading = max((i for i, l in enumerate(lines) if l.startswith('## ')
                        and not l.lower().startswith(('## provenance', '## notes for'))),
                       default=len(lines))
    for i in range(last_heading, len(lines)):
        if lines[i].strip() == '---':
            return '\n'.join(lines[:i])
    return text


def expand(spec, prefix):
    nums = set()
    for a, b in RANGE.findall(spec):
        nums.update(range(int(a), int(b) + 1))
    for n in re.findall(rf'{prefix}(\d+)', spec):
        nums.add(int(n))
    return nums


def citations():
    cited = {'Supp Table': {}, 'Supp Fig': {}, 'Table': {}, 'Fig': {}}
    for sec, path in BODY.items():
        if not path.exists():
            continue
        text = path.read_text()
        if sec == 'Results':
            text = results_prose(text)
        flat = ' '.join(text.split())
        for m in SUPP_CITE.finditer(flat):
            kind = 'Supp Table' if m.group(1).lower().startswith('tab') else 'Supp Fig'
            for n in expand(m.group(2), 'S'):
                cited[kind].setdefault(n, set()).add(sec)
        # strip supplementary citations before looking for main ones, so
        # "Supplementary Table S4" is not also read as a main-text "Table"
        stripped = SUPP_CITE.sub(' ', flat)
        for m in MAIN_CITE.finditer(stripped):
            kind = 'Table' if m.group(1).lower().startswith('tab') else 'Fig'
            for n in expand(m.group(2), ''):
                cited[kind].setdefault(n, set()).add(sec)
    return cited


def on_disk():
    items = {'Supp Table': {}, 'Supp Fig': {}, 'Table': {}, 'Fig': {}}
    for f in (BASE / 'result' / 'supplementary').glob('SuppTableS*.xlsx'):
        if f.name.startswith('~$'):
            continue
        m = re.match(r'SuppTableS(\d+)', f.name)
        if m:
            items['Supp Table'][int(m.group(1))] = f.name
    combined = BASE / 'result' / 'supplementary' / 'Supp_Tables.xlsx'
    if combined.exists():
        import openpyxl
        for name in openpyxl.load_workbook(combined, read_only=True).sheetnames:
            m = re.match(r'Supp Table S(\d+)', name)
            if m:
                items['Supp Table'][int(m.group(1))] = f'Supp_Tables.xlsx / {name}'
    for f in (BASE / 'figure' / 'supplementary').glob('SuppFigS*.pdf'):
        m = re.match(r'SuppFigS(\d+)', f.name)
        if m:
            items['Supp Fig'][int(m.group(1))] = f.name
    for f in (BASE / 'result' / 'main').glob('Table*.xlsx'):
        if f.name.startswith('~$'):
            continue
        m = re.match(r'Table(\d+)', f.name)
        if m:
            items['Table'][int(m.group(1))] = f.name
    for f in (BASE / 'figure' / 'main').glob('Fig*.pdf'):
        m = re.match(r'Fig(\d+)', f.name)
        if m:
            items['Fig'][int(m.group(1))] = f.name
    return items


def main():
    if not MS.exists():
        # The manuscript is not part of the public repository; without it the
        # check is skipped, not failed.
        print('manuscript/ not present -- citation check skipped '
              '(it runs only where the manuscript drafts are)')
        return 0
    cited, disk = citations(), on_disk()
    fails = []
    print(f'{"item":22s} {"status":10s} cited in')
    for kind in ('Table', 'Fig', 'Supp Table', 'Supp Fig'):
        for n in sorted(disk[kind]):
            secs = cited[kind].get(n)
            if not secs:
                fails.append(f'{kind} {n if kind in ("Table","Fig") else "S%d" % n} '
                             f'({disk[kind][n]}) exists but is cited nowhere in the body')
                status = 'UNCITED'
            else:
                status = 'ok'
            lab = f'{kind} {"S" if kind.startswith("Supp") else ""}{n}'
            print(f'{lab:22s} {status:10s} {", ".join(sorted(secs)) if secs else ""}')
        for n in sorted(cited[kind]):
            if n not in disk[kind]:
                lab = f'{kind} {"S" if kind.startswith("Supp") else ""}{n}'
                fails.append(f'{lab} is cited in {", ".join(sorted(cited[kind][n]))} '
                             f'but no such item exists on disk')
                print(f'{lab:22s} {"MISSING":10s} {", ".join(sorted(cited[kind][n]))}')
    print()
    if fails:
        print(f'{len(fails)} problem(s):')
        for f in fails:
            print(f'  - {f}')
        return 1
    n_items = sum(len(v) for v in disk.values())
    print(f'all {n_items} display items are cited in the body, and every '
          f'citation resolves to an item on disk')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
