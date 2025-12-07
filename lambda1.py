import os, json, base64, logging, shutil, re, uuid, datetime, time, random
from typing import Any, Dict
from urllib.parse import unquote_plus
from decimal import Decimal
from string import Template  # kept for future use if needed

import boto3
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    ReadTimeoutError,
    ConnectTimeoutError,
    ConnectionClosedError,
)

# =====================================================================
# Logging Setup
# =====================================================================
logger = logging.getLogger()
logger.setLevel(logging.INFO)
_MAX_LOG_CHUNK = 60000


def _log_big(label: str, text: str | None):
    """
    Log large text in manageable chunks so CloudWatch doesn't truncate it.
    Used for logging long model responses or large JSON blobs.
    """
    if not text:
        logger.info(f"{label}: <empty>")
        return
    logger.info(f"{label} (len={len(text)}):")
    for i in range(0, len(text), _MAX_LOG_CHUNK):
        logger.info(text[i:i + _MAX_LOG_CHUNK])


# =====================================================================
# AWS Clients & Tables
# =====================================================================
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")

# Core AWS clients
s3 = boto3.client("s3")
bedrock_rt = boto3.client("bedrock-runtime", region_name=AWS_REGION)
ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# Target Lambda (for chaining to the next step in the adjudication pipeline)
TARGET_LAMBDA_NAME = 'farhan_lambda_2'  # os.environ.get("Lambda_2")

# DynamoDB table names (overridable via environment variables for different environments)
PATIENT_TABLE = os.environ.get("PATIENT_TABLE", "Patient_info")                # PK: patient_id
PROVIDER_TABLE = os.environ.get("PROVIDER_TABLE", "Provider_info")            # PK: provider_id
BILL_TABLE = os.environ.get("BILL_TABLE", "temporary_patientMedicalBillInfo") # PK: table_id
BILL_ITEMS_TBL = os.environ.get("BILL_ITEMS_TABLE", "temporary_med_bill2")    # PK: code, SK: table_id
ICD10_TABLE = os.environ.get("ICD10_TABLE", "temporary_med_icd")              # PK: code, SK: table_id

# DynamoDB table resources
patient_tbl = ddb.Table(PATIENT_TABLE)
provider_tbl = ddb.Table(PROVIDER_TABLE)
bill_tbl = ddb.Table(BILL_TABLE)
bill_items_tbl = ddb.Table(BILL_ITEMS_TBL)
icd10_tbl = ddb.Table(ICD10_TABLE)

# =====================================================================
# Behavior Flags / Tunables
# =====================================================================
# These tunables allow you to adjust retry behavior and token limits via env vars.
RETRY_SLEEP_BASE = float(os.environ.get("RETRY_SLEEP_BASE", "0.8"))      # base delay for backoff
RETRY_JITTER_MAX = float(os.environ.get("RETRY_JITTER_MAX", "0.6"))      # random jitter added to backoff
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "8"))                    # max invoke retries
EXTRA_COOLDOWN_ON_FAIL_SECS = float(os.environ.get("EXTRA_COOLDOWN_ON_FAIL_SECS", "3.0"))
DOC_MAX_TOKENS = int(os.environ.get("DOC_MAX_TOKENS", "4500"))           # token budget for full document extraction


# =====================================================================
# LLM Prompt (single full-document extraction)
# =====================================================================
# This prompt defines the strict JSON schema and behavior the LLM must follow.
FULL_DOC_INSTRUCTIONS = """
You are extracting structured data from a medical receipt. READ THE ENTIRE PDF FILE IN ITS ENTIRETY.

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
  },
  "icd_10_codes": [
    {"code": string|null, "description": string|null}
  ]
}

Rules:
- Output MUST be valid JSON only. No backticks, no markdown, no extra commentary.
- Amounts (bill, subtotal, discount, taxes, balance_due) MUST be numbers (no $ or commas).
- If a field is missing on the document, set it to null.
- If a ZIP code appears inside an address, also copy it to zipcode.
- Do not invent data. Be conservative.
- Make sure to get all the medical data.
- "items" typically contain billing procedure codes (e.g., CPT/HCPCS) with amounts.
- "icd_10_codes" should contain any diagnosis codes labeled as ICD-10, DX, or similar, and their human-readable descriptions.
- the "icd_10 codes" are not guaranteed to exist in the document. If you do not find it, enter Null as the value
"""


