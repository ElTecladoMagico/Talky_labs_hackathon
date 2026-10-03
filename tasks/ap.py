"""AP decisions from source documents, ERP policy and historical accounting.

No golden input. Unverifiable extraction/coding/FX is an explicit review HOLD,
never a guessed POST. P2 owns bank_explained; P3 owns cash application.
"""
import json
import re
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from email.utils import parseaddr

from common import db
from common.je import make_je, norm_num, propose
from tasks.ap_extract import _rows, _amount, date_iso, extract_phase, fold

AMOUNTS = ('net', 'tax', 'gross', 'withholding', 'retention', 'payable')
ACTIONS = {
    'PROFORMA': 'NONE', 'VENDOR_STATEMENT': 'NONE',
    'FACTORING_NOTICE': 'REGISTER_ALTERNATIVE_PAYEE',
    'TAX_GARNISHMENT_ORDER': 'REGISTER_EMBARGO',
    'BANK_DETAILS_CHANGE': 'UPDATE_BANK_DETAILS',
    'CONTRACTOR_TAX_CERTIFICATE': 'UPDATE_CONTRACTOR_CERTIFICATE',
}
REJECTS = {'WRONG_ADDRESSEE', 'MANDATORY_FIELD_MISSING', 'ISP_NOT_APPLIED',
           'VAT_RATE_INCORRECT', 'WITHHOLDING_MISSING', 'ARITHMETIC_ERROR',
           'CERTIFICATION_CUMULATIVE_BILLED', 'CFDI_MISMATCH'}


def _number(number):
    return re.sub(r'^F[-/\s]+', '', number or '', flags=re.I)


def _key(vendor, number, currency, gross, company=None):
    return vendor, norm_num(_number(number)), currency, gross, company


def _fingerprint(d):
    # A changed bank/addressee/tax/withholding is not a mere resend.
    amounts = tuple(-abs(d[k]) if d['document_type'] == 'CREDIT_NOTE' and d[k] is not None else d[k] for k in AMOUNTS)
    return d['company'], d['invoice_date'], d['currency'], d['document_type'], d['iban'], amounts


def _phase(conn):
    month = db.get_json(conn, 'tasks/close')['month']
    paths = [p for p in db.PHASES.values()
             if json.loads((p / 'tasks/close.json').read_text())['month'] == month]
    if len(paths) != 1:
        raise ValueError('AP phase must be unambiguous')
    return paths[0]


