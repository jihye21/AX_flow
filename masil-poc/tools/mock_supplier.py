#!/usr/bin/env python3

import argparse, json, os, uuid, random, datetime, sys

def now_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def write_event(run_out, event):
    events_file = os.path.join(run_out, "events_log.csv")
    header_needed = not os.path.exists(events_file)
    with open(events_file, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("event_id|run_id|entity_type|entity_id|event_type|actor|payload|timestamp\n")
        line = "|".join([
            event.get("event_id",""),
            event.get("run_id",""),
            event.get("entity_type",""),
            event.get("entity_id",""),
            event.get("event_type",""),
            event.get("actor",""),
            json.dumps(event.get("payload",{}), ensure_ascii=False),
            event.get("timestamp","")
        ])
        f.write(line + "\n")

def simulate_response(po_id, amount, scenario, run_id, supplier="MockSup"):
    # scenarios: accept, partial, reject, delay, random
    if scenario == "random":
        r = random.random()
        if r < 0.75:
            scenario = "accept"
        elif r < 0.92:
            scenario = "partial"
        else:
            scenario = "reject"

    if scenario == "accept":
        payload = {"status":"accepted","accepted_amount": amount, "notes": "Auto-accepted by mock supplier"}
        evt_type = "SUPPLIER_ACCEPT"
    elif scenario == "partial":
        # partial: accept some percentage
        pct = random.choice([50, 60, 70, 80])
        accepted_amount = int(amount * pct / 100)
        payload = {"status":"partial","accepted_amount": accepted_amount, "percent": pct, "notes": "Partial acceptance"}
        evt_type = "SUPPLIER_PARTIAL"
    elif scenario == "reject":
        payload = {"status":"rejected","accepted_amount": 0, "notes": "Rejected by mock supplier"}
        evt_type = "SUPPLIER_REJECT"
    elif scenario == "delay":
        # supplier confirms but with delay
        new_date = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).date().isoformat()
        payload = {"status":"delayed","new_payment_date": new_date, "notes":"Supplier requested delay"}
        evt_type = "SUPPLIER_DELAY"
    else:
        payload = {"status":"unknown","notes":"Unknown scenario"}
        evt_type = "SUPPLIER_UNKNOWN"

    event = {
        "event_id": f"E-SUP-{uuid.uuid4().hex[:8]}",
        "run_id": run_id,
        "entity_type": "PO",
        "entity_id": po_id,
        "event_type": evt_type,
        "actor": supplier,
        "payload": payload,
        "timestamp": now_iso()
    }
    return event

def handle_single(run_out, po_id, amount, scenario, run_id, supplier):
    ev = simulate_response(po_id, amount, scenario, run_id, supplier)
    write_event(run_out, ev)
    print("WROTE_EVENT:", ev["event_id"], ev["event_type"], ev["payload"])
    return ev

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-out", required=True, help="path to run_out folder")
    p.add_argument("--po-id", help="PO id to simulate")
    p.add_argument("--amount", type=int, help="amount in KRW")
    p.add_argument("--scenario", choices=["accept","partial","reject","delay","random"], default="random")
    p.add_argument("--supplier", default="MockSup")
    p.add_argument("--batch-file", help="JSON file with list of requests: [{po_id,amount,scenario}]")
    p.add_argument("--run-id", help="run_id (optional)")
    args = p.parse_args()

    run_out = args.run_out
    if not os.path.isdir(run_out):
        print("ERROR: run_out not found:", run_out, file=sys.stderr)
        sys.exit(2)

    # get run_id from run metadata if not provided
    run_id = args.run_id
    if not run_id:
        meta_path = os.path.join(run_out, "run_metadata.json")
        if os.path.exists(meta_path):
            try:
                meta = json.load(open(meta_path, encoding='utf-8'))
                run_id = meta.get("run_id", None)
            except Exception:
                run_id = None

    if not run_id:
        print("WARN: run_id not provided and not found in run_metadata.json; using 'unknown-run'")
        run_id = "unknown-run"

    results = []
    if args.batch_file:
        data = json.load(open(args.batch_file, encoding='utf-8'))
        for req in data:
            po = req.get("po_id")
            amt = req.get("amount")
            sc = req.get("scenario", args.scenario)
            ev = handle_single(run_out, po, amt, sc, run_id, args.supplier)
            results.append(ev)
    else:
        if not args.po_id:
            print("ERROR: po-id required when not using batch-file", file=sys.stderr)
            sys.exit(3)
        if args.amount is None:
            print("ERROR: amount required when not using batch-file", file=sys.stderr)
            sys.exit(3)
        ev = handle_single(run_out, args.po_id, args.amount, args.scenario, run_id, args.supplier)
        results.append(ev)

    # output summary
    print(json.dumps({"run_id": run_id, "events": [e["event_id"] for e in results]}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()