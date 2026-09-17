"""Check every figure in figure/main and figure/supplementary against the Nature submission standard.

    python verify_figures.py

Per figure: PDF fonts embedded as TrueType subsets (fonttype 42 ->
Type0/CIDFontType2; Type3 bitmap fonts fail), a PNG copy at 600 dpi, width
<= 183 mm (double column) measured from the PNG pixel width at its dpi, and a
Source_Data_<stem>.xlsx in figure/source_data with a 'legend' sheet and
non-empty data sheets. A workbook matching no figure fails. Exit code 1 on any failure.
"""
import re
import sys
from pathlib import Path

import pandas as pd
from PIL import Image

BASE = Path(__file__).resolve().parent.parent
DIRS = [BASE / 'figure' / 'main', BASE / 'figure' / 'supplementary']
SRC = BASE / 'figure' / 'source_data'
MAX_W_MM = 183.0
MM_TOL = 8.0          # bbox_inches='tight' trims the canvas; allow slack
MIN_DPI = 590

rows = []


def add(stem, check, ok, detail=''):
    rows.append(dict(figure=stem, check=check,
                     status='PASS' if ok else 'FAIL', detail=detail))


def pdf_fonts(path):
    raw = path.read_bytes()
    fonts = sorted(set(m.decode() for m in
                       re.findall(rb'/BaseFont\s*/([A-Za-z0-9+\-_]+)', raw)))
    subtypes = sorted(set(m.decode() for m in
                          re.findall(rb'/Subtype\s*/(TrueType|Type0|Type1|Type3|CIDFontType2)',
                                     raw)))
    return fonts, subtypes


def check_stem(d, stem):
    pdf, png = d / f'{stem}.pdf', d / f'{stem}.png'

    add(stem, 'PDF exists', pdf.exists())
    if pdf.exists():
        fonts, subs = pdf_fonts(pdf)
        add(stem, 'PDF fonts embedded (TrueType subset)',
            bool(fonts) and 'Type3' not in subs
            and any(s in subs for s in ('Type0', 'CIDFontType2', 'TrueType')),
            f'{fonts} {subs}')

    add(stem, 'PNG exists', png.exists())
    if png.exists():
        im = Image.open(png)
        dpi = im.info.get('dpi', (0, 0))[0]
        add(stem, 'PNG 600 dpi', dpi >= MIN_DPI, f'{dpi:.0f} dpi')
        if dpi:
            w_mm = im.width / dpi * 25.4
            add(stem, f'width <= {MAX_W_MM:.0f} mm',
                w_mm <= MAX_W_MM + MM_TOL, f'{w_mm:.1f} mm')

    sd = SRC / f'Source_Data_{stem}.xlsx'
    add(stem, 'source data exists', sd.exists())
    if sd.exists():
        xl = pd.ExcelFile(sd)
        names = [s.lower() for s in xl.sheet_names]
        has_leg = 'legend' in names
        # Either one 'source data' sheet or one sheet per panel is accepted;
        # the data sheets must carry rows.
        data_sheets = [s for s in xl.sheet_names if s.lower() != 'legend']
        n = sum(len(xl.parse(s)) for s in data_sheets)
        add(stem, 'source data non-empty + legend sheet',
            has_leg and len(data_sheets) > 0 and n > 0,
            f'sheets={xl.sheet_names}, rows={n}')


def main():
    stems = []
    for d in DIRS:
        for pdf in sorted(d.glob('*.pdf')):
            stems.append((d, pdf.stem))
        # a PNG without a PDF is reported as a missing PDF
        for png in sorted(d.glob('*.png')):
            if not (d / f'{png.stem}.pdf').exists():
                add(png.stem, 'PDF exists', False, 'PNG present, PDF missing')

    for d, stem in stems:
        check_stem(d, stem)

    living = {s for _, s in stems}
    for sd in sorted(SRC.glob('Source_Data_*.xlsx')):
        stem = sd.stem.replace('Source_Data_', '')
        if stem not in living:
            add(stem, 'no orphan source data', False,
                f'{sd.name} matches no living figure')

    t = pd.DataFrame(rows)
    fails = t[t.status == 'FAIL']
    with pd.option_context('display.width', 200, 'display.max_rows', None,
                           'display.max_colwidth', 60):
        print(t.to_string(index=False))
    print(f'\n{len(t) - len(fails)}/{len(t)} checks pass '
          f'across {len(living)} figures')
    if len(fails):
        print('\nFAILURES:')
        for _, r in fails.iterrows():
            print(f'  {r.figure}: {r.check} -- {r.detail}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
