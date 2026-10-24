"""Сборка двух PDF из Markdown: формулы, таблицы и закреплённые ссылки на код."""
from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/pdf'
TMP = ROOT / 'tmp/docs-refresh'
COMMIT = '60147f01e4627c0f065170cc02ab451219b3020f'


def fonts():
    candidates = [Path('C:/Windows/Fonts'), Path('/usr/share/fonts/truetype/dejavu')]
    if (candidates[0] / 'arial.ttf').exists():
        regular, bold = candidates[0] / 'arial.ttf', candidates[0] / 'arialbd.ttf'
    else:
        regular, bold = candidates[1] / 'DejaVuSans.ttf', candidates[1] / 'DejaVuSans-Bold.ttf'
    math = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/share/fonts/DejaVuSans.ttf'
    if not math.exists():
        math = regular
    pdfmetrics.registerFont(TTFont('Body', str(regular)))
    pdfmetrics.registerFont(TTFont('BodyBold', str(bold)))
    pdfmetrics.registerFont(TTFont('Math', str(math)))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='BodyBold', italic='Body', boldItalic='BodyBold')


INK = colors.HexColor('#152B3C')
TEAL = colors.HexColor('#087E8B')
MUTED = colors.HexColor('#536777')
LIGHT = colors.HexColor('#EDF5F7')
LINE = colors.HexColor('#D5E1E7')
WIDTH = A4[0] - 112


def clean(text):
    return text.replace('\u2014', '-').replace('\u2013', '-').replace('\u2011', '-')


