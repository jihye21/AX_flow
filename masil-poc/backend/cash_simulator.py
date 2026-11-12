#!/usr/bin/env python3
import csv, argparse, os
from datetime import date, timedelta

parser = argparse.ArgumentParser()
parser.add_argument("--scenario", default="base")
parser.add_argument("--out", default="../results")
parser.add_argument("--data", default="../original")
args = parser.parse_args()

DATA_DIR = args.data
OUT_DIR = args.out

def read_opening():
    path = os.path.join(DATA_DIR, "fin_cash_daily_ms.csv")
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f, delimiter='|'))
    last = rows[-1]
    return int(last['closing_balance'])

def read_ar():
    ar={}
    path = os.path.join(DATA_DIR, "fin_ar_aging_ms.csv")
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f, delimiter='|'):
            d = r['due_date']; amt = int(r['amount_krw']); ar[d]=ar.get(d,0)+amt
    return ar

def read_ap_none():
    ap={}
    path = os.path.join(DATA_DIR, "fin_ap_aging_ms.csv")
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f, delimiter='|'):
            if r['po_id'].strip().upper()=='NONE':
                d=r['payment_due_date']; amt=int(r['amount_krw']); ap[d]=ap.get(d,0)+amt
    return ap

def read_pos():
    pos={}
    path = os.path.join(DATA_DIR, "sc_purchase_orders_ms.csv")
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f, delimiter='|'):
            d=r['payment_due_date']; amt=int(r['amount_krw']); pos[d]=pos.get(d,0)+amt
    return pos

def daterange(start, days):
    for i in range(days):
        yield (start + timedelta(days=i)).isoformat()

def run_simulation():
    opening = read_opening()
    if args.scenario == 'conservative': opening = int(opening * 0.9)
    if args.scenario == 'optimistic': opening = int(opening * 1.1)
    ar = read_ar(); ap = read_ap_none(); pos = read_pos()
    start = date(2026,7,1); days = 90
    bal = opening
    rows=[]
    for d in daterange(start, days):
        in_ar = ar.get(d,0); out_ap = ap.get(d,0); out_po = pos.get(d,0)
        closing = bal + in_ar - out_ap - out_po
        breach = closing < 3000000000
        rows.append({'date':d,'opening_balance_krw':str(bal),'ar_collections_krw':str(in_ar),
                     'ap_none_payments_krw':str(out_ap),'po_outflows_krw':str(out_po),
                     'closing_balance_krw':str(closing),'covenant_breach':str(breach)})
        bal = closing
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "full_cash_projection.csv")
    with open(out,'w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter='|')
        writer.writeheader(); writer.writerows(rows)
    print("Wrote", out)

if __name__ == "__main__":
    run_simulation()
