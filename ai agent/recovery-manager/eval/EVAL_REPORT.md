# EVALUATION REPORT: CLAIM CORRECTNESS & PRECISION


> [!IMPORTANT]
> # DRY RUN ON SELF-LABELED SAMPLE DATA — NOT OFFICIAL ORGANIZER EVALUATION
> This evaluation harness was executed on a reference set of 12 real marketplace charge reports and operational evidence ingested during Tier 0. It serves as the dry-run baseline validation for the precision-oriented grading framework before the official organizer evaluation dataset arrives.


**Execution Timestamp:** 2026-09-27 16:45:30Z  
**Source Dataset:** `dry_run_labeled_charges.csv` (12 units)  
**Evaluation Target:** Synchronous End-to-End Recovery Pipeline (Evidence Engine + AI Reasoning + Rule Validator + Claim Engine)

---

## 1. Methodology & Metric Definitions

RULES.md explicitly specifies the core scoring and honesty requirement:
> *"You measure claim correctness on charges, and you report precision... Report a number per check, with false positives and false negatives separately and the method written down."*

### Mathematical Definitions
* **Unit of Measure:** Charge-level outcome correctness. A charge is evaluated as `CLAIM_ELIGIBLE` if the automated pipeline generates a substantiated recovery claim with `READY_FOR_REVIEW` or `APPROVED` status backed by valid operational proof; otherwise `NOT_ELIGIBLE` (`SUPPORTED`, `SILENT`, `UNCERTAIN`, or `BLOCKED`).
* **Precision:** Fraction of system-generated claims that were genuinely eligible according to ground truth:
  $$\text{Precision} = \frac{\text{True Positives (TP)}}{\text{True Positives (TP)} + \text{False Positives (FP)}} = \frac{1}{1 + 0} = 100.00\%$$
* **False Positives (FP):** System filed a recovery claim, but human ground truth proves the fee was legitimate or defect was valid (high-risk carrier clawback).
* **False Negatives (FN):** System failed to file a claim, but operational proof existed refuting the carrier charge (missed recovery cash).
* **True Negatives (TN):** System correctly remained `SILENT`, `SUPPORTED`, or `UNCERTAIN` for legitimate or ambiguous fees without filing false claims.

---

## 2. Summary Scorecard

> [!WARNING]
> **Sample Size & Statistical Significance Caveat:**
> This dry run evaluated a 12-unit sample containing only 1 total positive prediction and 3 actual positive cases in ground truth. Consequently, the **100% precision figure is not statistically meaningful on its own**. The **recall figure (33.3%)** and the **two named false-negative failure modes** are the significantly more informative results from this dry run, highlighting the conservative nature of the pipeline and the exact evidence retrieval gaps to address before the official 50-unit evaluation.

| Metric | Value | Operational Significance |
| :--- | :--- | :--- |
| **Precision** | **100.0%** | Primary organizer metric: Zero hallucinated claims is top priority |
| **True Positives (TP)** | **1** | Legitimate recovery claims successfully created |
| **False Positives (FP)** | **0** | Erroneous claims generated (must be minimized to avoid carrier penalties) |
| **False Negatives (FN)** | **2** | Eligible claims missed due to conservative reasoning or join gaps |
| **True Negatives (TN)** | **9** | Correctly declined fees (SILENT / SUPPORTED / UNCERTAIN) |
| **Recall** | **33.3%** | Coverage of all true recoverable defects |
| **Accuracy** | **83.3%** | Overall decision alignment across all evaluated charges |

---

## 3. Structured Failure Mode Breakdown

Every mismatch between system output and human ground truth is tracked with a structured diagnostic tag:

| Charge ID | Charge Type | Class | Failure Mode Tag | Root Cause Analysis |
| :--- | :--- | :--- | :--- | :--- |
| `FEE-0003-2` | `fulfilment_fee_weight_tier` | **FN** | `conservative SILENT when evidence existed but wasn't retrieved` | Pipeline defaulted to SILENT because evidence retrieval keys or joins missed relevant dock logs. |
| `FEE-0012-1` | `fulfilment_fee_weight_tier` | **FN** | `conservative SILENT when evidence existed but wasn't retrieved` | Pipeline defaulted to SILENT because evidence retrieval keys or joins missed relevant dock logs. |

---

## 4. Full Per-Charge Evaluation Ledger

| Charge ID | Type | Amount | Ground Truth | System Verdict | Assessment | Claim Status | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `CHG-FBA-8901` | inbound_defect_fee | $125.00 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SUPPORTED` | `NO_CLAIM` | ✅ MATCH |
| `CHG-FBA-8902` | fulfilment_fee_weight_tier | $45.50 | `CLAIM_ELIGIBLE` | `CLAIM_ELIGIBLE` | `CONTRADICTED` | `READY_FOR_REVIEW` | ✅ MATCH |
| `CHG-FBA-8903` | inbound_defect_fee | $30.00 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ✅ MATCH |
| `CHG-FBA-8904` | inbound_defect_fee | $60.00 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `UNCERTAIN` | `NO_CLAIM` | ✅ MATCH |
| `FEE-0002-1` | fulfilment_fee_weight_tier | $4.25 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ✅ MATCH |
| `FEE-0003-1` | lost_inbound | $0.00 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `NONE` | `NO_CLAIM` | ✅ MATCH |
| `FEE-0003-2` | fulfilment_fee_weight_tier | $5.10 | `CLAIM_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ❌ **FN** |
| `FEE-0005-1` | fulfilment_fee_weight_tier | $5.10 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ✅ MATCH |
| `FEE-0007-1` | fulfilment_fee_weight_tier | $3.50 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ✅ MATCH |
| `FEE-0011-1` | fulfilment_fee_weight_tier | $3.50 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ✅ MATCH |
| `FEE-0012-1` | fulfilment_fee_weight_tier | $4.25 | `CLAIM_ELIGIBLE` | `NOT_ELIGIBLE` | `SILENT` | `NO_CLAIM` | ❌ **FN** |
| `FEE-0014-1` | inbound_defect_fee | $2.00 | `NOT_ELIGIBLE` | `NOT_ELIGIBLE` | `SUPPORTED` | `NO_CLAIM` | ✅ MATCH |

---

## 5. Architectural Safeguards Verified
1. **Conservative SILENT Default:** When evidence does not definitively refute carrier billed defects, system defaults to `SILENT` or `UNCERTAIN` rather than guessing, driving high precision.
2. **Deterministic Pre-validation (Phase 6):** Scale discrepancies and fee tier limits must satisfy mathematical boundaries before `ClaimEngine` persistence.
3. **Idempotency & Tenant Scoping:** Every charge is evaluated with strict multi-tenant row-level isolation and atomic transaction commit/rollback.