def inline(text):
    # Экранируем ввод; разрешённые теги создаёт только этот преобразователь.
    text = escape(clean(text))
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<link href="\2" color="#087E8B">\1</link>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`([^`]+)`', r'<font color="#087E8B">\1</font>', text)
    return text


EQUATIONS = {
 'simulation_eligible = (h >= 28) AND fresh': 'simulation_eligible = (h ≥ 28) AND fresh',
 'probability_eligible = (h >= 56) AND fresh': 'probability_eligible = (h ≥ 56) AND fresh',
 'mu_in(w) = sum(I(d), weekday(d)=w) / n(w)': 'μ<sub>in,w</sub> = (1 / n<sub>w</sub>) ∑<sub>d: weekday(d)=w</sub> I<sub>d</sub>',
 'mu_out(w) = sum(O(d), weekday(d)=w) / n(w)': 'μ<sub>out,w</sub> = (1 / n<sub>w</sub>) ∑<sub>d: weekday(d)=w</sub> O<sub>d</sub>',
 'I_expected(t) = mu_in(weekday(t)) + Kin(t)': 'Î<sub>t</sub> = μ<sub>in,w(t)</sub> + K<sub>in,t</sub>',
 'O_expected(t) = mu_out(weekday(t)) + Kout(t)': 'Ô<sub>t</sub> = μ<sub>out,w(t)</sub> + K<sub>out,t</sub>',
 'B_s(t) = B_s(t-1) + I_s(t) - O_s(t) + Kin(t) - Kout(t)': 'B<sub>t</sub><sup>(s)</sup> = B<sub>t−1</sub><sup>(s)</sup> + I<sub>t</sub><sup>(s)</sup> − O<sub>t</sub><sup>(s)</sup> + K<sub>in,t</sub> − K<sub>out,t</sub>',
 'B_s(0) = B0': 'B<sub>0</sub><sup>(s)</sup> = B<sub>0</sub>',
 'p10(t) = Q(0.1, {B_s(t)})': 'p10<sub>t</sub> = Q<sub>0.1</sub>({B<sub>t</sub><sup>(s)</sup>})',
 'p50(t) = Q(0.5, {B_s(t)})': 'p50<sub>t</sub> = Q<sub>0.5</sub>({B<sub>t</sub><sup>(s)</sup>})',
 'p90(t) = Q(0.9, {B_s(t)})': 'p90<sub>t</sub> = Q<sub>0.9</sub>({B<sub>t</sub><sup>(s)</sup>})',
 'D = max(0, -min(M(t), t=0..H))': 'D = max(0, −min<sub>0 ≤ t ≤ H</sub> M<sub>t</sub>)',
 'first_negative = first date with M(t) < 0, t=0..H': 'first_negative: первая дата с M<sub>t</sub> &lt; 0, t = 0…H',
 'P_day(t) = sum(1[B_s(t)<0], s=1..200) / 200': 'P<sub>day,t</sub> = (1 / 200) ∑<sub>s=1…200</sub> 1[B<sub>t</sub><sup>(s)</sup> &lt; 0]',
 'P_period = sum(1[min(B_s(t), t=1..H)<0], s=1..200) / 200': 'P<sub>period</sub> = (1 / 200) ∑<sub>s=1…200</sub> 1[min<sub>1 ≤ t ≤ H</sub> B<sub>t</sub><sup>(s)</sup> &lt; 0]',
 'M_new(t) = M(t) + L*1[t>=a] - (L+C)*1[t>=r]': 'M′<sub>t</sub> = M<sub>t</sub> + L · 1[t ≥ a] − (L + C) · 1[t ≥ r]',
 'M_new(t) = M(t) + A*1[a<=t<b]': 'M′<sub>t</sub> = M<sub>t</sub> + A · 1[a ≤ t &lt; b]',
}


def build(source: Path, destination: Path, short_title: str):
    styles = {
      'title': ParagraphStyle('title', fontName='BodyBold', fontSize=24, leading=28, textColor=INK, spaceAfter=14, keepWithNext=True),
      'h': ParagraphStyle('h', fontName='BodyBold', fontSize=13.5, leading=17, textColor=INK, spaceBefore=15, spaceAfter=8, keepWithNext=True),
      'body': ParagraphStyle('body', fontName='Body', fontSize=10.2, leading=14, textColor=INK, spaceAfter=7, splitLongWords=True, allowWidows=0, allowOrphans=0),
      'small': ParagraphStyle('small', fontName='Body', fontSize=8.8, leading=12, textColor=MUTED, spaceAfter=7),
      'math': ParagraphStyle('math', fontName='Math', fontSize=10.7, leading=21, textColor=INK),
      'cell': ParagraphStyle('cell', fontName='Body', fontSize=9.3, leading=12.5, textColor=INK),
    }
    story = []
    lines = source.read_text(encoding='utf-8').splitlines()
    pending = []
    def flush():
        if pending:
            text = ' '.join(pending)
            # SHA в преамбуле не должен распирать строку.
            text = text.replace(COMMIT, '60147f0 (полный SHA в исходном Markdown)')
            text = text.replace('a62d52df1b93a3c86e8bcca0f476f6d179c378b5', 'a62d52df1b93 (tree)')
            story.append(Paragraph(inline(text), styles['body']))
            pending.clear()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush(); i += 1; continue
        if line.startswith('# '):
            flush()
            story.append(Paragraph('CASHCAST / ТЕХНИЧЕСКИЕ МАТЕРИАЛЫ',styles['small']))
            story.append(Paragraph(inline(line[2:].replace('CashCast: ','')),styles['title']))
        elif line.startswith('## '):
            flush(); story.append(Paragraph(inline(line[3:]),styles['h']))
        elif line.startswith('$$ ') and line.endswith(' $$'):
            flush()
            formulas=[]
            while i < len(lines) and lines[i].startswith('$$ '):
                expr=lines[i][3:-3]
                assert expr in EQUATIONS, expr
                formulas.append(EQUATIONS[expr]); i+=1
            t=Table([[Paragraph('<br/>'.join(formulas),styles['math'])]],colWidths=[WIDTH])
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),LIGHT),('BOX',(0,0),(-1,-1),0.5,LINE),('LEFTPADDING',(0,0),(-1,-1),11),('RIGHTPADDING',(0,0),(-1,-1),11),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
            story.extend([t,Spacer(1,9)]); continue
        elif line.startswith('|'):
            flush(); rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                row=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in row): rows.append(row)
                i+=1
            count=len(rows[0]); assert all(len(r)==count for r in rows)
            widths=[WIDTH*.35,WIDTH*.65] if count==2 else [WIDTH/count]*count
            body=[[Paragraph(inline(c),styles['cell']) for c in r] for r in rows]
            t=Table(body,colWidths=widths,repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),LIGHT),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F7FAFB')]),('GRID',(0,0),(-1,-1),0.4,LINE),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
            story.extend([t,Spacer(1,10)]); continue
        elif re.match(r'^\d+\. ',line):
            flush(); items=[]
            while i < len(lines) and re.match(r'^\d+\. ',lines[i]):
                items.append(Paragraph(inline(lines[i]),styles['body'])); i+=1
            story.append(KeepTogether(items)); continue
        elif line.startswith('- '):
            flush(); text=line
            while i+1<len(lines) and lines[i+1].startswith('  '):
                i+=1; text+=' '+lines[i].strip()
            if text.startswith('- '): text='• '+text[2:]
            story.append(Paragraph(inline(text),styles['body']))
        else:
            pending.append(line)
        i+=1
    flush()

    def page(c,doc):
        c.saveState()
        w,h=A4
        c.setStrokeColor(LINE); c.setLineWidth(.5)
        c.line(56,h-39,w-56,h-39)
        c.line(56,42,w-56,42)
        c.setFillColor(MUTED); c.setFont('Body',8)
        c.drawString(56,h-29,'CASHCAST / '+short_title)
        c.drawString(56,29,'24.10.2026  |  source 60147f0  |  PR #60')
        c.drawRightString(w-56,29,str(doc.page))
        c.restoreState()
    document=SimpleDocTemplate(str(destination),pagesize=A4,leftMargin=56,rightMargin=56,
        topMargin=58,bottomMargin=57,title=source.stem,author='CashCast',subject='Обновление кассовых разрывов по commit 60147f0')
    document.build(story,onFirstPage=page,onLaterPages=page)
    reader=PdfReader(str(destination))
    pages=[p.extract_text() for p in reader.pages]
    assert all(len(p)>180 for p in pages), [(i+1,len(p)) for i,p in enumerate(pages)]
    assert all('\ufffd' not in p for p in pages)
    text='\n\n'.join(pages)
    for expected in ['60147f0','152 100','247 900','56']:
        assert expected in text, expected
    (TMP / (destination.stem+'.txt')).write_text(text,encoding='utf-8')
    return {'path':str(destination),'pages':len(reader.pages),'characters':len(text),'source_commit':COMMIT}


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True); TMP.mkdir(parents=True,exist_ok=True)
    fonts()
    results=[]
    for stem,short in [('technical','КАССОВЫЕ РАЗРЫВЫ: РЕАЛИЗАЦИЯ'),('mathematics','КАССОВЫЕ РАЗРЫВЫ: МАТЕМАТИКА')]:
        results.append(build(ROOT/f'docs/cash-gap-{stem}.md',OUT/f'cashcast-cash-gap-{stem}.pdf',short))
    print(json.dumps(results,ensure_ascii=True,indent=2))