# =====================================================================
# Helper Functions: Bedrock formatting and parsing
# =====================================================================
def _build_pdf_content_block(b64_data: str) -> Dict[str, Any]:
    """
    Build a Bedrock 'document' content block for a PDF.
    We assume all inputs are PDFs, so no format detection is needed.
    """
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": b64_data,
        },
    }


def _first_text_block(body_json: Dict[str, Any]) -> str:
    """
    Extract concatenated text from the model's response body.
    Bedrock returns a list of 'content' blocks; we merge all text-type blocks.
    """
    content = body_json.get("content", [])
    return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"]).strip()


# Regex to pull the outermost JSON object from the model text
_json_outer_re = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """
    Extract the first JSON object found in the text and parse it.
    Raises ValueError if no JSON is found or parsing fails.
    This is defensive in case the model adds stray text around the JSON.
    """
    if not text:
        raise ValueError("Model returned empty text.")
    m = _json_outer_re.search(text)
    if not m:
        raise ValueError("Model did not return JSON.")
    return json.loads(m.group(0))


# Regex to detect general numeric substrings (for money, percentages, etc.)
_money_re = re.compile(r"[-+]?\d*\.?\d+")


def _to_number(x):
    """
    Convert various numeric-like values to float (or None).
    Strips currency symbols and commas from strings.
    Intended to normalize LLM outputs for numeric fields.
    """
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        m = _money_re.search(x.replace(",", ""))
        return float(m.group(0)) if m else None
    return None


# Regex to detect US ZIP codes in arbitrary address strings
_zip_re = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def _maybe_zip_from_address(addr):
    """
    Try to extract a ZIP code from an address string.
    If not found, returns None.
    """
    if not addr or not isinstance(addr, str):
        return None
    m = _zip_re.search(addr)
    return m.group(0) if m else None


def _to_decimal(n) -> Decimal | None:
    """
    Convert to Decimal where possible for DynamoDB numeric fields.
    DynamoDB requires Decimal for non-integer numeric types.
    """
    if n is None:
        return None
    if isinstance(n, Decimal):
        return n
    if isinstance(n, (int, float)):
        return Decimal(str(n))
    if isinstance(n, str):
        try:
            return Decimal(n)
        except Exception:
            return None
    return None