def _round(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _json(value, default):
    return json.loads(value) if isinstance(value, str) else value if value is not None else default


def _fx(conn, currency, local, day):
    def rate(code):
        if code == 'EUR':
            return Decimal(1)
        found = conn.execute("SELECT rate FROM fx_rates WHERE base='EUR' AND currency=? AND date<=? ORDER BY date DESC LIMIT 1", (code, day)).fetchone()
        if not found:
            raise ValueError('FX_RATE_MISSING')
        return Decimal(str(found[0]))
    return rate(local) / rate(currency) if currency != local else Decimal(1)


def _recurring_cost(conn, d, vendor, docs, rows):
    if d['document_type'] != 'INVOICE' or not re.search(r'\bCUPS\s*:', d['text'], re.I):
        return None
    month = d['invoice_date'][:7]
    numbers = {norm_num(o['invoice_number']) for o in docs
               if o['vendor_id'] == vendor['id'] and o['company'] == d['company']
               and o['document_type'] == 'INVOICE' and (o['invoice_date'] or '')[:7] == month}
    numbers.update(norm_num(r[0]) for r in conn.execute(
        "SELECT number FROM ap_invoices WHERE vendor=? AND company=? AND kind='invoice' AND issue_date LIKE ?",
        (vendor['id'], d['company'], month + '%')))
    if len(numbers) < 2:
        return None
    cycles = defaultdict(lambda: defaultdict(set))
    for day, number, account, cc, wbs, tax, kind in rows:
        if kind == 'invoice':
            cycles[day[:7]][norm_num(number)].add((account, cc, wbs, tax))
    complete = [(m, tuple(next(iter(cycle[n])) for n in sorted(cycle)))
                for m, cycle in sorted(cycles.items()) if m < month and len(cycle) == len(numbers)
                and all(len(objects) == 1 for objects in cycle.values())]
    if len(complete) < 2 or complete[-1][1] != complete[-2][1]:
        return None
    pattern = complete[-1][1]
    if len(set(pattern)) != len(pattern):
        return None
    mapping = dict(zip(sorted(numbers), pattern))
    if any(objects != {mapping[number]} for number, objects in cycles.get(month, {}).items()):
        return None
    # ponytail: infer only repeated complete monthly cycles; replace with a
    # CUPS-to-cost-object master when supplied, especially if site ordering changes.
    d['cost_evidence'] = dict(method='RECURRING_SEQUENCE', history_months=[m for m, _ in complete[-2:]],
                              position=sorted(numbers).index(norm_num(d['invoice_number'])) + 1)
    return mapping[norm_num(d['invoice_number'])]


def _bank_recipients(conn, phase):
    accounts = {a['id']: a for a in _rows(conn, 'bank_accounts')}
    month = db.get_json(conn, 'tasks/close')['month']
    found = defaultdict(list)
    for path in sorted((phase / 'bank').glob('*/*.n43')):
        account = accounts.get(path.parent.name)
        if not account or path.stem > month:
            continue
        for record in re.split(r'(?m)(?=^22)', path.read_text(encoding='latin1')):
            header = record.splitlines()[0]
            mandate = re.search(r'\bMANDATO\s+([A-Z0-9-]+)-(\d{4})\b', record)
            invoice = re.search(r'(?m)^2302FRA\s+(\S+)', record)
            if not header.startswith('22') or len(header) < 42 or header[27] != '1' or not mandate or not invoice:
                continue
            vendor, company = mandate.groups()
            if company != account['company'] or not header[28:42].isdigit():
                continue
            key = (vendor, norm_num(_number(invoice[1])), account['currency'], int(header[28:42]))
            found[key].append(dict(company=company, account=account['id'], mandate=mandate[0],
                                   source=str(path.relative_to(phase))))
    return found


def _historic_cost(conn, d, vendor, docs=()):
    rows = conn.execute("""SELECT h.issue_date, h.number, l.account, l.cost_center, l.wbs, l.tax_code, h.kind
        FROM ap_invoices h JOIN je_line l ON l.entry_id=h.journal_entry AND l.company=h.company
        WHERE h.vendor=? AND h.company=? AND h.issue_date<=?
        AND h.decision IN ('POST','POST_PAYMENT_BLOCK')
        AND (l.account LIKE '6%' OR l.account LIKE '2%') ORDER BY h.issue_date DESC, h.doc_id DESC""",
        (vendor['id'], d['company'], d['invoice_date'])).fetchall()
    reference = d.get('credit_reference')
    matched = [r for r in rows if norm_num(r[1]) == norm_num(reference)] if reference else []
    rows = matched or rows
    if not rows:
        raise ValueError('ACCOUNTING_EVIDENCE_MISSING')
    inferred = _recurring_cost(conn, d, vendor, docs, rows)
    objects = {inferred} if inferred else {(acc, cc, wbs, tc) for date, number, acc, cc, wbs, tc, kind in rows
               if date == rows[0][0] and acc == vendor['default_gl_account']}
    if len(objects) != 1:
        raise ValueError('ACCOUNTING_EVIDENCE_AMBIGUOUS')
    acc, cc, wbs, tc = objects.pop()
    if bool(cc) == bool(wbs):
        raise ValueError('ACCOUNTING_EVIDENCE_MISSING')
    return dict(account=acc, cost_center=cc, wbs=wbs, tax_code=tc or vendor['default_tax_code'])


def _item_tax(item, code):
    if any(marker in fold(item['description']) for marker in ('no sujeto', 'no sujeit', 'non-taxable')):
        return 'SEX'
    return code


def _direct_rental_history(conn, d, p, pi):
    if (d['document_type'] != 'INVOICE' or len(d['items']) != 1
            or pi['uom'] != 'month' or not pi['gl_account'].startswith('621')
            or d['items'][0].get('receipt_ref') or d['items'][0].get('quantity_milli') != 1000
            or d['items'][0].get('unit_price') != pi['unit_price'] or p['currency'] != d['currency']):
        return []
    history = conn.execute("""SELECT doc_id, issue_date, po_refs, journal_entry FROM ap_invoices
        WHERE vendor=? AND company=? AND currency=? AND net=? AND kind='invoice'
        AND issue_date<? AND decision IN ('POST','POST_PAYMENT_BLOCK') ORDER BY issue_date DESC""",
        (p['vendor'], p['company'], p['currency'], d['net'], d['invoice_date'])).fetchall()
    months = {}
    for doc, day, refs, entry in history:
        if _json(refs, []) != [p['id']]:
            continue
        lines = conn.execute("SELECT account, cost_center, wbs FROM je_line WHERE entry_id=? AND company=?",
                             (entry, p['company'])).fetchall()
        costs = {tuple(l) for l in lines if l[0].startswith(('6', '2'))}
        if any(l[0] == '40090000' for l in lines) or costs != {(pi['gl_account'], pi['cost_center'], pi['wbs'])}:
            continue
        months.setdefault(day[:7], doc)
        if len(months) == 2:
            # ponytail: two matching monthly direct-expense precedents only;
            # use explicit receipt requirements from the contract when supplied.
            return list(months.values())
    return []


def _coding(conn, d, vendor, pos, receipts, docs=()):
    deposit = d['document_type'] == 'DOWN_PAYMENT_REQUEST'
    credit = d['document_type'] == 'CREDIT_NOTE'
    period = (d.get('period_end') or d['invoice_date'])[:7]
    if credit and d.get('credit_reference'):
        originals = [o for o in docs if o['vendor_id'] == d['vendor_id'] and o['company'] == d['company']
                     and norm_num(o['invoice_number']) == norm_num(d['credit_reference'])
                     and o['document_type'] == 'INVOICE']
        if len(originals) == 1:
            original = _coding(conn, originals[0], vendor, pos, receipts, docs)
            objects = {(l['account'], l['cost_center'], l['wbs'], l['tax_code']) for l in original}
            if len(objects) == 1:
                account, cc, wbs, tax = objects.pop()
                return [dict(amount=d['net'], account=account, cost_center=cc, wbs=wbs, tax_code=tax, po=None, po_item=None)]
            raise ValueError('ACCOUNTING_EVIDENCE_AMBIGUOUS')
    out = []
    for item in d['items'] or ([dict(description=d['text'], amount=d['net'], po=None, receipt_ref=None)] if deposit else []):
        grs = [g for g in receipts if g['vendor'] == vendor['id'] and g['reference'] == item.get('receipt_ref')] if item.get('receipt_ref') and not credit else []
        if item.get('receipt_ref') and not grs and not credit and (vendor['po_required'] or item.get('po') or d['po_refs']):
            raise ValueError('QTY_NOT_RECEIVED')
        po_ids = [item['po']] if item.get('po') else d['po_refs']
        candidates = [(p, pi) for p in pos.values() for pi in _json(p['items'], [])
                      if p['vendor'] == vendor['id'] and p['created_on'] <= d['invoice_date']
                      and (p['id'] in po_ids if po_ids else
                           any(g['po'] == p['id'] and g['po_item'] == pi['item'] for g in grs))]
        if grs:
            received_candidates = [(p, pi) for p in pos.values() for pi in _json(p['items'], [])
                                   if p['vendor'] == vendor['id'] and p['created_on'] <= d['invoice_date']
                                   and any(g['po'] == p['id'] and g['po_item'] == pi['item'] for g in grs)]
            candidates = [(p, pi) for p, pi in candidates if any(g['po'] == p['id'] and g['po_item'] == pi['item'] for g in grs)]
            if not candidates and po_ids and all(
                    n in pos and pos[n]['vendor'] == vendor['id'] and pos[n]['company'] == d['company']
                    and pos[n]['currency'] == d['currency'] for n in po_ids):
                candidates = received_candidates
        if not candidates and not credit and not po_ids and not item.get('receipt_ref'):
            candidates = [(p, pi) for p in pos.values() for pi in _json(p['items'], [])
                          if p['vendor'] == vendor['id'] and p['company'] == d['company']
                          and p['created_on'] <= d['invoice_date']
                          and fold(pi['description']) in fold(item['description'])]
            with_receipt = [(p, pi) for p, pi in candidates if any(
                g['po'] == p['id'] and g['po_item'] == pi['item']
                and g['posting_date'][:7] == period for g in receipts)]
            if with_receipt:
                candidates = with_receipt
            elif not vendor['po_required']:
                candidates = []
            same_price = [(p, pi) for p, pi in candidates if item.get('unit_price') == pi['unit_price']]
            if same_price:
                candidates = same_price
            if candidates:
                latest = max(p['created_on'] for p, _ in candidates)
                candidates = [(p, pi) for p, pi in candidates if p['created_on'] == latest]
        if len(candidates) > 1:
            exact = [(p, pi) for p, pi in candidates if
                     fold(pi['description']) in fold(item['description'])
                     or re.search(r'\b' + re.escape(pi['material']) + r'\b', item['description'])]
            candidates = exact
        if len(candidates) == 1 and not credit:
            p, pi = candidates[0]
            if p['company'] != d['company']:
                raise ValueError('WRONG_ADDRESSEE')
            if p['currency'] != d['currency']:
                raise ValueError('PO_CURRENCY_MISMATCH')
            if po_ids and p['id'] not in po_ids:
                d.setdefault('po_evidence', []).append(dict(method='DELIVERY_REFERENCE', declared=po_ids,
                    resolved=p['id'], po_item=pi['item'], receipt_ref=item['receipt_ref'],
                    goods_receipts=[g['id'] for g in grs if g['po'] == p['id'] and g['po_item'] == pi['item']]))
            code = pi['tax_code']
            line = dict(amount=item['amount'], account='40700000' if deposit else pi['gl_account'],
                        cost_center=pi['cost_center'], wbs=pi['wbs'], tax_code=code,
                        po=p['id'], po_item=pi['item'])
            if not deposit:
                if not grs:
                    grs = [g for g in receipts if g['po'] == p['id'] and g['po_item'] == pi['item']
                           and g['posting_date'][:7] == period]
                grs = [g for g in grs if g['po'] == p['id'] and g['po_item'] == pi['item']]
                qty = item.get('quantity_milli')
                received = sum(g['quantity_milli'] for g in grs)
                history = _direct_rental_history(conn, d, p, pi) if not grs else []
                if (not grs or qty is None or received < qty) and not history:
                    raise ValueError('QTY_NOT_RECEIVED')
                base = _round(Decimal(qty) * pi['unit_price'] / 1000)
                variance = item['amount'] - base
                if Decimal(variance) * _fx(conn, d['currency'], 'EUR', d['invoice_date']) > 15000 or variance > abs(base) * Decimal('.02'):
                    raise ValueError('PRICE_VARIANCE')
                if history:
                    d.setdefault('po_evidence', []).append(dict(method='DIRECT_RECURRING_RENTAL',
                        resolved=p['id'], po_item=pi['item'], history_doc_ids=history))
                else:
                    line['grir'] = base
            out.append(line)
        elif po_ids or item.get('receipt_ref') and vendor['po_required'] and not credit:
            raise ValueError('QTY_NOT_RECEIVED')
        elif vendor['po_required'] and not credit:
            raise ValueError('ACCOUNTING_EVIDENCE_MISSING')
        else:
            line = _historic_cost(conn, d, vendor, docs)
            line.update(amount=item['amount'], po=None, po_item=None)
            line['tax_code'] = _item_tax(item, line['tax_code'])
            out.append(line)
    if not out:
        raise ValueError('EXTRACTION_REVIEW_REQUIRED')
    if any(l['account'] not in ('40700000',) and bool(l['cost_center']) == bool(l['wbs']) for l in out):
        raise ValueError('ACCOUNTING_EVIDENCE_MISSING')
    return out


def _notice_date(text, pattern):
    found = re.search(pattern + r'\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})', text, re.I)
    return date_iso(found[1]) if found else None


def _payment_checks(d, vendor, notices):
    if not d['invoice_date']:
        return None, False  # _decide publishes an extraction-review HOLD.
    alt = _json(vendor.get('alternative_payee'), {})
    payee = {'type': 'FACTOR'} if alt and alt['from_date'] <= d['invoice_date'] else None
    if any(g['from_date'] < d['metadata']['received_at'][:10] for g in _json(vendor.get('garnishments'), [])) and not payee:
        payee = {'type': 'AEAT_EMBARGO'}
    approved = {b.get('iban') for b in _json(vendor.get('bank_history'), []) if d['invoice_date'] <= b.get('valid_to', '')}
    approved.add(_json(vendor['bank'], {}).get('iban'))
    if payee and alt:
        approved.add(alt.get('iban'))
    domain = parseaddr(vendor['email'])[1].casefold().split('@')[-1]
    for n in notices:
        if n['vendor_id'] != vendor['id']:
            continue
        if n['document_type'] == 'FACTORING_NOTICE':
            effective = _notice_date(n['text'], r'a partir (?:del|de)')
            if effective and effective <= d['invoice_date']:
                payee = {'type': 'FACTOR'}
                approved.add(n['iban'])
        if n['document_type'] == 'TAX_GARNISHMENT_ORDER' and n['metadata']['received_at'] < d['metadata']['received_at'] and not payee:
            payee = {'type': 'AEAT_EMBARGO'}
        if n['document_type'] == 'BANK_DETAILS_CHANGE':
            effective = _notice_date(n['text'], r'a partir (?:del|de)')
            sender = parseaddr(n['metadata'].get('from', ''))[1].casefold().split('@')[-1]
            if effective and effective <= d['invoice_date'] and 'firmado' in fold(n['text']) and 'certificado' in fold(n['text']) and sender == domain:
                approved.add(n['iban'])
    sender = parseaddr(d['metadata'].get('from', ''))[1].casefold()
    fraud = (d['iban'] and d['iban'] not in approved
             or d['metadata'].get('channel') == 'email' and sender and sender.split('@')[-1] != domain)
    return payee, bool(fraud)


def _decide(conn, d, vendor, company, pos, receipts, notices, taxes):
    if d['document_type'] in ACTIONS:
        return 'NOT_INVOICE', [], [], None, None
    if any(i.startswith(('NO_READABLE_DOCUMENT', 'OCR_REQUIRED', 'OCR_FAILED', 'PARSE_ERROR', 'MISSING_ATTACHMENT')) for i in d['issues']):
        return 'HOLD', ['EXTRACTION_REVIEW_REQUIRED'], [], None, None
    if not d['buyer_tax_id']:
        return 'REJECT', ['MANDATORY_FIELD_MISSING'], [], None, None
    if not company:
        return 'REJECT', ['WRONG_ADDRESSEE'], [], None, None
    if d['source_company'] != d['company']:
        return 'REJECT', ['WRONG_ADDRESSEE'], [], None, None
    if not vendor:
        return 'HOLD', ['VENDOR_NOT_IN_MASTER'], [], None, None
    if not all(d.get(k) for k in ('invoice_number', 'invoice_date', 'currency')) or not all(type(d.get(k)) is int for k in AMOUNTS):
        return 'HOLD', ['EXTRACTION_REVIEW_REQUIRED'], [], None, None
    coding, issue = [], None
    try:
        coding = _coding(conn, d, vendor, pos, receipts, notices)
    except ValueError as exc:
        issue = str(exc)
    if issue == 'WRONG_ADDRESSEE':
        return 'REJECT', [issue], [], None, None
    if d['company'] not in _json(vendor['companies'], []):
        return 'REJECT', ['WRONG_ADDRESSEE'], [], None, None
    code = vendor['default_tax_code']
    fallback = [dict(amount=i['amount'], tax_code=_item_tax(i, code)) for i in d['items']]
    tax_lines = coding or fallback or [dict(amount=d['net'], tax_code=code)]
    if d['document_type'] == 'DOWN_PAYMENT_REQUEST':
        tax_lines = [dict(amount=d['net'], tax_code='SEX')]
    if code == 'SISP' and d['tax']:
        return 'REJECT', ['ISP_NOT_APPLIED'], [], None, None
    if all(type(d.get(k)) is int for k in AMOUNTS):
        expected_tax = sum(_round(Decimal(l['amount']) * taxes['tax_codes'][l['tax_code']]['rate'] / 10000)
                           for l in tax_lines if taxes['tax_codes'][l['tax_code']]['kind'] == 'input')
        if abs(expected_tax - d['tax']) > max(2, len(tax_lines)):
            return 'REJECT', ['VAT_RATE_INCORRECT'], [], None, None
        if vendor['withholding'] and not d['withholding']:
            return 'REJECT', ['WITHHOLDING_MISSING'], [], None, None
        if d['gross'] != d['net'] + d['tax'] or d['payable'] != d['gross'] - d['withholding'] - d['retention']:
            return 'REJECT', ['ARITHMETIC_ERROR'], [], None, None
    else:
        return 'HOLD', ['EXTRACTION_REVIEW_REQUIRED'], [], None, None
    current = d.get('current_certification')
    if current is None:
        current = _amount(r'^Importe de esta certificación', d['text'])
    if current is not None and abs(d['net']) > abs(current) + 2:
        return 'REJECT', ['CERTIFICATION_CUMULATIVE_BILLED'], [], None, None
    if company['country'] == 'MX' and 'XML_PDF_MISMATCH' in d['issues']:
        return 'REJECT', ['CFDI_MISMATCH'], [], None, None
    payee, fraud = _payment_checks(d, vendor, notices)
    if fraud:
        return 'HOLD', ['BANK_DETAILS_CHANGED'], [], payee, None
    if d['issues']:
        return 'HOLD', ['EXTRACTION_REVIEW_REQUIRED'], [], payee, None
    if issue:
        return 'HOLD', [issue], [], payee, None
    block = None
    if any(l['tax_code'] == 'SISP' for l in coding) and d['document_type'] == 'INVOICE':
        certificates = [(r['issued_on'], r['valid_until']) for r in _rows(conn, 'contractor_certificates') if r['vendor'] == vendor['id']]
        for n in notices:
            if n['document_type'] == 'CONTRACTOR_TAX_CERTIFICATE' and n['vendor_id'] == vendor['id']:
                issued = _notice_date(n['text'], r'Fecha de emisión:')
                until = _notice_date(n['text'], r'hasta')
                if issued and until:
                    certificates.append((issued, until))
        if not any(start <= d['invoice_date'] <= end for start, end in certificates):
            block = 'CONTRACTOR_CERTIFICATE_EXPIRED'
    return ('POST_PAYMENT_BLOCK' if block else 'POST'), ([block] if block else []), coding, payee, block


def _journal(d, vendor, coding, taxes, fx):
    lines = []
    def line(account, amount, **extra):
        if amount:
            lines.append(dict(account=account, debit=max(amount, 0), credit=max(-amount, 0), **extra))
    for l in coding:
        amount = _round(Decimal(l['amount']) * fx)
        if l['account'] == '40700000':
            line('40700000', amount, partner=vendor['id'], assignment=d['invoice_number'])
        elif 'grir' in l:
            base = _round(Decimal(l['grir']) * fx)
            line('40090000', base, partner=vendor['id'], assignment=f"{l['po']}/{l['po_item']}")
            line(l['account'], amount - base, cost_center=l['cost_center'], wbs=l['wbs'])
        else:
            line(l['account'], amount, cost_center=l['cost_center'], wbs=l['wbs'])
        tax = taxes['tax_codes'][l['tax_code']]
        if tax['kind'] == 'reverse':
            quota = _round(Decimal(l['amount']) * tax['rate'] / 10000 * fx)
            line('47210000', quota)
            line('47710000', -quota)
    line('47200000', d['tax'])
    line('47510000', -d['withholding'])
    line('40000900', -d['retention'], partner=vendor['id'])
    payable = sum(l['debit'] - l['credit'] for l in lines)
    line(vendor['reconciliation_account'], -payable, partner=vendor['id'], assignment=d['invoice_number'])
    d['payable'] = payable
    return make_je(d['company'], lines)


def run(conn):
    conn.execute('CREATE INDEX IF NOT EXISTS ix_ap_history_lines ON je_line(entry_id, company, account)')
    phase = _phase(conn)
    docs = extract_phase(conn, phase)
    recipients = _bank_recipients(conn, phase)
    vendors = {v['id']: v for v in _rows(conn, 'vendors')}
    companies = {c['code']: c for c in _rows(conn, 'companies')}
    pos = {p['id']: p for p in _rows(conn, 'purchase_orders')}
    month = db.get_json(conn, 'tasks/close')['month']
    receipts = [g for g in _rows(conn, 'goods_receipts') if g['posting_date'][:7] <= month]
    taxes = db.get_json(conn, 'erp/tax_codes')
    seen = {}
    for h in sorted(_rows(conn, 'ap_invoices'), key=lambda h: (h['received_on'], h['doc_id'])):
        if h['decision'] in ('POST', 'POST_PAYMENT_BLOCK', 'HOLD'):
            seen.setdefault(_key(h['vendor'], h['number'], h['currency'], h['gross'], h['company']), (h['doc_id'], h['number']))
    originals = {}
    # Exact copies have one stable economic representative. Synthetic resend
    # timestamps may precede their originals; retain an explicit audit warning.
    for d in sorted(docs, key=lambda d: (bool(re.match(r'^F[-/\s]', d['invoice_number'] or '', re.I)), d['doc_id'])):
        if d['vendor_id'] and d['invoice_number'] and d['gross'] is not None:
            key = _key(d['vendor_id'], d['invoice_number'], d['currency'], d['gross'], d['company'])
            originals.setdefault((key, _fingerprint(d)), (d['doc_id'], _number(d['invoice_number']), d['metadata']['received_at']))
    results = []
    for source in sorted(docs, key=lambda d: (d['metadata']['received_at'], d['doc_id'])):
        d = deepcopy(source)
        d.update(source_invoice_number=d['invoice_number'], source_currency=d['currency'], source_company=d['company'],
                 source_amounts={k: d.get(k) for k in AMOUNTS}, journal_entry=None,
                 duplicate_of=None, payee=None, payment_block=None, action=None, lines=[])
        if 'deposit request' in fold(d['text']):
            d['document_type'] = 'DOWN_PAYMENT_REQUEST'
            d['issues'] = [i for i in d['issues'] if i != 'ITEM_SUM_MISMATCH']
        if d['document_type'] == 'CREDIT_NOTE':
            for k in AMOUNTS:
                if d[k] is not None:
                    d[k] = -abs(d[k])
            for item in d['items']:
                item['amount'] = -abs(item['amount'])
        evidence = recipients.get((d['vendor_id'], norm_num(_number(d['invoice_number'])), d['currency'], d['payable']), [])
        recipient_companies = {e['company'] for e in evidence}
        if len(recipient_companies) == 1:
            d.update(company=next(iter(recipient_companies)), bank_evidence=evidence)
        vendor, company = vendors.get(d['vendor_id']), companies.get(d['company'])
        key = _key(d['vendor_id'], d['invoice_number'], d['currency'], source['gross'], d['company'])
        first = seen.get(key) or originals.get((key, _fingerprint(source))) if d['vendor_id'] and d['invoice_number'] and d['gross'] is not None and d['company'] else None
        if d['source_company'] != d['company']:
            first = None
        if first and vendor and d['document_type'] not in ACTIONS and _payment_checks(d, vendor, docs)[1]:
            first = None
        if first and first[0] != d['doc_id']:
            d.update(decision='DUPLICATE', reasons=['DUPLICATE'], duplicate_of=first[0], invoice_number=first[1])
            if len(first) > 2 and first[2] > d['metadata']['received_at']:
                d['warnings'] = ['RECEIPT_ORDER_CONFLICT']
            coding = []
        else:
            decision, reasons, coding, payee, block = _decide(conn, d, vendor, company, pos, receipts, docs, taxes)
            d.update(decision=decision, reasons=reasons, payee=payee, payment_block=block)
            if decision == 'NOT_INVOICE':
                d['action'] = ACTIONS[d['document_type']]
        if d['decision'] == 'REJECT' and 'ARITHMETIC_ERROR' in d['reasons']:
            d['gross'] = d['net'] + d['tax']
            d['payable'] = d['gross'] - d['withholding'] - d['retention']
        fx = Decimal(1)
        if company and d['currency'] and d['invoice_date']:
            try:
                fx = _fx(conn, d['currency'], company['currency'], d['invoice_date'])
            except ValueError as exc:
                if d['decision'] in ('POST', 'POST_PAYMENT_BLOCK'):
                    d.update(decision='HOLD', reasons=[str(exc)])
            else:
                for k in AMOUNTS:
                    if d[k] is not None:
                        d[k] = _round(Decimal(d[k]) * fx)
                d['currency'] = company['currency']
        if d['decision'] in ('POST', 'POST_PAYMENT_BLOCK'):
            d['journal_entry'] = _journal(d, vendor, coding, taxes, fx)
            d['lines'] = [{**{k: v for k, v in l.items() if k != 'grir'}, 'amount': _round(Decimal(l['amount']) * fx)} for l in coding]
        d['status'] = 'REVIEW_REQUIRED' if d['decision'] == 'HOLD' and any(r.endswith(('REQUIRED', 'MISSING', 'AMBIGUOUS')) and r not in ('WITHHOLDING_MISSING',) for r in d['reasons']) else 'DECIDED'
        event, je = 'ap:' + d['doc_id'], d['journal_entry']
        existing = conn.execute('SELECT owner, task, company, lines FROM proposed_je WHERE event_key=?', (event,)).fetchone()
        if existing and (je is None or existing[:3] != ('P1', 'ap', je['company']) or json.loads(existing[3]) != je['lines']):
            raise ValueError('AP journal conflict: ' + event)
        if je and not existing:
            propose(conn, event, 'P1', 'ap', je)
        conn.execute("""UPDATE ap_result SET company=?, vendor_id=?, invoice_number=?, invoice_norm=?,
            invoice_date=?, payable=?, currency=?, decision=?, data=? WHERE doc_id=?""",
            (d['company'], d['vendor_id'], d['invoice_number'], norm_num(d['invoice_number']) if d['invoice_number'] else None,
             d['invoice_date'], d['payable'], d['currency'], d['decision'], json.dumps(d, ensure_ascii=False), d['doc_id']))
        results.append(d)
    return results
