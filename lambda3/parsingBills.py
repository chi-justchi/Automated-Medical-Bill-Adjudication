import os, json, base64, logging, re, uuid, datetime
from typing import Optional, Dict, Any
from decimal import Decimal
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
bedrock_rt = boto3.client(
    "bedrock-runtime",
    region_name=os.environ.get("AWS_REGION", "us-east-2")
)

# ---------- Output bucket for parsed bills ----------
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "chitest02")  # <— new: write here
PARSED_PREFIX = "parsed/"                                     # keep key structure under this prefix

JSON_BILL_PROMPT = """
You are extracting structured data from a medical receipt.

Return ONLY a JSON object matching EXACTLY this schema:

{
  "patient_info": {
    "firstname": string|null,
    "lastname": string|null,
    "age": number|null,
    "phone": string|null,
    "address": string|null,
    "city": string|null,
    "state": string|null,
    "zipcode": string|null
  },
  "hospital_info": {
    "name": string|null,
    "phone": string|null,
    "address": string|null,
    "city": string|null,
    "state": string|null,
    "zipcode": string|null
  },
  "medical_bill_info": {
    "items": [
      {"code": string|null, "description": string|null, "bill": number|null}
    ],
    "subtotal": number|null,
    "discount": number|null,
    "tax_rate_percent": number|null,
    "total_tax": number|null,
    "balance_due": number|null
  }
}

Rules:
- Output MUST be valid JSON only. No backticks, no markdown, no extra commentary.
- Amounts (bill, subtotal, discount, taxes, balance_due) MUST be numbers (no $ or commas).
- If a field is missing on the document, set it to null.
- If a ZIP code appears inside an address, also copy it to zipcode.
- Do not invent data. Be conservative.
- Go through EACH page systematically (page 1, 2, 3, etc.)
- Extract EVERY line item - medications, procedures, supplies, services, etc.
- Count and report how many pages you processed
- Count and report total number of line items extracted
"""

# ---------- JSON Extraction Helper ----------
def _extract_json(text: str):
    if not text or not text.strip():
        raise ValueError("Model returned empty text.")
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"```\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("Model did not return JSON.")
    return json.loads(m.group(0))

def _to_number(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        cleaned = x.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None

def _extract_zip_from_address(addr):
    if not addr or not isinstance(addr, str):
        return None
    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", addr)
    return m.group(0) if m else None

# ---------- Main Function ----------
def parse_bill_pdf(bucket: str, key: str, model_id: str) -> str:
    """
    Parse a bill PDF and save the extracted JSON to S3.
    Returns the S3 key (under parsed/bills/) where the JSON was saved, in OUTPUT_BUCKET.
    """
    try:
        logger.info(f"Parsing bill PDF: s3://{bucket}/{key}")

        # Read PDF from S3
        obj = s3.get_object(Bucket=bucket, Key=key)
        file_bytes = obj["Body"].read()

        b64 = base64.b64encode(file_bytes).decode("utf-8")

        # Build Bedrock messages
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": JSON_BILL_PROMPT},
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64
                    }
                }
            ]
        }]

        # Build Bedrock request payload
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": 4000,
            "temperature": 0
        }

        logger.info(f"Invoking Bedrock model: {model_id}") # log before call
        resp = bedrock_rt.invoke_model(modelId=model_id, body=json.dumps(payload)) # call Bedrock
        body = json.loads(resp["body"].read()) # read and parse response

        content = body.get("content", []) # extract content
        text_blocks = [c.get("text", "") for c in content if c.get("type") == "text"] # extract text parts
        out_text = "\n".join([t for t in text_blocks if t])
        logger.info(f"Model response length: {len(out_text)}")

        data = _extract_json(out_text) # may raise

        # ---------- Extract Fields ----------
        p = data.get("patient_info", {}) or {}
        h = data.get("hospital_info", {}) or {}
        m = data.get("medical_bill_info", {}) or {}

        patient_info = {
            "firstname": p.get("firstname"),
            "lastname": p.get("lastname"),
            "age": _to_number(p.get("age")),
            "phone": p.get("phone"),
            "address": p.get("address"),
            "city": p.get("city"),
            "state": p.get("state"),
            "zipcode": p.get("zipcode") or _extract_zip_from_address(p.get("address")),
        }

        # take hospital info
        hospital_info = {
            "name": h.get("name"),
            "phone": h.get("phone"),
            "address": h.get("address"),
            "city": h.get("city"),
            "state": h.get("state"),
            "zipcode": h.get("zipcode") or _extract_zip_from_address(h.get("address")),
        }

        items = []
        for it in m.get("items", []) or []:
            items.append({
                "code": it.get("code"),
                "description": it.get("description"),
                "bill": _to_number(it.get("bill"))
            })

        medical_bill_info = {
            "subtotal": _to_number(m.get("subtotal")),
            "discount": _to_number(m.get("discount")),
            "tax_rate_percent": _to_number(m.get("tax_rate_percent")),
            "total_tax": _to_number(m.get("total_tax")),
            "balance_due": _to_number(m.get("balance_due")),
        }

        # ---------- Generate IDs and Timestamps ----------
        table_id = str(uuid.uuid4())
        patient_id = str(uuid.uuid4())
        provider_id = str(uuid.uuid4())
        created_at = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

        # ---------- Construct Parsed Output ----------
        parsed_output = {
            "table_id": table_id,
            "patient_id": patient_id,
            "provider_id": provider_id,
            "created_at": created_at,
            "source_bucket": bucket,
            "source_key": key,
            "patient_info": patient_info,
            "hospital_info": hospital_info,
            "medical_bill_info": medical_bill_info,
            "items": items
        }

        # ---- Save to chitest02/parsed/bills/ ----
        base_name = os.path.splitext(os.path.basename(key))[0]
        filename = f"{base_name}_{table_id}.json"
        parsed_key = f"{PARSED_PREFIX}bills/{filename}"

        # this function saves the parsed data to s3
        s3.put_object(
            Bucket=OUTPUT_BUCKET,          # write to chitest02
            Key=parsed_key,                # parsed/bills/<file>.json
            Body=json.dumps(parsed_output, indent=2, default=str),
            ContentType="application/json"
        )
        logger.info(f"Parsed JSON saved to s3://{OUTPUT_BUCKET}/{parsed_key}")
        return parsed_key

    # except block to handle errors
    except Exception as e:
        logger.error(f"Failed to parse bill PDF: {e}", exc_info=True)
        raise