def _clean_for_ddb(obj):
    """
    Recursively clean Python object for DynamoDB:
    - Remove None and empty strings (to avoid validation issues).
    - Convert int/float to Decimal.
    - Preserve nested structures and strings.
    This is applied to items right before DDB writes.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            cleaned = _clean_for_ddb(v)
            if cleaned is None:
                continue
            if isinstance(cleaned, str) and cleaned == "":
                continue
            out[k] = cleaned
        return out

    elif isinstance(obj, list):
        return [
            x
            for x in (_clean_for_ddb(v) for v in obj)
            if not (x is None or x == "")
        ]

    elif isinstance(obj, (int, float)):
        return _to_decimal(obj)

    elif isinstance(obj, (str, Decimal)):
        return obj

    else:
        return obj


def _put_safe(table, item: dict):
    """
    Clean and write an item safely into DynamoDB.
    - Sanitizes the item with _clean_for_ddb
    - Performs put_item
    Returns the cleaned item for logging/debugging.
    """
    item_clean = _clean_for_ddb(item)
    table.put_item(Item=item_clean)
    return item_clean


# =====================================================================
# Bedrock Invocation Helpers (with retry/backoff)
# =====================================================================
def _is_retryable_client_error(e: ClientError) -> bool:
    """
    Determine whether a ClientError is retryable (throttling, 5xx, etc.).
    This prevents immediate hard failure on transient Bedrock issues.
    """
    err = e.response.get("Error", {}) if hasattr(e, "response") else {}
    code = (err.get("Code") or "").lower()
    msg = (err.get("Message") or "")
    retryable_codes = {
        "throttlingexception",
        "toomanyrequestsexception",
        "serviceunavailableexception",
        "internalfailure",
        "internalservererror",
        "requesttimeout",
        "limitexceededexception",
    }
    if code in retryable_codes:
        return True
    if "too many requests" in str(msg).lower():
        return True
    status = (
        e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if hasattr(e, "response")
        else None
    )
    if status and (status == 429 or 500 <= status < 600):
        return True
    return False


def _sleep_with_backoff(attempt: int):
    """
    Exponential backoff with random jitter based on the attempt number.
    Backoff = RETRY_SLEEP_BASE * 2^(attempt-1) + random jitter.
    """
    delay = (RETRY_SLEEP_BASE * (2 ** (attempt - 1))) + random.uniform(
        0, RETRY_JITTER_MAX
    )
    time.sleep(delay)


def _bedrock_invoke(model_id: str, payload: dict) -> dict:
    """
    Robust Bedrock invocation with automatic retries and backoff.
    - Handles network issues, throttling, and 5xx responses.
    - Raises RuntimeError after exhausting MAX_RETRIES.
    """
    body_bytes = json.dumps(payload).encode("utf-8")
    last_err = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = bedrock_rt.invoke_model(modelId=model_id, body=body_bytes)
            return json.loads(resp["body"].read())
        except (
            EndpointConnectionError,
            ReadTimeoutError,
            ConnectTimeoutError,
            ConnectionClosedError,
        ) as e:
            # Low-level connectivity or timeout issues → retry
            last_err = e
            logger.warning(
                f"Bedrock connection/timeout (attempt {attempt}/{MAX_RETRIES}): {e}"
            )
            _sleep_with_backoff(attempt)
            continue
        except ClientError as e:
            # AWS service-level error; decide if retryable based on code/status
            last_err = e
            if _is_retryable_client_error(e):
                logger.warning(
                    f"Bedrock retryable error (attempt {attempt}/{MAX_RETRIES}): {e}"
                )
                _sleep_with_backoff(attempt)
                continue
            # Non-retryable → propagate immediately
            logger.error(f"Bedrock non-retryable error: {e}", exc_info=True)
            raise
        except Exception as e:
            # Unknown error; treat as transient and retry until limit
            last_err = e
            logger.warning(
                f"Bedrock invoke transient error (attempt {attempt}/{MAX_RETRIES}): {e}",
                exc_info=True,
            )
            _sleep_with_backoff(attempt)

    # All retries exhausted
    logger.error("Bedrock invoke failed after retries.", exc_info=True)
    raise RuntimeError(f"Bedrock invoke failed after retries: {last_err}")


def _invoke_full_extraction(model_id: str, content_block: dict) -> Dict[str, Any]:
    """
    Invoke the model ONCE for the entire PDF to extract structured data.
    The prompt and PDF content_block are sent together as a single message.
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": FULL_DOC_INSTRUCTIONS},
                content_block,
            ],
        }
    ]
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": messages,
        "max_tokens": DOC_MAX_TOKENS,
        "temperature": 0,
    }

    logger.info("Invoking model for full-document extraction ...")
    body = _bedrock_invoke(model_id, payload)
    raw_text = _first_text_block(body)
    _log_big("[full-doc] Full OCR/Model output", raw_text)
    _log_big("[full-doc] Model raw (first 2k)", raw_text[:2000])
    return _extract_json_from_text(raw_text)


