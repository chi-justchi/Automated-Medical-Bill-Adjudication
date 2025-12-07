import os, json, base64, logging, shutil, uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import unquote_plus
import boto3
from parsingPolicies import parse_policy_pdf
from parsingBills import parse_bill_pdf
from fetchPatientData import *
from decimal import Decimal

# ---------- Logging ----------
logger = logging.getLogger()
logger.setLevel(logging.INFO)
_MAX_LOG_CHUNK = 60000

def _log_big(label: str, text: str | None):
    if not text:
        logger.info(f"{label}: <empty>")
        return
    logger.info(f"{label} (len={len(text)}):")
    for i in range(0, len(text), _MAX_LOG_CHUNK):
        logger.info(text[i:i+_MAX_LOG_CHUNK])

# ---------- AWS Clients ----------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
MAIN_BUCKET = os.environ.get("MAIN_BUCKET", "chitest02")  # <-- add this
s3 = boto3.client("s3")
bedrock_rt = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# ---------- Configuration ----------
POLICY_PREFIX = "policies/"
PARSED_PREFIX = "parsed/"
MODEL_ID = os.environ.get("MODEL_ID")


# ---------- Helper Functions ----------
def _delete_object(bucket: str, key: str) -> bool:
    """Delete an S3 object"""
    try:
        resp = s3.delete_object(Bucket=bucket, Key=key)
        logger.info(f"Deleted: s3://{bucket}/{key}")
        return True
    except Exception as e:
        logger.error(f"Delete failed for s3://{bucket}/{key}: {e}")
        return False

def decimal_to_number(obj):
    """Convert Decimal objects to int or float for JSON serialization"""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def _check_parsed_policy_exists(bucket: str, policy_key: str) -> bool:
    """Check if parsed policy JSON already exists"""
    try:
        filename = policy_key.split('/')[-1].replace('.pdf', '.json')
        parsed_key = f"{PARSED_PREFIX}policies/{filename}"
        
        s3.head_object(Bucket=bucket, Key=parsed_key)
        logger.info(f"Parsed policy already exists: s3://{bucket}/{parsed_key}")
        return True
    except s3.exceptions.ClientError:
        return False

def _get_latest_policy(bucket: str) -> Optional[Dict[str, Any]]:
    """Fetch the most recent parsed policy JSON"""
    try:
        response = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=f"{PARSED_PREFIX}policies/",
            MaxKeys=100
        )
        
        if 'Contents' not in response or not response['Contents']:
            logger.warning("No parsed policies found")
            return None
        
        # Sort by LastModified descending
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        latest_key = objects[0]['Key']
        
        logger.info(f"Fetching latest policy: s3://{bucket}/{latest_key}")
        obj = s3.get_object(Bucket=bucket, Key=latest_key)
        policy_data = json.loads(obj['Body'].read().decode('utf-8'))
        
        return policy_data
    except Exception as e:
        logger.error(f"Failed to fetch latest policy: {e}", exc_info=True)
        return None

def _build_bill_data_from_dynamodb(table_id: str) -> Optional[Dict[str, Any]]:
    """
    Construct bill data structure from DynamoDB tables.
    Returns a dictionary matching the expected bill_data format,
    or None if something is missing.
    """
    logger.info(f"Building bill_data from DynamoDB for table_id={table_id}")
    
    # Patient info
    patient_info = get_patient_info_by_table_id(table_id)
    if not patient_info:
        logger.warning(f"No patient info found for table_id={table_id}")
        return None

    # Fetch provider info
    provider_info = get_provider_info_by_table_id(table_id)
    if not provider_info:
        logger.warning(f"No provider info found for table_id={table_id}")
        return None
    
    # Fetch medical bill info
    bill_info = get_medical_bill_info_by_table_id(table_id)
    if not bill_info:
        logger.warning(f"No medical bill info found for table_id={table_id}")
        return None


    # CPT / procedure codes
    cpt_codes = get_codes_for_table_id(table_id)
    if not cpt_codes:
        logger.warning(f"No CPT codes found for table_id={table_id}")
        cpt_codes = []

    # Base structure 
    bill_data: Dict[str, Any] = {
        "table_id": table_id,
        "patient_id": patient_info.get("patient_id", ""),
        "provider_id": provider_info.get("provider_id", ""),
        "created_at": patient_info.get("created_at", ""),
        "source_bucket": patient_info.get("source_bucket", MAIN_BUCKET),
        "source_key": patient_info.get("source_key", f"dynamodb:{table_id}"),
        "patient_info": {
            "firstname": patient_info.get("firstname", ""),
            "lastname": patient_info.get("lastname", ""),
            "phone": patient_info.get("phone", ""),
            "address": patient_info.get("address", ""),
            "city": patient_info.get("city", ""),
        },
        "hospital_info": {
            "name": provider_info.get("name", ""),
            "phone": provider_info.get("phone", ""),
            "address": provider_info.get("address", ""),
            "city": provider_info.get("city", ""),
        },
        "medical_bill_info": {
            "subtotal": decimal_to_number(bill_info.get("subtotal")),
            "tax_rate_percent": decimal_to_number(bill_info.get("tax_rate_percent")),
            "total_tax": decimal_to_number(bill_info.get("total_tax")),
            "balance_due": decimal_to_number(bill_info.get("balance_due"))

        },
        "items": []
    }

    # Add items (procedures/codes)
    for code_item in cpt_codes:
        code = code_item.get("code", "")
        
        # Fetch charge from temporary_med_bill2 table
        charge_data = get_charge_by_code(code, table_id)
        
        if charge_data:
            charge = decimal_to_number(charge_data.get("bill"))
        else:
            # Fallback to code_item if not found in temporary_med_bill2
            charge = float(code_item.get("charge_amount", 0) or 0)
        
        item = {
            "code": code,
            "description": code_item.get("description", ""),
            "bill": charge
        }
        bill_data["items"].append(item)

    logger.info(
        f"Built bill_data from DynamoDB for table_id={table_id} "
        f"with {len(bill_data['items'])} items, "
        f"balance_due={bill_info.get('balance_due')}"
    )
    print(f"Debug: This is bill_data: {bill_data}")
    return bill_data


