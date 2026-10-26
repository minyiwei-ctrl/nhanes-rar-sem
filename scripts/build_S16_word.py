import json
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

D = json.load(open('data.json'))
F, SZ, NSZ = 'Arial', Pt(8), Pt(7)

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Inches(8.5), Inches(11)
for m in ('top_margin', 'bottom_margin', 'left_margin', 'right_margin'):
    setattr(sec, m, Inches(0.75))
st = doc.styles['Normal']; st.font.name = F; st.font.size = SZ
st.paragraph_format.space_before = Pt(0); st.paragraph_format.space_after = Pt(2)


def para(text, bold=False, ital=False, size=SZ, before=0, after=3):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text); r.font.name = F; r.font.size = size
    r.bold, r.italic = bold, ital
    return p


def fixed_layout(tbl, widths):
    """python-docx cell widths are advisory until the table is fixed-layout.

    Without this the renderer autofits, ignores every width set below, and
    breaks confidence intervals across lines mid-number.
    """
    tbl.autofit = False
    tblPr = tbl._tbl.tblPr
    for old in tblPr.findall(qn('w:tblLayout')):
        tblPr.remove(old)
    lay = OxmlElement('w:tblLayout'); lay.set(qn('w:type'), 'fixed')
    tblPr.append(lay)
    grid = tbl._tbl.find(qn('w:tblGrid'))
    if grid is not None:
        tbl._tbl.remove(grid)
    grid = OxmlElement('w:tblGrid')
    for w in widths:
        gc = OxmlElement('w:gridCol'); gc.set(qn('w:w'), str(int(w * 1440)))
        grid.append(gc)
    tbl._tbl.insert(list(tbl._tbl).index(tblPr) + 1, grid)


def clear_borders(tbl):
    """Journal tables are horizontal-rule only: no grid, no verticals."""
    tblPr = tbl._tbl.tblPr
    for old in tblPr.findall(qn('w:tblBorders')):
        tblPr.remove(old)
    b = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        e = OxmlElement(f'w:{edge}'); e.set(qn('w:val'), 'none'); e.set(qn('w:sz'), '0')
        b.append(e)
    tblPr.append(b)


def rule(row, edge, sz):
    for c in row.cells:
        tcPr = c._tc.get_or_add_tcPr()
        for old in tcPr.findall(qn('w:tcBorders')):
            tcPr.remove(old)
        tb = OxmlElement('w:tcBorders')
        e = OxmlElement(f'w:{edge}')
        e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), str(sz)); e.set(qn('w:color'), '000000')
        tb.append(e); tcPr.append(tb)


def put(cell, text, bold=False, ital=False, right=False, size=SZ):
    cell.text = ''
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0.5); p.paragraph_format.space_after = Pt(0.5)
    if right:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p.add_run(str(text)); r.font.name = F; r.font.size = size
    r.bold, r.italic = bold, ital


def span(row):
    """Merge a row into one cell, for the group headings inside Panel A."""
    return row.cells[0].merge(row.cells[-1])


para('Supplementary Table S16 | Marker-level associations of rest–activity rhythm '
     'metrics with components of KDM biological age and the systemic '
     'immune-inflammation index', bold=True, size=Pt(9), after=8)

# ------------------------------------------------------------------ Panel A
para('Panel A. Marker-level associations', bold=True, after=4)
HA = ['Marker', 'Marker group', 'n', 'β (95% CI)', 'P', 'P (Holm)']
WA = [1.45, 1.25, 0.80, 0.45, 1.80, 0.55, 0.70]   # sums to 7.00 in
nrows = 1 + sum(1 + sum(1 + len(b['rows']) for b in g['blocks']) for g in D['groups'])
tA = doc.add_table(rows=nrows, cols=len(HA)); clear_borders(tA); fixed_layout(tA, WA)
tA.alignment = WD_TABLE_ALIGNMENT.LEFT
for i, h in enumerate(HA):
    put(tA.rows[0].cells[i], h, bold=True, right=i >= 3)