# =====================================================================
# Lambda Chaining Helper
# =====================================================================
def _trigger_next_lambda(
    bucket: str,
    key: str,
    version_id: str | None,
    table_id: str | None,
    job_id: str | None,
):
    """
    Fire-and-forget invocation of the next Lambda in the pipeline.
    Passes:
      - S3 bucket/key/version (for context)
      - table_id (linking to this bill in DynamoDB)
      - job_id (from S3 object metadata, used to correlate to frontend job)
    """
    if not TARGET_LAMBDA_NAME:
        logger.warning("TARGET_LAMBDA_NAME not set; skipping trigger.")
        return

    payload = {
        "source": "lambda-chain",
        "s3": {
            "bucket_name": bucket,
            "object_key": key,
            "version_id": version_id,
        },
        "table_id": table_id,
        "job_id": job_id,
    }

    logger.info(f"Triggering {TARGET_LAMBDA_NAME} with payload: {json.dumps(payload)}")

    # InvocationType="Event" → asynchronous invocation; this Lambda does not wait for the next one
    lambda_client.invoke(
        FunctionName=TARGET_LAMBDA_NAME,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    logger.info(
        f"Triggered next lambda {TARGET_LAMBDA_NAME} for s3://{bucket}/{key}"
        + (f"?versionId={version_id}" if version_id else "")
    )


# =====================================================================
# Main Lambda Handler
# =====================================================================
def lambda_handler(event, context):
    """
    Entry point for S3 -> Lambda:
    - Triggered by S3 PUT (PDF upload).
    - For each PDF:
      * Read PDF from S3 (and read job_id from S3 object metadata).
      * Call Bedrock ONCE with the entire PDF to extract structured JSON.
      * Write patient, provider, bill, items, and ICD-10 rows to DynamoDB.
      * Use ONE table_id per PDF (whole bill).
      * Trigger the next Lambda with table_id and job_id.
      * Delete the source PDF from S3 after processing (cleanup).
    """
    tmp_root = "/tmp"
    model_id = os.environ["MODEL_ID"]

    results = []
    # Keep last parsed info for final debug prints
    last_patient_info = None
    last_hospital_info = None
    last_medical_bill_info = None

    try:
        # -----------------------------------------------------------------
        # 1. Validate event and get S3 records
        # -----------------------------------------------------------------
        records = event.get("Records", [])
        if not records:
            logger.info("No S3 records in event.")
            return {"results": []}

        # -----------------------------------------------------------------
        # 2. Process each S3 record (each uploaded PDF)
        # -----------------------------------------------------------------
        for idx, rec in enumerate(records, start=1):
            bucket = rec["s3"]["bucket"]["name"]
            key = unquote_plus(rec["s3"]["object"]["key"])
            size = rec["s3"]["object"].get("size")
            version_id = None  # ignore object versions for now

            logger.info(f"[{idx}] Start s3://{bucket}/{key} size={size}")

            parsed_any_page = False
            # Conceptually treating the whole PDF as "page 1"
            page_results = []
            table_id: str | None = None
            job_id: str | None = None

            try:
                # ---------------------------------------------------------
                # 2.1 Fetch PDF from S3 and read job_id from metadata
                # ---------------------------------------------------------
                obj = s3.get_object(Bucket=bucket, Key=key)
                content_type = obj.get("ContentType")
                logger.info(f"[{idx}] S3 ContentType: {content_type}")

                # Metadata is lowercase-keyed in S3; expect 'job_id' set by uploader
                metadata = (obj.get("Metadata") or {})
                job_id = metadata.get("job_id")
                logger.info(f"[{idx}] S3 object metadata: {metadata} (job_id={job_id})")

                # Read full PDF bytes and encode as base64 for Bedrock document input
                file_bytes = obj["Body"].read()
                b64 = base64.b64encode(file_bytes).decode("utf-8")

                # We assume all inputs are PDFs, so directly build a PDF content block.
                content_block = _build_pdf_content_block(b64)

                # ---------------------------------------------------------
                # 2.2 Single full-document extraction via Bedrock
                # ---------------------------------------------------------
                created_at = datetime.datetime.utcnow().isoformat(
                    timespec="seconds"
                ) + "Z"

                # Generate identifiers for this bill and associated entities
                patient_id = str(uuid.uuid4())
                provider_id = str(uuid.uuid4())
                table_id = str(uuid.uuid4())

                try:
                    data = _invoke_full_extraction(model_id, content_block)
                except Exception as e:
                    # Any model or parsing failure for this PDF is captured, but we continue
                    logger.error(
                        f"[{idx}] Error during full-doc extraction: {e}",
                        exc_info=True,
                    )
                    page_results.append(
                        {
                            "page_no": 1,
                            "parsed": False,
                            "error": str(e),
                        }
                    )
                    # Small cooldown to avoid hammering the model if many failures occur
                    time.sleep(EXTRA_COOLDOWN_ON_FAIL_SECS)
                    results.append(
                        {
                            "bucket": bucket,
                            "key": key,
                            "parsed_any_page": False,
                            "pages": page_results,
                        }
                    )
                    # control flow continues to 'finally' where we still trigger next lambda and delete
                    continue

                # ---------------------------------------------------------
                # 2.3 Normalize JSON segments from full document
                # ---------------------------------------------------------
                p = data.get("patient_info", {}) or {}
                h = data.get("hospital_info", {}) or {}
                m = data.get("medical_bill_info", {}) or {}
                icd_10_list = data.get("icd_10_codes", []) or []

                # ---------------- Patient ----------------
                patient_info = {
                    "firstname": p.get("firstname"),
                    "lastname": p.get("lastname"),
                    "age": _to_number(p.get("age")),
                    "phone": p.get("phone"),
                    "address": p.get("address"),
                    "city": p.get("city"),
                    "state": p.get("state"),
                    "zipcode": p.get("zipcode"),
                }
                # If zipcode missing, try to infer it from the address string
                if not patient_info["zipcode"]:
                    patient_info["zipcode"] = _maybe_zip_from_address(
                        patient_info["address"]
                    )

                # ---------------- Hospital / Provider ----------------
                hospital_info = {
                    "name": h.get("name"),
                    "phone": h.get("phone"),
                    "address": h.get("address"),
                    "city": h.get("city"),
                    "state": h.get("state"),
                    "zipcode": h.get("zipcode"),
                }
                if not hospital_info["zipcode"]:
                    hospital_info["zipcode"] = _maybe_zip_from_address(
                        hospital_info["address"]
                    )

                # ---------------- Bill Items ----------------
                # The LLM returns a list of dicts with code/description/bill
                items = []
                for it in (m.get("items") or []):
                    items.append(
                        {
                            "code": it.get("code"),
                            "description": it.get("description"),
                            "bill": _to_number(it.get("bill")),
                        }
                    )

                # ---------------- Bill Summary ----------------
                medical_bill_info = {
                    "subtotal": _to_number(m.get("subtotal")),
                    "discount": _to_number(m.get("discount")),
                    "tax_rate_percent": _to_number(
                        m.get("tax_rate_percent")
                    ),
                    "total_tax": _to_number(m.get("total_tax")),
                    "balance_due": _to_number(m.get("balance_due")),
                }

                # -------------------------------------------------
                # 2.4 Persist to DynamoDB (patient, provider, bill)
                # -------------------------------------------------
                # Patient row (one per PDF)
                patient_item = {
                    "patient_id": patient_id,
                    "created_at": created_at,
                    "table_id": table_id,
                    "source_bucket": bucket,
                    "source_key": key,
                    "page_no": 1,  # full-doc treated as single logical page
                    **patient_info,
                }
                patient_item = _put_safe(patient_tbl, patient_item)

                # Provider/hospital row (one per PDF)
                provider_item = {
                    "provider_id": provider_id,
                    "created_at": created_at,
                    "table_id": table_id,
                    "source_bucket": bucket,
                    "source_key": key,
                    "page_no": 1,
                    **hospital_info,
                }
                provider_item = _put_safe(provider_tbl, provider_item)

                # Bill summary row (one per PDF)
                bill_item = {
                    "table_id": table_id,
                    "created_at": created_at,
                    "source_bucket": bucket,
                    "source_key": key,
                    "patient_id": patient_id,
                    "provider_id": provider_id,
                    "page_no": 1,
                    **medical_bill_info,
                }
                # Ensure numeric fields are Decimal for DynamoDB
                for k in (
                    "subtotal",
                    "discount",
                    "tax_rate_percent",
                    "total_tax",
                    "balance_due",
                ):
                    if bill_item.get(k) is not None:
                        bill_item[k] = _to_decimal(bill_item[k])
                bill_item = _put_safe(bill_tbl, bill_item)

                # -------------------------------------------------
                # 2.5 Write bill items to DynamoDB (one row per item)
                # -------------------------------------------------
                # These are the line items (CPT/HCPCS with amounts) linked by table_id.
                if items:
                    with bill_items_tbl.batch_writer() as batch:
                        for it in items:
                            bill_dec = _to_decimal(it.get("bill"))
                            code_val = it.get("code")
                            # Guarantee a non-empty PK even if the LLM didn't find a code
                            if not code_val or code_val == "":
                                code_val = f"NO_CODE_{uuid.uuid4()}"
                            item_row = {
                                "code": code_val,  # PK
                                "table_id": table_id,  # SK (in GSI or composite PK design)
                                "description": it.get("description"),
                                "bill": bill_dec,
                                "created_at": created_at,
                                "page_no": 1,
                            }
                            batch.put_item(
                                Item=_clean_for_ddb(item_row)
                            )

                # -------------------------------------------------
                # 2.6 Write ICD-10 codes to icd_10_reference_table
                #      PK: code, SK: table_id
                # -------------------------------------------------
                icd10_count = 0
                for icd in icd_10_list:
                    code_val = (icd or {}).get("code")
                    desc_val = (icd or {}).get("description")
                    if not code_val:
                        # Skip entries with no code; description alone isn't useful as a PK
                        continue
                    icd_item = {
                        "code": code_val,       # partition key
                        "table_id": table_id,   # sort key
                        "description": desc_val,
                        "created_at": created_at,
                        "source_bucket": bucket,
                        "source_key": key,
                    }
                    _put_safe(icd10_tbl, icd_item)
                    icd10_count += 1

                logger.info(
                    f"[{idx}] DDB writes OK: "
                    f"{PATIENT_TABLE}(patient_id={patient_id}), "
                    f"{PROVIDER_TABLE}(provider_id={provider_id}), "
                    f"{BILL_TABLE}(table_id={table_id}), "
                    f"{BILL_ITEMS_TBL}(items={len(items)}), "
                    f"{ICD10_TABLE}(icd10_codes={icd10_count})"
                )

                # Track last successfully parsed info for debug/demo prints
                last_patient_info = patient_info
                last_hospital_info = hospital_info
                last_medical_bill_info = {
                    **medical_bill_info,
                    "items": items,
                }
                parsed_any_page = True

                # Capture per-PDF summary for the function response
                page_results.append(
                    {
                        "page_no": 1,
                        "parsed": True,
                        "table_id": table_id,
                        "patient_id": patient_id,
                        "provider_id": provider_id,
                        "items_count": len(items),
                        "icd10_count": icd10_count,
                        "patient_info": patient_info,
                        "hospital_info": hospital_info,
                        "medical_bill_info": medical_bill_info,
                    }
                )

            except Exception as e:
                # Catch-all to avoid the whole batch failing due to one PDF
                logger.error(
                    f"[{idx}] Error while processing {key}: {e}", exc_info=True
                )
            finally:
                # ---------------------------------------------------------
                # 2.7 Trigger next Lambda (adjudication step)
                # ---------------------------------------------------------
                try:
                    if table_id is not None:
                        # Debug print for CloudWatch
                        print(table_id)
                        logger.info(f"[{idx}] Triggering next lambda with table_id={table_id}, job_id={job_id}")
                        _trigger_next_lambda(bucket, key, version_id, table_id, job_id)
                    else:
                        logger.warning(
                            f"[{idx}] Skipping next-lambda trigger for s3://{bucket}/{key} "
                            f"because table_id is None (processing failed early)."
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to trigger next lambda for s3://{bucket}/{key}: {e}",
                        exc_info=True,
                    )

                # ---------------------------------------------------------
                # 2.8 Delete the source file from S3 after processing
                # ---------------------------------------------------------
                try:
                    if bucket and key:
                        logger.info(f"[{idx}] Deleting source object s3://{bucket}/{key}")
                        s3.delete_object(Bucket=bucket, Key=key)
                        logger.info(f"[{idx}] Deleted source object s3://{bucket}/{key}")
                except Exception as e:
                    # Deletion failure is logged but not fatal to the Lambda
                    logger.error(
                        f"[{idx}] Failed to delete source object s3://{bucket}/{key}: {e}",
                        exc_info=True,
                    )

                # Store result summary for this record
                results.append(
                    {
                        "bucket": bucket,
                        "key": key,
                        "parsed_any_page": parsed_any_page,
                        "pages": page_results,
                    }
                )
                logger.info(
                    f"[{idx}] Done with full PDF (pages processed={len(page_results)})."
                )

        logger.info(f"Processed {len(records)} record(s).")
        return {"results": results}

    finally:
        # =================================================================
        # Final debug/demo prints (non-critical) and /tmp cleanup
        # =================================================================
        # These prints are for manual testing insight; they do not affect logic.
        print("Testing")
        try:
            if last_patient_info:
                print(
                    last_patient_info.get("firstname"),
                    last_patient_info.get("lastname"),
                )
            if last_hospital_info:
                print(last_hospital_info.get("phone"))
            if last_medical_bill_info:
                print(last_medical_bill_info.get("balance_due"))
                for item in last_medical_bill_info.get("items", []):
                    code = item.get("code")
                    desc = item.get("description")
                    bill = item.get("bill")
                    print(f"{code} - {desc}: ${bill}")
        except Exception as e:
            logger.warning(f"Demo prints failed: {e}")

        # Clean up any temporary files/directories in /tmp to keep the environment clean
        try:
            for name in os.listdir(tmp_root):
                path = os.path.join(tmp_root, name)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"Failed to remove {path}: {e}")
            logger.info("Cleaned /tmp.")
        except FileNotFoundError:
            # /tmp may not exist or may already be cleaned
            pass
