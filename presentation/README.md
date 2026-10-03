# Kalmora · five-minute talk

Static six-slide deck in English, one presenter. It follows the data: input → extract → SQLite → clean → decide → results. No framework, no network: open `dist/index.html` in a browser.

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory presentation/dist   # optional
```

Keys: ← → / PageUp PageDown / Space move, Home End jump, `N` speaker notes. The bottom-right pill (timer, notes, full screen) fades out until hovered. Printing gives one slide per page without controls or notes.

| # | Slide | Time |
|---|---|---|
| 1 | The input: 305 documents, 48 statements, 109,537 journal lines → 6 JSONL | 30 s |
| 2 | Extract: pypdf, Facturae/CFDI, local Vision OCR, N43/camt/CSV | 50 s |
| 3 | One SQLite file: task order, `ledger` view, unique `event_key` | 50 s |
| 4 | Four cleaning rules with real cases | 70 s |
| 5 | Decide: rules → Claude (≥ 0.8) → doubt; `make_je` checks; netting example | 60 s |
| 6 | Results: press Play — manim-style animation (`results.js`): total, per-task bars, AP F1 by decision | 40 s |

## Where the numbers come from

`main` at `afe78d5`, `python3 run.py dev` on 2026-10-03: TOTAL 97.62 (ap 0.969, ar_billing/ar_cash/bank_rec/ic 1.000, close 0.856, trial_balance 0.999). `pytest`: 182 pass; the other 6 need the local OCR binary. Row counts from `db/kalmora_dev.db` (`je_line`, `doc_extract`, `proposed_je`). Rule examples: `ap_result` rows API005210, API005227 and `docs/score-gaps.tdd.md`. Update by hand if the pipeline changes.

## Tests

```sh
node --test --experimental-test-coverage --test-coverage-include='presentation/dist/deck.js' --test-coverage-lines=80 --test-coverage-functions=80 --test-coverage-branches=80 presentation/tests/deck.test.cjs
```
