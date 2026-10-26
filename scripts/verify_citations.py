"""Check that every display item on disk is cited in the manuscript body and
that every citation points at an item that exists.

    python verify_citations.py                       # the Markdown drafts
    python verify_citations.py path/to/Manuscript.docx   # a Word manuscript

Exit code 1 on any failure, one line per finding. The body is
manuscript/1_Introduction.md, 2_Methods.md, MANUSCRIPT_RESULTS.md and
4_Discussion.md; MANUSCRIPT_RESULTS.md is cut at the first horizontal rule
after its last '## ' results heading, before its provenance appendix. When a
.docx is given instead, its paragraph text is the body (read from the
document XML; no python-docx needed). With neither the drafts nor a .docx
the check is skipped, not failed, because the manuscript is not part of the
public repository.
A citation is "Supplementary Table S4", "Supplementary Tables S3 and S4",
"Supplementary Tables S2, S3, S12 and S15", "Supplementary Tables S8-S11"
(a range), "Supplementary Fig. S3" or "Supp Table S4", case-insensitive, and
the same forms without the S ("Supplementary Table 12", the journal style of
the Word manuscript); a bare "S4" or "Fig. S3" without the word
Supplementary does not count.
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
    r'((?:S?\d+[a-z]?)(?:\s*(?:,|and|to|–|—|-|;)\s*(?:and\s+)?S?\d+[a-z]?)*)',
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


def expand(spec, prefix=''):
    """Item numbers in a citation spec ("S3, S4 and S8-S11" or "3-4, 11")."""
    nums = set()
    for a, b in RANGE.findall(spec):
        nums.update(range(int(a), int(b) + 1))
    for n in re.findall(r'(\d+)', spec):
        nums.add(int(n))
    return nums


def docx_text(path):
    """Paragraph text of a .docx: runs joined without separators inside a
    paragraph (Word splits words across runs), paragraphs separated by
    newlines; tabs and breaks become spaces."""
    import xml.etree.ElementTree as ET
    import zipfile
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    paras = []
    for p in root.iter(f'{W}p'):
        parts = []
        for el in p.iter():
            if el.tag == f'{W}t':
                parts.append(el.text or '')
            elif el.tag in (f'{W}tab', f'{W}br', f'{W}cr'):
                parts.append(' ')
            elif el.tag == f'{W}noBreakHyphen':
                parts.append('-')
            elif el.tag == f'{W}sym':
                # A symbol-font character (Word stores it outside the text
                # run); the ranges in the current manuscript use Symbol
                # F02D, the minus sign. Map the private-use code to ASCII.
                code = int(el.get(f'{W}char', '0'), 16)
                parts.append(chr(code - 0xF000) if 0xF000 <= code < 0xF100 else '?')
        paras.append(''.join(parts))
    return '\n'.join(paras)


def body_sections(docx=None):
    """[(section name, text)] — the Word file if given, else the drafts."""
    if docx is not None:
        return [(Path(docx).name, docx_text(docx))]
    out = []
    for sec, path in BODY.items():
        if not path.exists():
            continue
        text = path.read_text()
        if sec == 'Results':
            text = results_prose(text)
        out.append((sec, text))
    return out


def citations(docx=None):
    cited = {'Supp Table': {}, 'Supp Fig': {}, 'Table': {}, 'Fig': {}}
    for sec, text in body_sections(docx):
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
    docx = next((Path(a) for a in sys.argv[1:] if a.lower().endswith('.docx')), None)
    if docx is not None and not docx.exists():
        raise SystemExit(f'{docx} not found')
    if docx is None and not any(p.exists() for p in BODY.values()):
        # The manuscript is not part of the public repository, and since
        # October 2026 the working manuscript is a Word file; without the
        # drafts the check is skipped, not failed. Point it at the Word file
        # to run it: python verify_citations.py manuscript/EJE/<file>.docx
        print('no manuscript drafts (manuscript/*.md) -- citation check skipped; '
              'pass a .docx to check a Word manuscript')
        return 0
    cited, disk = citations(docx), on_disk()
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
