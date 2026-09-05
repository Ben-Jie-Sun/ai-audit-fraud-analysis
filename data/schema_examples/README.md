# Transaction schema examples

These workbooks are judge/tester-facing examples for the transaction-ledger path.

## 01_minimum_required_sample.xlsx
Smallest supported schema for ML analysis:
- `transaction_id`
- `date`
- `amount`
- `employee_id` **or** `employee_name`

The workbook intentionally omits vendor/category/location/etc. The audit engine should still run, but dependent fraud signals are reported as skipped.

## 02_medium_context_typo_sample.xlsx
A richer schema with deliberate header spelling mistakes to demonstrate conservative auto-recognition:
- `Transacton ID` -> `transaction_id`
- `Employe Name` -> `employee_name`
- `Merchent` -> `vendor`
- `Transaction Date` -> `date` (alias)
- `Expense Category` -> `category` (alias)
- `Value` -> `amount` (alias)

It also includes department and manager context while omitting location/payment method, demonstrating partial recommended-context coverage.

## Requirement policy
Minimum fields are required to start the ML pipeline. Recommended fields improve contextual fraud checks but are not mandatory. Missing recommended fields disable only their dependent signals; the UI/report shows what was skipped.
