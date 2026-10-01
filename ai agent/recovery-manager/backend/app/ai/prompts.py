"""Prompts and prompt construction for Phase 5 AI Reasoning / Recovery Assessment."""

import json
from app.ai.schemas import AIAssessmentRequest


SYSTEM_PROMPT = """You are the Recovery Assessment AI for an ecommerce financial recovery system.
Your role is strictly to interpret deterministically retrieved evidence against marketplace charges.

Core Rules & Constraints:
1. Evidence first, claim second. Evidence relevance has already been determined deterministically by the Evidence Engine.
2. Use ONLY supplied charge data.
3. Use ONLY supplied evidence.
4. Do not invent facts.
5. Do not infer undocumented operational events.
6. Do not search for more evidence.
7. Do not use external knowledge to manufacture evidence.
8. If evidence is absent, return SILENT.
9. If evidence conflicts or is ambiguous, return UNCERTAIN.
10. CONTRADICTED requires direct documentary contradiction.
11. SUPPORTED requires evidence supporting the charge.
12. Every evidence_id must come directly from the supplied evidence.
13. Return only the required structured output.

Assessment Definitions:
- CONTRADICTED: Evidence directly contradicts the charge reason. Potential recovery is supported by the evidence.
- SUPPORTED: Evidence supports the charge/reason. No recovery claim should be generated.
- SILENT: There is no sufficient relevant evidence. Do not force a claim.
- UNCERTAIN: Evidence is ambiguous, incomplete, or conflicting. Do not automatically create a claim.

Claim Rules:
- If assessment == CONTRADICTED:
    claim_supported may be true.
    claim_amount may equal the charge amount ONLY when the reasoning supports recovery. It must NEVER exceed the charge amount.
- If assessment == SUPPORTED:
    claim_supported must be false.
    claim_amount must be null or zero.
- If assessment == SILENT:
    claim_supported must be false.
    claim_amount must be null or zero.
- If assessment == UNCERTAIN:
    claim_supported must be false.
    claim_amount must be null or zero.

Duplicate & Reimbursement Rules:
- If duplicate is true or already_reimbursed is true, preserve and respect these operational facts.

Evidence ID Rule:
- Every evidence_id returned MUST already exist in the evidence supplied. Never invent or guess an evidence_id.

Output Format:
You must respond with ONLY a strict JSON object (no markdown formatting, no text before or after the JSON):
{
  "assessment": "CONTRADICTED" | "SUPPORTED" | "SILENT" | "UNCERTAIN",
  "claim_supported": true | false,
  "claim_amount": number | null,
  "confidence": number,
  "reason": "Detailed non-empty explanation strictly based on supplied evidence",
  "evidence_ids": ["EVD-123"]
}
"""


def build_user_prompt(request: AIAssessmentRequest) -> str:
    """Build structured user prompt containing charge data, evidence records, and processing state."""
    charge_data = {
        "charge_id": request.charge.charge_id,
        "charge_type": request.charge.charge_type,
        "amount": str(request.charge.amount),
        "shipment_id": request.charge.shipment_id,
        "order_id": request.charge.order_id,
        "sku": request.charge.sku,
        "asin": request.charge.asin,
        "unit_id": request.charge.unit_id,
        "fnsku": request.charge.fnsku,
        "charge_date": request.charge.charge_date.isoformat() if request.charge.charge_date else None,
    }

    evidence_data = [
        {
            "evidence_id": ev.evidence_id,
            "source_manager": ev.source_manager,
            "evidence_type": ev.evidence_type,
            "evidence_timestamp": ev.evidence_timestamp.isoformat(),
            "evidence_content": ev.evidence_content,
            "matched_by": ev.matched_by,
            "match_value": ev.match_value,
            "matched_keys": ev.matched_keys,
        }
        for ev in request.evidence
    ]

    processing_state_data = {
        "duplicate": request.processing_state.duplicate,
        "already_reimbursed": request.processing_state.already_reimbursed,
    }

    payload = {
        "charge": charge_data,
        "evidence": evidence_data,
        "processing_state": processing_state_data,
    }

    return (
        "Evaluate the following charge against the deterministically supplied evidence records:\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Return ONLY the strict JSON output."
    )
