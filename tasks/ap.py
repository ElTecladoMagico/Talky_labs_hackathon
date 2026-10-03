"""Partial AP decision runner: source-backed market representation fees.

Ponytail ceiling: other AP profiles stay pending until their own policy/tests
exist. This runner does not reconcile cash or write P2's bank_explained.
"""
import json
import re
from email.utils import parseaddr
from common import db
from common.je import make_je, norm_num, propose
from tasks.ap_extract import _rows, extract_phase


def _key(vendor, number, currency, gross):
    # An F- prefix denotes a resubmitted invoice, not a different bill.
    return vendor, norm_num(re.sub(r'^F[-/\s]+', '', number or '', flags=re.I)), currency, gross


def _phase(conn):
    month = db.get_json(conn, 'tasks/close')['month']
    paths = [p for p in db.PHASES.values()
             if json.loads((p / 'tasks/close.json').read_text())['month'] == month]
    if len(paths) != 1:
        raise ValueError('AP phase must be unambiguous')
    return paths[0]


def _fee_je(conn, d, vendor, company):
    tax_code = vendor['default_tax_code']
    tax = db.get_json(conn, 'erp/tax_codes')['tax_codes'].get(tax_code, {})
    bank = json.loads(vendor['bank'])
    amounts = [d[k] for k in ('net', 'tax', 'gross', 'payable')]
    if (d['document_type'] != 'INVOICE' or d['issues'] or d['po_refs']
            or vendor['po_required'] or vendor['withholding']
            or d['withholding'] or d['retention']
            or d['company'] not in json.loads(vendor['companies'])
            or d['currency'] != 'EUR' or company.get('currency') != d['currency']
            or vendor['currency'] != d['currency'] or vendor['country'] != 'ES'
            or tax.get('country') != 'ES' or tax.get('kind') != 'input'
            or not d['invoice_number'] or not d['invoice_date']
            or not all(type(a) is int and a >= 0 for a in amounts)
            or d['net'] <= 0 or d['gross'] != d['net'] + d['tax']
            or d['payable'] != d['gross']
            or d['tax'] != (d['net'] * tax['rate'] + 5000) // 10000
            or not d['iban'] or d['iban'] != bank.get('iban')
            or parseaddr(d['metadata'].get('from', ''))[1].casefold() != vendor['email'].casefold()):
        return None
    history = conn.execute('''SELECT h.issue_date, l.cost_center, l.wbs
        FROM ap_invoices h JOIN je_line l ON l.entry_id=h.journal_entry AND l.company=h.company
        WHERE h.vendor=? AND h.company=? AND l.account=? AND h.issue_date<=?
        AND h.decision IN ('POST', 'POST_PAYMENT_BLOCK') ORDER BY h.issue_date DESC''',
        (vendor['id'], company['code'], vendor['default_gl_account'], d['invoice_date'])).fetchall()
    if not history:
        return None
    objects = {(cc, wbs) for date, cc, wbs in history if date == history[0][0]}
    if len(objects) != 1:
        return None
    cc, wbs = objects.pop()
    if bool(cc) == bool(wbs):
        return None
    return make_je(d['company'], [
        dict(account=vendor['default_gl_account'], debit=d['net'], credit=0,
             cost_center=cc, wbs=wbs, tax_code=tax_code),
        dict(account='47200000', debit=d['tax'], credit=0),
        dict(account=vendor['reconciliation_account'], debit=0, credit=d['payable'],
             partner=vendor['id'], assignment=d['invoice_number'])])


def run(conn):
    docs = extract_phase(conn, _phase(conn))
    vendors = {v['id']: v for v in _rows(conn, 'vendors')}
    companies = {c['code']: c for c in _rows(conn, 'companies')}
    seen = {_key(h['vendor'], h['number'], h['currency'], h['gross']): h['doc_id']
            for h in _rows(conn, 'ap_invoices') if h['decision'] in ('POST', 'POST_PAYMENT_BLOCK', 'HOLD')}
    results = []
    for d in sorted(docs, key=lambda d: (d['metadata']['received_at'], d['doc_id'])):
        vendor = vendors.get(d['vendor_id'])
        if not vendor or vendor['archetype'] != 'MARKET_REP_FEE':
            continue
        key = _key(d['vendor_id'], d['invoice_number'], d['currency'], d['gross'])
        duplicate = seen.get(key) if d['invoice_number'] and d['gross'] is not None else None
        seen.setdefault(key, d['doc_id'])
        je = None if duplicate else _fee_je(conn, d, vendor, companies.get(d['company'], {}))
        if not duplicate and je is None:
            continue
        event = 'ap:' + d['doc_id']
        existing = conn.execute('SELECT owner, task, company, lines FROM proposed_je WHERE event_key=?', (event,)).fetchone()
        if existing and (je is None or existing[:3] != ('P1', 'ap', je['company'])
                         or json.loads(existing[3]) != je['lines']):
            raise ValueError('AP journal conflict: ' + event)
        if je and not existing:
            propose(conn, event, 'P1', 'ap', je)
        row = dict(d, decision='DUPLICATE' if duplicate else 'POST',
                   duplicate_of=duplicate, journal_entry=je, status='DECIDED',
                   reasons=['Duplicate invoice'] if duplicate else ['Validated market representation fee'])
        conn.execute('''UPDATE ap_result SET company=?, vendor_id=?, invoice_number=?, invoice_norm=?,
            invoice_date=?, payable=?, currency=?, decision=?, data=? WHERE doc_id=?''',
            (d['company'], d['vendor_id'], d['invoice_number'], norm_num(d['invoice_number']),
             d['invoice_date'], d['payable'], d['currency'], row['decision'], json.dumps(row, ensure_ascii=False), d['doc_id']))
        results.append(row)
    return results