# def _compare_bill_to_policy(bill_data: dict, policy_data: dict, bucket: str) -> Optional[str]:
def _compare_bill_to_policy(bill_data: dict, policy_data: dict, bucket: str, key: str, metadata) -> Optional[str]:
    """Compare bill against policy and save comparison results"""
    max_retries = 5
    base_delay = 2  # seconds

    try:
        prompt = f"""You are an insurance coverage analyst. Compare this medical bill against the insurance policy and identify what's covered and how much is covered.

POLICY:    
{json.dumps(policy_data, indent=2)}

MEDICAL BILL:
{json.dumps(bill_data, indent=2)}

Analyze and return ONLY a single JSON object with this structure:
{{
  "bill_summary": {{
    "patient": "...",
    "provider": "...",
    "total_billed": 0.00,
    "procedure_count": 0
  }},
  "coverage_analysis": [
    {{
      "procedure": "...",
      "cpt_code": "...",
      "billed_amount": 0.00,
      "covered": true/false,
      "coverage_type": "in-network/out-of-network/not covered",
      "deductible_applies": true/false,
      "deductible_amount": 0.00,
      "coinsurance_rate": "xx%",
      "patient_responsibility": 0.00,
      "insurance_pays": 0.00,
      "explanation": "..."
    }}
  ],
  "totals": {{
    "total_billed": 0.00,
    "total_covered": 0.00,
    "total_patient_owes": 0.00,
    "total_insurance_pays": 0.00,
    "breakdown": {{
      "deductible": 0.00,
      "coinsurance": 0.00,
      "copay": 0.00,
      "not_covered": 0.00
    }}
  }},
  "notes": ["Any important details about coverage limits, exclusions, etc."]
}}"""

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": prompt}]
        }]

        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "max_tokens": 4000,
            "temperature": 0
        }

        resp = bedrock_rt.invoke_model(modelId=MODEL_ID, body=json.dumps(payload))
        body = json.loads(resp["body"].read())
        
        content = body.get("content", [])
        text_blocks = [c.get("text", "") for c in content if c.get("type") == "text"]
        comparison_text = "\n".join([t for t in text_blocks if t])
        
        logger.info("=== COVERAGE COMPARISON ===")
        _log_big("Comparison Result", comparison_text)
        
        # Parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', comparison_text, re.DOTALL)
        if json_match:
            comparison_result = json.loads(json_match.group(0))
        else:
            comparison_result = {"raw_response": comparison_text}
        
        # Save comparison results
        comparison_id = str(uuid.uuid4())
        # timestamp = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        
        comparison_output = {
            "comparison_id": comparison_id,
            "timestamp": timestamp,
            "bill_table_id": bill_data.get("table_id"),
            "bill_source_key": bill_data.get("source_key"),
            "policy_id": policy_data.get("policy_id", "unknown"),
            "comparison": comparison_result
        }
        
        # Save to S3
        filename = f"comparison_{comparison_id}.json"
        comparison_key = f"{PARSED_PREFIX}comparisons/{filename}"
        
        s3.put_object(
            Bucket=bucket,
            Key=comparison_key,
            Body=json.dumps(comparison_output, indent=2, default=str),
            ContentType="application/json",
            Metadata=metadata
        )
        
        logger.info(f"Saved comparison to s3://{bucket}/{comparison_key}")
        return comparison_key
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ThrottlingException':
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff: 2, 4, 8, 16, 32 seconds
                logger.warning(f"Throttled. Retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                logger.error(f"Comparison failed after {max_retries} retries: {e}", exc_info=True)
                return None
        else:
            logger.error(f"Comparison failed: {e}", exc_info=True)
            return None
    except Exception as e:
        logger.error(f"Comparison failed: {e}", exc_info=True)
        return None


def handler(event, context):
    tmp_root = "/tmp"
    results = []
    
    job_id = event.get('job_id')
    print(job_id)

    metadata = {}
    if job_id:
        metadata['job_id'] = job_id

    try:
        records = event.get("Records", [])

        # --------- MODE 1: S3-triggered invocation ---------
        if records:
            if not records:
                logger.info("No S3 records in event.")
                return {"results": []}

            for idx, rec in enumerate(records, start=1):
                bucket = rec["s3"]["bucket"]["name"]
                key = unquote_plus(rec["s3"]["object"]["key"])
                size = rec["s3"]["object"].get("size")
                logger.info(f"[{idx}] Start s3://{bucket}/{key} size={size}")

                deleted = False
                result = {
                    "bucket": bucket,
                    "key": key,
                    "type": None,
                    "action": None,
                    "deleted": False,
                    "comparison_key": None
                }

                try:
                    # 1) Determine document type
                    is_policy = key.startswith(POLICY_PREFIX)
                    is_json = key.lower().endswith('.json')
                    is_pdf = key.lower().endswith('.pdf')
                    
                    doc_type = "POLICY" if is_policy else "BILL"
                    result["type"] = doc_type
                    
                    logger.info(f"[{idx}] Document type: {doc_type}, is_json={is_json}, is_pdf={is_pdf}")

                    # Skip if it's already a parsed JSON file
                    # if key.startswith(PARSED_PREFIX):
                    if key.startswith(f"{PARSED_PREFIX}policies/") or key.startswith(f"{PARSED_PREFIX}comparisons/"):
                        logger.info(f"[{idx}] Skipping parsed file: {key}")
                        result["action"] = "skipped_parsed"
                        results.append(result)
                        continue

                    # 2) Handle POLICY
                    if is_policy:
                        if is_pdf:
                            # Check if already parsed
                            if _check_parsed_policy_exists(bucket, key):
                                logger.info(f"[{idx}] Policy already parsed, skipping")
                                result["action"] = "skipped_exists"
                                results.append(result)
                                continue
                            
                            # Parse new policy PDF
                            logger.info(f"[{idx}] Parsing policy PDF")
                            parsed_key = parse_policy_pdf(bucket, key, MODEL_ID)
                            result["action"] = "parsed"
                            result["parsed_key"] = parsed_key
                        else:
                            logger.info(f"[{idx}] Skipping non-PDF policy file")
                            result["action"] = "skipped_format"
                    
                    # 3) Handle BILL
                    elif not is_policy:
                        # ---------- Handle BILL documents ----------
                        bill_data = None

                        # S3-triggered bill path: parse PDF or load JSON
                        parsed_bill_data = None
                        if is_pdf:
                            logger.info(f"[{idx}] Parsing bill PDF")
                            parsed_key = parse_bill_pdf(bucket, key, MODEL_ID)
                            result["action"] = "parsed"
                            result["parsed_key"] = parsed_key
                            
                            # Fetch the parsed data
                            obj = s3.get_object(Bucket=bucket, Key=parsed_key)
                            parsed_bill_data = json.loads(obj['Body'].read().decode('utf-8'))
                            
                        elif is_json:
                            logger.info(f"[{idx}] Loading existing bill JSON")
                            obj = s3.get_object(Bucket=bucket, Key=key)
                            parsed_bill_data = json.loads(obj['Body'].read().decode('utf-8'))
                            result["action"] = "loaded_json"

                        bill_data = parsed_bill_data

                        # 4) Compare with policy if we have bill data
                        if bill_data:
                            logger.info(f"[{idx}] Fetching latest policy for comparison")
                            policy_data = _get_latest_policy(bucket)
                            
                            if policy_data:
                                logger.info(f"[{idx}] Comparing bill to policy")
                                comparison_key = _compare_bill_to_policy(
                                    bill_data, 
                                    policy_data, 
                                    bucket, 
                                    key,
                                    metadata
                                )
                                result["comparison_key"] = comparison_key
                                result["compared"] = comparison_key is not None
                            else:
                                logger.warning(f"[{idx}] No policy found for comparison")
                                result["compared"] = False
                        else:
                            logger.warning(f"[{idx}] Could not build bill_data from any source")
                            result["compared"] = False
                        
                        # 5) Delete original bill PDF after processing
                        if is_pdf:
                            deleted = _delete_object(bucket, key)
                            result["deleted"] = deleted

                except Exception as e:
                    logger.error(f"[{idx}] Error processing {key}: {e}", exc_info=True)
                    result["error"] = str(e)

                finally:
                    results.append(result)
                    logger.info(f"[{idx}] Done.")

            logger.info(f"Processed {len(records)} record(s).")
            return {"results": results}

        # --------- MODE 2: Direct invocation with table_id (no S3 Records) ---------
        table_id = event.get("table_id")
        if table_id:
            logger.info(f"Direct invocation with table_id={table_id}")
            bucket = event.get("bucket_name", MAIN_BUCKET)

            # 🔹 1) Look at validation result from Lambda 2 (if present)
            validation = event.get("validation")
            if validation is not None:
                all_valid = validation.get("all_valid")
                if all_valid is False:
                    # Build human-readable reason
                    reason_parts = []

                    # Main issue from CPT vs ICD if present
                    main_issue = validation.get("cpt_icd_justification_issue")
                    if main_issue:
                        reason_parts.append(main_issue)

                    # Any additional issues list
                    extra_issues = validation.get("issues") or []
                    if extra_issues:
                        reason_parts.append("; ".join(extra_issues))

                    reason = " ".join(reason_parts) or "See validation details."
                    message = f"The bill is invalid because: {reason}"

                    # 🔹 2) Save an 'invalid bill' comparison object to S3
                    comparison_id = str(uuid.uuid4())
                    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"

                    comparison_output = {
                        "comparison_id": comparison_id,
                        "timestamp": timestamp,
                        "bill_table_id": table_id,
                        "bill_source_key": f"dynamodb:{table_id}",
                        "policy_id": None,
                        "comparison": {
                            "status": "invalid_bill",
                            "message": message,
                            "validation": validation,
                        },
                    }

                    filename = f"comparison_{comparison_id}.json"
                    comparison_key = f"{PARSED_PREFIX}comparisons/{filename}"

                    s3.put_object(
                        Bucket=bucket,
                        Key=comparison_key,
                        Body=json.dumps(comparison_output, indent=2),
                        ContentType="application/json",
                        Metadata=metadata,
                    )

                    logger.info(
                        f"Bill marked invalid; saved comparison to s3://{bucket}/{comparison_key}"
                    )
                    
                    # 🔹 CLEANUP AFTER SAVING INVALID COMPARISON
                    cleanup_results = cleanup_all_data_for_table_id(table_id)
                    logger.info(f"Cleanup results: {cleanup_results}")

                    # 🔹 3) Return the "The bill is invalid because ..." message
                    return {
                        "mode": "dynamodb",
                        "table_id": table_id,
                        "success": False,
                        "comparison_key": comparison_key,
                        "reason": message,
                    }

            # 🔹 If we reach here: either validation is missing or all_valid is True → proceed normally


            # Build bill_data from DynamoDB
            bill_data = _build_bill_data_from_dynamodb(table_id)
            if not bill_data:
                logger.warning(f"Could not build bill_data for table_id={table_id}")
                return {
                    "mode": "dynamodb",
                    "table_id": table_id,
                    "success": False,
                    "reason": "no_bill_data"
                }

            # Fetch latest policy
            policy_data = _get_latest_policy(bucket)
            if not policy_data:
                logger.warning("No parsed policies found for direct invocation")
                return {
                    "mode": "dynamodb",
                    "table_id": table_id,
                    "success": False,
                    "reason": "no_policy"
                }

            # Compare
            logger.info(f"Comparing DynamoDB bill for table_id={table_id} against latest policy")
            comparison_key = _compare_bill_to_policy(
                bill_data=bill_data,
                policy_data=policy_data,
                bucket=bucket,
                key=f"dynamodb:{table_id}",
                metadata=metadata
            )
            
            # 🔹 CLEANUP AFTER SUCCESSFUL COMPARISON
            if comparison_key:
                logger.info(f"Comparison successful. Starting cleanup for table_id={table_id}")
                cleanup_results = cleanup_all_data_for_table_id(table_id)
                logger.info(f"Cleanup results: {cleanup_results}")
            else:
                logger.warning(f"Comparison failed, skipping cleanup for table_id={table_id}")
                cleanup_results = None


            return {
                "mode": "dynamodb",
                "table_id": table_id,
                "success": comparison_key is not None,
                "comparison_key": comparison_key
            }

        # If neither Records nor table_id → nothing to do
        logger.info("Event has neither S3 Records nor table_id; nothing to process.")
        return {"results": []}

    finally:
        # Clean Lambda /tmp
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
            pass



