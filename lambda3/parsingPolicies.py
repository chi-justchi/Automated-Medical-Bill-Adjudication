import os
import re
import json
import base64
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

# ---------- Logging ----------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------- AWS Clients ----------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
s3 = boto3.client("s3")
bedrock_rt = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# ---------- Constants ----------
PARSED_PREFIX = "parsed/"
MAX_TOKENS = 3000

JSON_POLICY_PROMPT = """
You are an expert insurance policy parser. Extract key coverage details from the attached PDF. Return JSON with this structure:
{
  "schema_version": "policy.v1",
  "policy_id": "ShieldPlus_USF_2025-2026",
  "plan": {
    "name": "Shield Plus",
    "policy_number": "string|null",
    "policy_year": "2025–2026",
    "manager": "ISO",
    "underwriter": "BHSI (Bermuda) reinsured by BHSI",
    "network": {"name": "Aetna", "url": "string|null"}
  },
  "limits": {
    "medical_expense_per_injury_or_sickness_usd": 250000,
    "evacuation_usd": 50000,
    "repatriation_usd": 25000,
    "source_page": "p.3"
  },
  "deductibles": {
    "student_health_center_usd": 0,
    "elsewhere_usd": 100,
    "policy_year_max_usd": 100,
    "source_page": "p.3"
  },
  "coinsurance": {
    "in_network": "80%",
    "out_of_network": "60%",
    "source_page": "p.3"
  },
  "copays": {
    "primary_care_usd": 20,
    "specialist_usd": 35,
    "urgent_care_usd": 50,
    "emergency_room_usd": 200,
    "source_page": "p.3"
  },
  "coverage_highlights": {
    "maternity": "Covered per policy",
    "preexisting_wait_months": 12,
    "wellness_preventive": "As stated",
    "source_page": "p.3"
  },
  "rates": [
    {"age_range": "18–24", "monthly_usd": 123},
    {"age_range": "25–40", "monthly_usd": 145},
    {"age_range": "Dependent", "monthly_usd": 200}
  ],
  "eligibility": "F-1/J-1 full-time, etc.",
  "exclusions": ["..."],
  "claims": {
    "mail_to": "…",
    "deadline": "90 days",
    "phone": "…",
    "email": "…",
    "source_page": "p.X"
  },
  "refund_policy": {
    "conditions": ["…"],
    "processing_fee_usd": 50,
    "source_page": "p.X"
  },
  "assistance_services": {
    "provider": "On Call International",
    "phones": ["…"],
    "email": "…",
    "source_page": "p.X"
  },
  "artifacts": {
    "pdf_s3": "s3://…/raw/…/policy.pdf",
    "text_jsonl_s3": "s3://…/text/…/pages.jsonl"
  }
}
Rules:
- Go through EACH page systematically (page 1, 2, 3, etc.)
- Extract EVERY line item - medications, procedures, supplies, services, etc.
- Count and report how many pages you processed
- Count and report total number of line items extracted
- Amounts MUST be numbers (no $ or commas)
- If a field is missing, set it to null
- Output MUST be valid JSON only - no markdown, no commentary
"""

# ---------- Helpers ----------


def _extract_json(text: str) -> Any:
    """
    Extract a JSON object or array from a model response.
    Tries in order:
      1) ```json ... ``` fenced block
      2) ``` ... ``` fenced block
      3) First balanced {...} or [...]
    """
    if not text or not text.strip():
        raise ValueError("Model returned empty text; no JSON to parse.")

    # 1) ```json ... ```
    m = re.search(
        r"```json\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        return json.loads(m.group(1))

    # 2) ``` ... ```
    m = re.search(r"```\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text)
    if m:
        return json.loads(m.group(1))

    # 3) First balanced {...} or [...]
    def _balanced_slice(s: str, open_ch: str, close_ch: str) -> Optional[str]:
        start = s.find(open_ch)
        if start < 0:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        return s[start : i + 1]
        return None

    for o, c in (("{", "}"), ("[", "]")):
        cand = _balanced_slice(text, o, c)
        if cand:
            return json.loads(cand)

    raise ValueError("Could not locate JSON block in model output.")


# ---------- Core ----------


def parse_policy_pdf(bucket: str, key: str, model_id: str) -> str:
    """
    Parse a policy PDF from S3 using an Amazon Bedrock model and save extracted JSON back to S3.

    Args:
        bucket: S3 bucket name.
        key: S3 object key for the PDF.
        model_id: Bedrock model ID.

    Returns:
        The S3 key where the parsed JSON was saved.
    """
    try:
        logger.info("Parsing policy PDF: s3://%s/%s", bucket, key)

        # Fetch PDF from S3
        obj = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = obj["Body"].read()

        # Encode to base64 for Bedrock document input
        b64 = base64.b64encode(file_bytes).decode("utf-8")

        # Build Bedrock request
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": JSON_POLICY_PROMPT},
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                ],
            }
        ]

        payload: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
        }

        logger.info("Invoking Bedrock model: %s", model_id)
        resp = bedrock_rt.invoke_model(modelId=model_id, body=json.dumps(payload))

        # Bedrock returns a StreamingBody under resp["body"]
        raw = resp["body"].read()
        body = json.loads(raw)

        # Extract text from response content
        content = body.get("content", [])
        text_blocks = [c.get("text", "") for c in content if c.get("type") == "text"]
        out_text = "\n".join(t for t in text_blocks if t)

        logger.info("Model response length: %d", len(out_text))

        # Parse JSON
        parsed_data = _extract_json(out_text)

        # Add metadata
        artifacts = parsed_data.get("artifacts", {}) if isinstance(parsed_data, dict) else {}
        artifacts.update(
            {
                "pdf_s3": f"s3://{bucket}/{key}",
                "parsed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
        )
        if isinstance(parsed_data, dict):
            parsed_data["artifacts"] = artifacts

        # Save to S3
        filename = os.path.basename(key).rsplit(".", 1)[0] + ".json"
        parsed_key = f"{PARSED_PREFIX}policies/{filename}"

        # this function saves the parsed data to s3
        s3.put_object(
            Bucket=bucket,
            Key=parsed_key,
            Body=json.dumps(parsed_data, indent=2),
            ContentType="application/json",
        )

        logger.info("Saved parsed policy to s3://%s/%s", bucket, parsed_key)
        return parsed_key
    
    # except block to handle errors
    except Exception as e:
        logger.error("Failed to parse policy PDF: %s", e, exc_info=True)
        raise
