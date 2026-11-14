# backend/llm_wrapper.py
import os, json, time, csv  

try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

def build_prompt(run_id, summary, top_pos):
    prompt = {
        "instruction": "Given the run summary and top purchase orders, generate department-specific action plans (purchase, sales, marketing). Return JSON object with keys purchase/sales/marketing, each a list of actions with rationale and estimated impact.",
        "run_id": run_id,
        "summary": summary,
        "top_pos": top_pos
    }
    return json.dumps(prompt, ensure_ascii=False)

def call_llm(prompt_text, model="gpt-4o-mini", max_tokens=512):
    if not OPENAI_AVAILABLE or not OPENAI_API_KEY:
        data = json.loads(prompt_text)
        pos = data.get("top_pos", [])
        purchase = []
        if pos:
            total_amt = sum(p.get("amount_krw", 0) for p in pos)
            purchase.append({
                "action": "negotiate_postpone_or_split",
                "po_ids": [p["po_id"] for p in pos],
                "total_amount_krw": total_amt,
                "rationale": "concentrated payments on single date causing covenant breach",
                "expected_recovery": f"reduces immediate outflow up to {total_amt:,} KRW"
            })
        sales = [{"action": "prioritize_collection", "rationale": "accelerate AR from major customers", "expected_recovery": "improved cash in 7-14 days"}]
        marketing = [{"action": "reduce_campaign_volume", "percent": 30, "rationale": "reduce near-term demand to match supply and cash constraints"}]
        return {"purchase": purchase, "sales": sales, "marketing": marketing, "model": "local_stub"}

    openai.api_key = OPENAI_API_KEY
    resp = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are an operations advisor."},
            {"role": "user", "content": prompt_text}
        ],
        max_tokens=max_tokens,
        temperature=0.0
    )
    text = resp['choices'][0]['message']['content']
    try:
        return json.loads(text)
    except Exception:
        return {"text": text, "model": model}

def generate_recommendations(run_dir):
    summary_path = os.path.join(run_dir, "summary.json")
    if not os.path.isfile(summary_path):
        return {}
    with open(summary_path, "r", encoding='utf-8') as fh:
        summary = json.load(fh)

    data_po = []
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    po_path = os.path.join(base_dir, "masil-poc", "original", "sc_purchase_orders_ms.csv")
    
    if os.path.isfile(po_path):
        with open(po_path, newline='', encoding='utf-8') as fh:
            rdr = csv.DictReader(fh, delimiter='|')
            first_breach = summary.get("shortfalls_sample", [])
            target_dates = set([s[0] for s in first_breach if isinstance(s, (list, tuple)) and len(s) > 0])
            for r in rdr:
                if r.get('payment_due_date') in target_dates:
                    data_po.append({
                        "po_id": r.get('po_id'),
                        "sku_id": r.get('sku_id'),
                        "supplier_id": r.get('supplier_id'),
                        "amount_krw": int(r.get('amount_krw') or 0),
                        "payment_due_date": r.get('payment_due_date')
                    })
                    
    prompt = build_prompt(os.path.basename(run_dir), summary, data_po)
    rec = call_llm(prompt)
    out_path = os.path.join(run_dir, "recommendations.json")
    with open(out_path, "w", encoding='utf-8') as fh:
        json.dump({"prompt": prompt, "recommendations": rec, "ts": time.time()}, fh, indent=2, ensure_ascii=False)
    return rec