rule(tA.rows[0], 'top', 12); rule(tA.rows[0], 'bottom', 6)
i = 1
for gi, g in enumerate(D['groups']):
    put(span(tA.rows[i]), g['age'], bold=True)
    if gi:
        rule(tA.rows[i], 'top', 4)
    i += 1
    for b in g['blocks']:
        put(span(tA.rows[i]), b['metric'], ital=True); i += 1
        for r in b['rows']:
            cs = tA.rows[i].cells
            put(cs[0], r[0])
            put(cs[1], r[1].replace('KDM: ', 'KDM, '))
            put(cs[2], r[2])
            put(cs[3], f'{int(r[3]):,}', right=True)
            # NBSP inside the interval: a confidence interval split across two
            # lines is the single most common way these tables come out ugly.
            put(cs[4], r[4].replace(' ', '\u00a0'), right=True)
            for k in (5, 6):
                put(cs[k], r[k], right=True)
            i += 1
rule(tA.rows[-1], 'bottom', 12)
for row in tA.rows:
    for c, w in zip(row.cells, WA):
        c.width = Inches(w)

# ------------------------------------------------------------------ Panel B
para('', after=6)
para('Panel B. Algebraic decomposition of log SII', bold=True, before=6, after=4)
HB = ['Age group', 'Rhythm\nmetric', 'n', 'B, log\nplatelet', 'B, log\nneutrophil',
      'B, log\nlymphocyte', 'Reconstructed\nB, log SII', 'Directly estimated\nB, log SII',
      'Difference']
WB = [1.30, 0.62, 0.45, 0.68, 0.72, 0.78, 0.85, 0.90, 0.70]   # sums to 7.00 in
WB_ = WB
tB = doc.add_table(rows=1 + len(D['panelb']['rows']), cols=len(HB)); clear_borders(tB); fixed_layout(tB, WB)
tB.alignment = WD_TABLE_ALIGNMENT.LEFT
for i, h in enumerate(HB):
    put(tB.rows[0].cells[i], h.replace('\n', ' '), bold=True, right=i >= 2)
rule(tB.rows[0], 'top', 12); rule(tB.rows[0], 'bottom', 6)
for j, r in enumerate(D['panelb']['rows'], start=1):
    for k, v in enumerate(r):
        t = f'{int(v):,}' if k == 2 else ('<0.0001' if k == 8 else str(v))
        put(tB.rows[j].cells[k], t, right=k >= 2)
rule(tB.rows[-1], 'bottom', 12)
for row in tB.rows:
    for c, w in zip(row.cells, WB):
        c.width = Inches(w)

# ------------------------------------------------------------------- Notes
def typeset(t):
    """The workbook notes are deliberately ASCII so they survive any reader.
    A Word supplement is not that reader, so the real glyphs go back in here."""
    for a, b in [('platelets x neutrophils', 'platelets × neutrophils'),
                 (' -- ', ' — '), ('|beta|', '|β|'),
                 ('so beta is the change', 'so β is the change'),
                 ('interaction beta', 'interaction β'),
                 ('>=', '≥'), ('"', '\u201c'), (' 1 s.d.', ' 1 s.d.')]:
        t = t.replace(a, b)
    # reopen/close the smart quotes in pairs
    out, open_q = [], True
    for ch in t:
        if ch == '\u201c':
            out.append('\u201c' if open_q else '\u201d'); open_q = not open_q
        else:
            out.append(ch)
    return ''.join(out)


para('', after=6)
for t in D['notes']:
    if t.startswith('Supplementary Table S16 |'):
        continue
    if t.startswith(('PANEL A', 'PANEL B', 'BOTH PANELS')):
        head, _, rest = t.partition('. ')
        para(head + '.', bold=True, size=NSZ, before=4, after=2)
        if rest:
            para(typeset(rest), size=NSZ, after=2)
    else:
        para(typeset(t), size=NSZ, after=2)

doc.save('SuppTableS16.docx')
print('wrote SuppTableS16.docx')
