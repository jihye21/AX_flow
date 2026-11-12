#!/usr/bin/env python3
import argparse, os, pandas as pd, matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from datetime import datetime
def read_proj(path):
    df = pd.read_csv(path, delimiter='|', dtype=str)
    df['opening_balance_krw'] = df['opening_balance_krw'].astype('int64')
    df['ar_collections_krw'] = df['ar_collections_krw'].astype('int64')
    df['ap_none_payments_krw'] = df['ap_none_payments_krw'].astype('int64')
    df['po_outflows_krw'] = df['po_outflows_krw'].astype('int64')
    df['closing_balance_krw'] = df['closing_balance_krw'].astype('int64')
    df['covenant_breach'] = df['covenant_breach'].astype('bool')
    df['date'] = pd.to_datetime(df['date'])
    return df
def make_plot(df, out_png):
    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(df['date'], df['closing_balance_krw'], marker='o', linewidth=2, label='Closing Balance')
    breaches = df[df['covenant_breach']]
    if not breaches.empty:
        ax.fill_between(df['date'], df['closing_balance_krw'], where=df['covenant_breach'], color='red', alpha=0.2, label='Covenant breach')
    ax.set_ylabel('Closing balance (KRW)')
    ax.set_title('Cash Projection')
    ax.tick_params(axis='x', rotation=30)
    ax.get_yaxis().set_major_formatter(lambda x, pos: f"{int(x):,}")
    ax.legend(); plt.tight_layout(); fig.savefig(out_png, dpi=150); plt.close(fig)
def summarize(df):
    as_of = df['date'].min().date().isoformat()
    min_row = df.loc[df['closing_balance_krw'].idxmin()]
    min_balance = int(min_row['closing_balance_krw']); min_date = pd.to_datetime(min_row['date']).date().isoformat()
    breach_rows = df[df['covenant_breach']]; breach_flag = not breach_rows.empty; breach_period = None
    if breach_flag:
        start = breach_rows['date'].min().date().isoformat(); end = breach_rows['date'].max().date().isoformat()
        breach_period = f"{start} ~ {end}"
    total_ar = int(df['ar_collections_krw'].sum()); total_po = int(df['po_outflows_krw'].sum())
    return {'as_of': as_of, 'min_balance': min_balance, 'min_date': min_date, 'breach_flag': breach_flag, 'breach_period': breach_period, 'total_ar': total_ar, 'total_po': total_po}
def human(x): return f"{x:,} KRW"
def build_pdf(summary, png, out_pdf):
    c = canvas.Canvas(out_pdf, pagesize=A4); w,h = A4; margin = 15*mm; y = h - margin
    c.setFont('Helvetica-Bold', 16); c.drawString(margin, y, 'Cash Projection Report'); y -= 10*mm
    c.setFont('Helvetica', 10); c.drawString(margin, y, f"As-of: {summary['as_of']}"); y -= 6*mm
    c.drawString(margin, y, f"Lowest balance: {human(summary['min_balance'])} on {summary['min_date']}"); y -= 6*mm
    c.drawString(margin, y, f"Total AR (projected): {human(summary['total_ar'])}"); y -= 6*mm
    c.drawString(margin, y, f"Total PO outflows: {human(summary['total_po'])}"); y -= 8*mm
    c.setFont('Helvetica-Bold', 11)
    if summary['breach_flag']:
        c.setFillColorRGB(0.8,0,0); c.drawString(margin, y, f"Covenant breach expected: {summary['breach_period']}"); c.setFillColorRGB(0,0,0)
    else:
        c.drawString(margin, y, 'No covenant breach expected in the horizon')
    y -= 12*mm
    if os.path.exists(png):
        img = ImageReader(png); iw, ih = img.getSize(); max_w = w - 2*margin; max_h = h/2; scale = min(max_w/iw, max_h/ih)
        draw_w = iw * scale; draw_h = ih * scale; img_x = margin; img_y = y - draw_h; c.drawImage(img, img_x, img_y, width=draw_w, height=draw_h); y = img_y - 8*mm
    c.setFont('Helvetica-Bold', 11); c.drawString(margin, y, 'Recommended actions (auto-generated):'); y -= 6*mm; c.setFont('Helvetica', 10)
    if summary['breach_flag']:
        c.drawString(margin, y, '- Hold new cash commitments until review (finance & CEO).'); y -= 5*mm
        c.drawString(margin, y, '- Attempt AR acceleration and AP deferral where possible.'); y -= 5*mm
        c.drawString(margin, y, '- Consider PO split or short-term financing options.'); y -= 6*mm
    else:
        c.drawString(margin, y, '- Proceed with standard approval process; monitor daily cash.'); y -= 6*mm
    c.setFont('Helvetica', 8); c.drawString(margin, 10*mm, f"Generated at {datetime.utcnow().isoformat()}Z"); c.save()
def main():
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--proj', required=True); parser.add_argument('--out', required=True)
    args=parser.parse_args(); proj=args.proj; outdir=args.out
    if not os.path.exists(proj): raise FileNotFoundError(f'Projection file not found: {proj}')
    os.makedirs(outdir, exist_ok=True); png=os.path.join(outdir,'cash_projection.png'); pdf=os.path.join(outdir,'one_pager.pdf')
    df=read_proj(proj); make_plot(df, png); summary=summarize(df); build_pdf(summary, png, pdf); print('Generated:', png, pdf)
if __name__ == '__main__':
    main()
