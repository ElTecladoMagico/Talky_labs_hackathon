"""Scorer for the Kalmora close hackathon.

usage: python score.py <evaluator_phase_dir> <participant_phase_dir> <submission_dir> [--json out.json]

The submission directory may contain any subset of: ap.jsonl, ar_billing.jsonl, ar_cash.jsonl, bank_rec.jsonl, ic.jsonl, close.jsonl.
Amounts are integer cents. See FORMATO_ENTREGA.md.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

WEIGHTS = {"ap": 0.30, "ar_billing": 0.10, "ar_cash": 0.15, "bank_rec": 0.20, "ic": 0.05, "close": 0.10, "trial_balance": 0.10}


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def norm_num(s):
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper()).lstrip("0")


def je_lines(je, company=None):
    if not je:
        return []
    lines = je.get("lines", je) if isinstance(je, dict) else je
    out = []
    for l in lines:
        amt = int(l.get("debit") or 0) - int(l.get("credit") or 0)
        if amt:
            out.append((l.get("company") or company or (je.get("company") if isinstance(je, dict) else None), str(l["account"]), amt, l.get("partner"),
                        l.get("cost_center") or None, l.get("wbs") or None))
    return out


PARTNER_PREFIXES = ("40", "41", "43", "44", "49", "55", "24", "16")
COST_PREFIXES = ("6", "7", "2")


def norm_line(acc, amt, p, cc, w):
    acc = str(acc)
    p = p if acc.startswith(PARTNER_PREFIXES) else None
    if not acc.startswith(COST_PREFIXES):
        cc = w = None
    return acc, amt, p, cc, w


def je_match(gold, sub, company=None, tol=2):
    """Greedy line matching on (account, partner, cost centre, WBS) with ±tol cents. Returns matched / max(lines)."""
    g = [norm_line(a, amt, p, cc, w) for _, a, amt, p, cc, w in je_lines(gold, company)]
    s = [norm_line(a, amt, p, cc, w) for _, a, amt, p, cc, w in je_lines(sub, company)]
    if not g and not s:
        return 1.0
    pool = defaultdict(list)
    for x in s:
        pool[(x[0], x[2], x[3], x[4])].append(x[1])
    hit = 0
    for acc, amt, p, cc, w in g:
        cand = pool.get((acc, p, cc, w), [])
        best = min(cand, key=lambda v: abs(v - amt), default=None)
        if best is not None and abs(best - amt) <= tol:
            cand.remove(best)
            hit += 1
    return hit / max(len(g), len(s))


def f1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def amount_ok(a, b, tol=1):
    try:
        return abs(int(a) - int(b)) <= tol
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------- AP
def score_ap(gold, sub):
    S = {s["doc_id"]: s for s in sub}
    classes = sorted({g["decision"] for g in gold} | {s.get("decision") for s in sub if s.get("decision")})
    tp, fp, fn = Counter(), Counter(), Counter()
    header, coding, po, je, reasons, payee = [], [], [], [], [], []
    for g in gold:
        s = S.get(g["doc_id"], {})
        sd = s.get("decision")
        if sd == g["decision"]:
            tp[g["decision"]] += 1
        else:
            fn[g["decision"]] += 1
            if sd:
                fp[sd] += 1
        if g["decision"] in ("HOLD", "REJECT", "POST_PAYMENT_BLOCK") and g.get("reasons"):
            reasons.append(1.0 if set(g["reasons"]) & set(s.get("reasons") or []) else 0.0)
        if g["decision"] == "DUPLICATE":
            reasons.append(1.0 if s.get("duplicate_of") == g.get("duplicate_of") else 0.0)
        if g["decision"] not in ("POST", "POST_PAYMENT_BLOCK"):
            continue
        fields = [s.get("company") == g["company"], s.get("vendor_id") == g["vendor_id"], norm_num(s.get("invoice_number")) == norm_num(g["invoice_number"]),
                  s.get("invoice_date") == g["invoice_date"]] + [amount_ok(s.get(k), g.get(k)) for k in ("net", "tax", "gross", "withholding", "retention", "payable")]
        header.append(sum(fields) / len(fields))
        # line coding: amount-weighted greedy match on (account, cost object, tax code)
        gl = [(l["account"], l.get("cost_center"), l.get("wbs"), l["tax_code"], l["amount"]) for l in g.get("lines", [])]
        sl = Counter((l.get("account"), l.get("cost_center"), l.get("wbs"), l.get("tax_code")) for l in s.get("lines", []) for _ in [0])
        samt = defaultdict(int)
        for l in s.get("lines", []):
            samt[(l.get("account"), l.get("cost_center"), l.get("wbs"), l.get("tax_code"))] += int(l.get("amount") or 0)
        tot = sum(abs(x[4]) for x in gl) or 1
        ok = 0
        for acc, cc, wbs, tc, amt in gl:
            k = (acc, cc, wbs, tc)
            take = min(abs(amt), abs(samt.get(k, 0)))
            ok += take
            if k in samt:
                samt[k] -= take if samt[k] > 0 else -take
        coding.append(ok / tot)
        gp = [(l["po"], l["po_item"], l["amount"]) for l in g.get("lines", []) if l.get("po")]
        if gp:
            sp = Counter((l.get("po"), l.get("po_item")) for l in s.get("lines", []) if l.get("po"))
            good = sum(abs(a) for p_, i_, a in gp if sp.get((p_, i_)))
            po.append(good / (sum(abs(a) for *_, a in gp) or 1))
        if g.get("journal_entry"):
            je.append(je_match(g["journal_entry"], s.get("journal_entry"), g["company"]))
        if g.get("payee") or g.get("payment_block"):
            ok_p = (s.get("payee") or {}).get("type") == (g.get("payee") or {}).get("type") if g.get("payee") else True
            ok_b = s.get("payment_block") == g.get("payment_block") if g.get("payment_block") else True
            payee.append(1.0 if ok_p and ok_b else 0.0)
    macro = sum(f1(tp[c], fp[c], fn[c]) for c in classes) / max(1, len(classes))
    avg = lambda x: sum(x) / len(x) if x else 1.0
    parts = dict(decision_macro_f1=macro, header=avg(header), coding=avg(coding), po_match=avg(po), journal_entry=avg(je), reasons=avg(reasons), payee_and_block=avg(payee))
    total = 0.30 * macro + 0.15 * parts["header"] + 0.15 * parts["coding"] + 0.10 * parts["po_match"] + 0.20 * parts["journal_entry"] + 0.05 * parts["reasons"] + 0.05 * parts["payee_and_block"]
    per_class = {c: round(f1(tp[c], fp[c], fn[c]), 3) for c in classes}
    return total, dict(parts, per_decision_f1=per_class, documents=len(gold), answered=sum(1 for g in gold if g["doc_id"] in S))


# ---------------------------------------------------------------------- AR billing
def score_ar_billing(gold, sub):
    S = {s["billing_item"]: s for s in sub}
    scores = []
    for g in gold:
        s = S.get(g["billing_item"], {})
        if s.get("expected") != g["expected"]:
            scores.append(0.0)
            continue
        if g["expected"] != "INVOICE":
            scores.append(1.0)
            continue
        gi, si = g["invoice"], s.get("invoice") or {}
        checks = [si.get("tax_code") == gi["tax_code"], si.get("due_date") == gi["due_date"]] + [amount_ok(si.get(k), gi[k]) for k in ("net", "tax", "retention", "payable")]
        if gi.get("face"):
            sf = si.get("face") or {}
            checks.append(all(sf.get(k) == gi["face"].get(k) for k in ("oficina_contable", "organo_gestor", "unidad_tramitadora")))
        head = sum(checks) / len(checks)
        scores.append(0.6 * head + 0.4 * je_match(g.get("journal_entry"), s.get("journal_entry"), g["company"]))
    return (sum(scores) / len(scores) if scores else 1.0), dict(items=len(gold), answered=sum(1 for g in gold if g["billing_item"] in S))


# ---------------------------------------------------------------------- AR cash application
def score_ar_cash(gold, sub):
    S = {s["bank_line"]: s for s in sub}
    scores = []
    exact = 0
    for g in gold:
        s = S.get(g["bank_line"], {})
        ga = Counter((a.get("invoice") or a.get("pagare"), a["amount"]) for a in g["applications"])
        sa = Counter((a.get("invoice") or a.get("pagare"), int(a.get("amount") or 0)) for a in s.get("applications", []))
        app = 1.0 if ga == sa else (sum((ga & sa).values()) / max(sum(ga.values()), sum(sa.values())) if (ga or sa) else 1.0)
        gr = Counter((r["type"], r["amount"]) for r in g["residuals"])
        sr = Counter((r.get("type"), int(r.get("amount") or 0)) for r in s.get("residuals", []))
        res = 1.0 if gr == sr else (sum((gr & sr).values()) / max(sum(gr.values()), sum(sr.values())) if (gr or sr) else 1.0)
        cust = 1.0 if s.get("customer") == g["customer"] else 0.0
        adj = je_match(g["adjustment"], s.get("adjustment") or [], g["company"])
        sc = 0.15 * cust + 0.45 * app + 0.20 * res + 0.20 * adj
        exact += sc == 1.0
        scores.append(sc)
    return (sum(scores) / len(scores) if scores else 1.0), dict(receipts=len(gold), fully_correct=exact)


# ---------------------------------------------------------------------- bank reconciliation
def score_bank(gold, sub):
    S = {s["account"]: s for s in sub}
    res = {}
    tot = []
    for g in gold:
        s = S.get(g["account"], {})
        gp = {(b, k) for m in g["matches"] for b in m["bank_lines"] for k in m["book_lines"]}
        sp = {(b, k) for m in s.get("matches", []) for b in m.get("bank_lines", []) for k in m.get("book_lines", [])}
        mf = f1(len(gp & sp), len(sp - gp), len(gp - sp))
        gu = {("B", x["bank_line"]): x["category"] for x in g["unmatched_bank"]} | {("L", x["book_line"]): x["category"] for x in g["unmatched_book"]}
        su = {("B", x.get("bank_line")): x.get("category") for x in s.get("unmatched_bank", [])} | {("L", x.get("book_line")): x.get("category") for x in s.get("unmatched_book", [])}
        found = sum(1 for k in gu if k in su)
        cat = sum(1 for k, v in gu.items() if su.get(k) == v)
        uf = f1(found, len(set(su) - set(gu)), len(gu) - found)
        catacc = cat / len(gu) if gu else 1.0
        gadj = [l for a in g["adjustments"] for l in a["lines"]]
        sadj = [l for a in s.get("adjustments", []) for l in a.get("lines", [])]
        adj = je_match(gadj, sadj, g["company"])
        sc = 0.45 * mf + 0.20 * uf + 0.15 * catacc + 0.20 * adj
        res[g["account"]] = round(sc, 4)
        tot.append(sc)
    return (sum(tot) / len(tot) if tot else 1.0), dict(per_account=res)


# ---------------------------------------------------------------------- intercompany
def score_ic(gold, sub):
    gk = {(tuple(sorted(g["pair"])), g["cause"]): g for g in gold}
    sk = {(tuple(sorted(s.get("pair", []))), s.get("cause")): s for s in sub}
    tp = len(set(gk) & set(sk))
    det = f1(tp, len(set(sk) - set(gk)), len(set(gk) - set(sk)))
    adj = []
    for k, g in gk.items():
        s = sk.get(k)
        adj.append(je_match(g["adjustment"], (s or {}).get("adjustment") or [], None) if s else 0.0)
    a = sum(adj) / len(adj) if adj else 1.0
    return 0.6 * det + 0.4 * a, dict(differences=len(gold), detected=tp)


# ---------------------------------------------------------------------- close
def close_key(x):
    t = x.get("type")
    if t == "ACCRUAL":
        return (t, x.get("company"), x.get("vendor"))
    if t in ("PREPAID",):
        return (t, x.get("company"), x.get("invoice"))
    if t == "FX_REVAL":
        return (t, x.get("company"), x.get("item"))
    if t == "BAD_DEBT":
        return (t, x.get("company"), x.get("customer"))
    if t == "WIP_REVENUE":
        return (t, x.get("company"), x.get("billing_item"))
    return (t, x.get("company"), x.get("customer"))


def score_close(gold, sub):
    G = defaultdict(int)
    for g in gold:
        G[close_key(g)] += int(g.get("amount") or 0) if g["type"] != "DOUBTFUL_RECLASS" else 1
    Sx = defaultdict(int)
    for s in sub:
        Sx[close_key(s)] += int(s.get("amount") or 0) if s.get("type") != "DOUBTFUL_RECLASS" else 1
    hits = 0.0
    for k, v in G.items():
        if k not in Sx:
            continue
        tol = 0.15 if k[0] == "ACCRUAL" else 0.0
        if abs(Sx[k] - v) <= max(100, abs(v) * tol):
            hits += 1
        elif abs(Sx[k] - v) <= abs(v) * 0.5:
            hits += 0.4
    rec = hits / len(G) if G else 1.0
    prec = hits / len(Sx) if Sx else (1.0 if not G else 0.0)
    return f1(hits, len(Sx) - hits, len(G) - hits) if G or Sx else 1.0, dict(items=len(G), recall=round(rec, 3), precision=round(prec, 3))


# ---------------------------------------------------------------------- trial balance
def score_tb(ev_dir, subs):
    truth = {(r["company"], r["account"]): r["balance"] for r in load(f"{ev_dir}/golden/trial_balance_truth.jsonl")}
    recorded = {(r["company"], r["account"]): r["balance"] for r in load(f"{ev_dir}/golden/trial_balance_recorded.jsonl")}
    team = defaultdict(int, recorded)
    for name, rows in subs.items():
        for r in rows:
            entries = []
            if name in ("ap", "ar_billing") and r.get("journal_entry"):
                entries.append((r.get("company"), r["journal_entry"]))
            if name in ("ar_cash", "ic") and r.get("adjustment"):
                entries.append((r.get("company"), r["adjustment"]))
            if name == "bank_rec":
                for a in r.get("adjustments", []):
                    entries.append((r.get("company"), a.get("lines", [])))
            if name == "close" and r.get("journal_entry"):
                entries.append((r.get("company"), r["journal_entry"]))
            for comp, je in entries:
                for c, acc, amt, *_ in je_lines(je, comp):
                    team[(c, acc)] += amt
    keys = set(truth) | set(team)
    diff = sum(abs(truth.get(k, 0) - team.get(k, 0)) for k in keys)
    base = sum(abs(truth.get(k, 0) - recorded.get(k, 0)) for k in keys) or 1
    return max(0.0, 1 - diff / base), dict(abs_difference_eur=round(diff / 100, 2), recorded_vs_truth_eur=round(base / 100, 2))


def main(ev_dir, part_dir, sub_dir, out=None):
    gold = {k: load(f"{ev_dir}/golden/{k}.jsonl") for k in ("ap", "ar_billing", "ar_cash", "bank_rec", "ic", "close")}
    subs = {k: load(f"{sub_dir}/{k}.jsonl") for k in gold}
    result = {}
    fns = dict(ap=score_ap, ar_billing=score_ar_billing, ar_cash=score_ar_cash, bank_rec=score_bank, ic=score_ic, close=score_close)
    for k, fn in fns.items():
        sc, det = fn(gold[k], subs[k])
        result[k] = dict(score=round(sc, 4), **det)
    sc, det = score_tb(ev_dir, subs)
    result["trial_balance"] = dict(score=round(sc, 4), **det)
    result["total"] = round(sum(WEIGHTS[k] * result[k]["score"] for k in WEIGHTS) * 100, 2)
    s = json.dumps(result, ensure_ascii=False, indent=1)
    if out:
        open(out, "w").write(s)
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    r = main(*args[:3], out=out)
    print(json.dumps(r, ensure_ascii=False, indent=1))
