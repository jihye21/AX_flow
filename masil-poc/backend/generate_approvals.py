#!/usr/bin/env python3
import csv, argparse, os

parser = argparse.ArgumentParser()
parser.add_argument("--data", default="../original")
parser.add_argument("--proj", default="../results/full_cash_projection.csv")
parser.add_argument("--out", default="../results")
args = parser.parse_args()

DATA_DIR = args.data
OUT_DIR = args.out

def read_campaigns():
    path = os.path.join(DATA_DIR, "mkt_budget_plan_ms.csv")
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f, delimiter='|'))

def read_projection():
    path = args.proj
    with open(path, newline='', encoding='utf-8') as f:
        return {r['date']: r for r in csv.DictReader(f, delimiter='|')}

def determine_level(requested, settlement, proj):
    for d, rec in proj.items():
        if d <= settlement and rec['covenant_breach'].lower() == 'true':
            return "CEO_BOARD", "covenant_breach_in_window"
    amt = int(requested)
    if amt <= 10000000:
        return "MARKETING_LEAD", "within_marketing_limit"
    else:
        return "MASIL_REP", "masil_threshold"

def run():
    camps = read_campaigns()
    proj = read_projection()
    out=[]
    for c in camps:
        level, reason = determine_level(c['requested_budget_krw'], c['settlement_date'], proj)
        out.append({'plan_id': c['plan_id'], 'campaign_id': c['campaign_id'], 'requested_budget_krw': c['requested_budget_krw'],
                    'settlement_date': c['settlement_date'], 'approval_level': level, 'reason': reason})
    os.makedirs(OUT_DIR, exist_ok=True)
    outp = os.path.join(OUT_DIR, "approval_flags.csv")
    with open(outp,'w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter='|')
        writer.writeheader(); writer.writerows(out)
    print("Wrote", outp)

if __name__ == "__main__":
    run()
