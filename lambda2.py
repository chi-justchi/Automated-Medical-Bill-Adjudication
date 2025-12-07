import json
import os
import boto3
import logging
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from typing import List, Dict, Optional, Tuple, Any

# -------------------------------------------------------------------
# AWS & logging setup
# -------------------------------------------------------------------
region_name = "us-east-2"

logger = logging.getLogger()
logger.setLevel(logging.INFO)
_MAX_LOG_CHUNK = 60000  # reserved for potential large-log helpers

# Core AWS clients/resources
dynamodb = boto3.resource("dynamodb", region_name)
bedrock = boto3.client("bedrock-runtime", region_name)
lambda_client = boto3.client("lambda", region_name=region_name)

# Name/ARN for downstream Lambda in the adjudication pipeline
NEXT_LAMBDA_NAME = os.environ.get("Lambda_3")

# -------------------------------------------------------------------
# DynamoDB tables
# -------------------------------------------------------------------
# Line items (CPT etc.) for a given bill, keyed by code + table_id
med_bill_table = dynamodb.Table("temporary_med_bill2")

# Temporary ICD codes extracted from the bill, linked via table_id
icd_temp_table = dynamodb.Table("temporary_med_icd")

# Reference CPT code table: authoritative codes + descriptions
reference_table = dynamodb.Table("reference_table")

# Reference ICD table: authoritative ICD codes + descriptions
icd_reference_table = dynamodb.Table("icd_10_reference_table")

# Token budget for Bedrock responses
MAX_TOKENS = 100


# -------------------------------------------------------------------
def trigger_next_lambda(previous_event, validation_result, cpt_codes):
    """
    Fire-and-forget invocation of the next Lambda in the pipeline.

    - Takes the original event (from upstream Lambda),
      the validation_result produced here, and the list of CPT codes.
    - Attaches `validation` and `cpt_codes` to the payload.
    - Invokes NEXT_LAMBDA_NAME asynchronously (InvocationType="Event").
    """
    if not NEXT_LAMBDA_NAME:
        print("TARGET_NEXT_LAMBDA_NAME not set; skipping next-lambda trigger.")
        return

    # Preserve as much of the original event as possible to keep context
    if isinstance(previous_event, dict):
        payload = dict(previous_event)
        payload["validation"] = validation_result
    else:
        payload = {"original_event": previous_event, "validation": validation_result}

    # Always pass CPT list so downstream stages can display them or reuse them
    payload["cpt_codes"] = cpt_codes

    print(f"Triggering {NEXT_LAMBDA_NAME} with payload: {json.dumps(payload)}")

    try:
        lambda_client.invoke(
            FunctionName=NEXT_LAMBDA_NAME,
            InvocationType="Event",  # async, no need to wait for next Lambda
            Payload=json.dumps(payload).encode("utf-8"),
        )
    except Exception as e:
        # Trigger failure does not crash this Lambda; we just log it
        print(f"Error triggering next lambda {NEXT_LAMBDA_NAME}: {e}")


# -------------------------------------------------------------------
def get_cpt_codes_for_table_id(table_id: str) -> List[Dict[str, str]]:
    """
    Fetch all CPT-like entries from med_bill_table for a given table_id.

    Returns:
        A list of dicts: [{"code": "...", "description": "..."}, ...]
        - Uses a Scan with FilterExpression on table_id.
        - Handles pagination with LastEvaluatedKey.
    """
    try:
        # Initial scan filtered by table_id
        response = med_bill_table.scan(
            FilterExpression=Attr("table_id").eq(table_id)
        )
        items = response.get("Items", [])

        # Paginate through all results if more than 1 page
        while "LastEvaluatedKey" in response:
            response = med_bill_table.scan(
                FilterExpression=Attr("table_id").eq(table_id),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        codes = []
        for item in items:
            # Only build entries that have a "code" field
            if "code" in item:
                codes.append({
                    "code": item["code"],
                    "description": item.get("description", "")
                })

        return codes

    except Exception as e:
        print(f"Error fetching CPT codes: {e}")
        return []


# -------------------------------------------------------------------
def get_icd_entries_for_table_id(table_id: str) -> List[Dict[str, Optional[str]]]:
    """
    Fetch ICD entries from the temporary ICD table for a given table_id.

    Expected item shape:
        { "code": "...", "table_id": "...", "description": "..." }

    Returns:
        A list of dicts: [{"code": "...", "description": "... or None"}, ...]
        - Uses a Scan with FilterExpression on table_id.
        - Handles pagination with LastEvaluatedKey.
    """
    try:
        response = icd_temp_table.scan(
            FilterExpression=Attr("table_id").eq(table_id)
        )
        items = response.get("Items", [])

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = icd_temp_table.scan(
                FilterExpression=Attr("table_id").eq(table_id),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        icd_entries = []
        for item in items:
            # Only accept items that actually have a 'code'
            if "code" in item:
                icd_entries.append({
                    "code": item["code"],
                    "description": item.get("description")
                })

        return icd_entries

    except Exception as e:
        print(f"Error fetching ICD entries: {e}")
        return []


# -------------------------------------------------------------------
def get_reference_cpt_code(code: str):
    """
    Look up a CPT code in the reference_table.

    Returns:
        {"code": "...", "description": "..."} if found, else None.
        - Uses a direct GetItem with PK = code.
    """
    try:
        response = reference_table.get_item(Key={"code": code})
        item = response.get("Item")
        if not item:
            return None
        return {"code": item["code"], "description": item.get("description", "")}
    except Exception:
        # On any error (network, missing table, etc.) just treat as not found
        return None


def get_reference_icd_code(icd_code: str):
    """
    Look up an ICD code in the icd_reference_table.

    Returns:
        {"code": "...", "description": "..."} if found, else None.
        - Uses a direct GetItem with PK = code.
    """
    try:
        response = icd_reference_table.get_item(Key={"code": icd_code})
        item = response.get("Item")
        if not item:
            return None
        return {"code": item["code"], "description": item.get("description", "")}
    except Exception:
        # On any error, treat as if reference entry does not exist
        return None


# -------------------------------------------------------------------
def batch_compare_with_bedrock(pairs: List[Tuple[str, str]], label: str):
    """
    Compare multiple (description_A, description_B) pairs using a single Bedrock call.

    Args:
        pairs: list of (desc_from_bill, desc_from_reference) tuples.
        label: "CPT" or "ICD" (used in the instructions).

    Returns:
        List[Optional[bool]]:
          - True  => pair deemed equivalent
          - False => pair not equivalent
          - None  => model response could not be interpreted or an error occurred

    Design:
      - We build a numbered list of pairs.
      - Prompt the model to respond with a JSON list like ["YES","NO",...].
      - Parse and normalize each element to boolean/None.
    """
    if not pairs:
        return []

    # Build pair text to feed into the model (1-based numbered list)
    lines = []
    for idx, (d1, d2) in enumerate(pairs, start=1):
        lines.append(f"{idx}. Description A: {d1}")
        lines.append(f"   Description B: {d2}")

    prompt = f"""
You are a medical coding expert.
Determine whether each pair of {label} descriptions are equivalent. They may have different wordings and abbreviations, but as long as they deliver similar message, it should be valid. For example, for CPT codes: "Left Foot X-ray test" and "X-ray examination of foot" delivers similar message and should be determined valid.
But also, do not be too lenient. For example for ICD codes: "Chest pain on breathing" and "Heart disease" should not be determined to be giving similar message.
Respond with ["YES","NO",...] only.
Pairs:
{chr(10).join(lines)}
"""

    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        })

        # Single Bedrock model invocation for all pairs
        response = bedrock.invoke_model(
            modelId=os.environ.get("MODEL_ID"),
            body=body,
        )

        # Expect a JSON-encoded array of strings like ["YES","NO",...]
        response_body = json.loads(response["body"].read())
        text = response_body["content"][0]["text"].strip()

        decisions = json.loads(text)

        results = []
        for val in decisions:
            s = str(val).upper()
            if s.startswith("Y"):
                results.append(True)
            elif s.startswith("N"):
                results.append(False)
            else:
                # Unable to interpret this element; mark as None
                results.append(None)

        return results

    except Exception:
        # If the entire call fails, we return a list of None aligned with `pairs`
        return [None] * len(pairs)


# -------------------------------------------------------------------
def check_cpt_justification_with_bedrock(cpt_codes, icd_codes):
    """
    Ask Bedrock whether each CPT is medically justified by at least one ICD.

    Args:
        cpt_codes: list of {"code": "...", "description": "..."} from bill.
        icd_codes: list of {"code": "...", "description": "..."} for justification.

    Returns:
        (justified, message)
        - justified == True  => all CPTs justified; message is None
        - justified == False => some CPTs not justified; message is short explanation
        - justified == None  => Bedrock error; message is error string
    """
    # Construct human-readable lists for the model
    cpt_text = "\n".join([f"- CPT {c['code']}: {c['description']}" for c in cpt_codes])
    icd_text = "\n".join([f"- ICD {i['code']}: {i['description']}" for i in icd_codes])

    prompt = f"""
You are a medical coding expert.
ICD diagnoses:
{icd_text}

CPT services:
{cpt_text}

Determine whether EVERY CPT is medically justified by at least one ICD.
If all are justified, respond with: OK
Otherwise respond with: ISSUE: <short reason>.
"""

    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        })

        response = bedrock.invoke_model(
            modelId=os.environ.get("MODEL_ID"),
            body=body
        )

        text = json.loads(response["body"].read())["content"][0]["text"].strip()

        # Normalize the decision:
        if text.upper().startswith("OK"):
            return True, None
        else:
            # Any non-OK response is treated as an issue; return text verbatim
            return False, text

    except Exception as e:
        # If Bedrock fails, surface the error but don't hard-crash the whole Lambda
        return None, str(e)


# -------------------------------------------------------------------
def lambda_handler(event, context):
    """
    Lambda entrypoint for validation stage.

    Responsibilities:
      - Read table_id from event.
      - Fetch temporary ICD and CPT entries for that table_id.
      - Compare ICD descriptions against ICD reference table (via Bedrock).
      - Compare CPT descriptions against CPT reference table (via Bedrock).
      - Check that CPT codes are justified by (valid) ICD codes (via Bedrock).
      - Aggregate issues and all_valid flag.
      - Pass validation_result and CPT codes to NEXT_LAMBDA_NAME.

    Returns:
      bool: all_valid (True if all checks passed, False otherwise).
    """
    all_valid = True          # Global flag tracking if everything is valid
    issues = []               # Accumulates human-readable issue strings
    cpt_icd_issue = None      # Holds any CPT/ICD justification issue text
    cpt_codes = []            # CPTs found for this table_id (passed downstream)

    print("Event:", json.dumps(event))

    try:
        table_id = event.get("table_id")
        if not table_id:
            # table_id is mandatory to continue; fail and trigger next lambda with error state
            issues.append("Missing table_id in event.")
            validation_result = {"table_id": None, "all_valid": False, "issues": issues}
            trigger_next_lambda(event, validation_result, [])
            return False

        # --------------------- ICD extraction & validation ---------------------
        icd_entries = get_icd_entries_for_table_id(table_id)

        # This will hold ICDs (with chosen descriptions) that we use for CPT justification
        icd_for_justification = []

        if not icd_entries:
            issues.append(f"No ICD entries found for table_id {table_id}")
        else:
            icd_pairs = []                 # (bill_description, ref_description) for Bedrock
            icd_items_for_validation = []  # structured tracking of each pair

            for entry in icd_entries:
                icd_code = entry["code"]
                icd_desc = entry.get("description")

                # Look up the ICD code in the reference table
                ref_icd = get_reference_icd_code(icd_code)

                if ref_icd:
                    ref_desc = ref_icd["description"]

                    if icd_desc:
                        # Will be compared via Bedrock
                        icd_items_for_validation.append({
                            "code": icd_code,
                            "icd_desc": icd_desc,
                            "ref_desc": ref_desc
                        })
                        icd_pairs.append((icd_desc, ref_desc))
                    else:
                        # No temp description; rely entirely on reference description
                        icd_for_justification.append({
                            "code": icd_code,
                            "description": ref_desc
                        })
                else:
                    # ICD is not in reference table
                    if icd_desc:
                        issues.append(
                            f"ICD {icd_code} not found in reference; using temporary description."
                        )
                        icd_for_justification.append({
                            "code": icd_code,
                            "description": icd_desc
                        })
                    else:
                        # No ref entry and no temp description → cannot use this ICD for justification
                        issues.append(
                            f"ICD {icd_code} missing description and not in reference; skipping."
                        )

            # Bedrock validation for ICD descriptions (only those with both temp+reference descriptions)
            if icd_pairs:
                results = batch_compare_with_bedrock(icd_pairs, "ICD")
                for item, result in zip(icd_items_for_validation, results):
                    icd_code = item["code"]
                    ref_desc = item["ref_desc"]

                    if result is False:
                        # Description mismatch between bill and reference
                        issues.append(f"ICD {icd_code} description mismatch.")
                        all_valid = False
                        # Still use the reference description for justification checks
                        icd_for_justification.append({"code": icd_code, "description": ref_desc})
                    else:
                        # If result True or None, we fall back to reference description for justification
                        icd_for_justification.append({"code": icd_code, "description": ref_desc})

        # --------------------- CPT extraction & ICD justification ---------------------
        cpt_codes = get_cpt_codes_for_table_id(table_id)

        if not cpt_codes:
            issues.append("No CPT codes found.")
            all_valid = False
        else:
            if icd_for_justification:
                # Ask Bedrock if each CPT is justified by at least one ICD
                justified, msg = check_cpt_justification_with_bedrock(
                    cpt_codes, icd_for_justification
                )
                if justified is False:
                    # Model explicitly says some CPTs are not justified
                    issues.append(msg)
                    cpt_icd_issue = msg
                    all_valid = False
                elif justified is None:
                    # Model call failed
                    issues.append("Bedrock error during CPT justification.")
            else:
                # No ICDs at all that we can trust/use
                issues.append("No ICD codes available to justify CPTs.")

        # --------------------- CPT reference validation ---------------------
        cpt_pairs = []                # (bill_desc, reference_desc)
        cpt_items_for_validation = [] # structured metadata for each pair

        for item in cpt_codes:
            code = item["code"]
            desc = item.get("description", "")

            # Look up CPT in reference table
            ref = get_reference_cpt_code(code)
            if not ref:
                issues.append(f"CPT {code} not found in CPT reference table.")
                continue

            ref_desc = ref["description"]
            cpt_items_for_validation.append({
                "code": code,
                "description": desc,
                "ref_description": ref_desc
            })
            cpt_pairs.append((desc, ref_desc))

        # Only call Bedrock if there are pairs to validate
        if cpt_pairs:
            results = batch_compare_with_bedrock(cpt_pairs, "CPT")
            for item, result in zip(cpt_items_for_validation, results):
                if result is False:
                    # Description mismatch between claim and reference for this CPT
                    issues.append(f"CPT {item['code']} description mismatch.")
                    all_valid = False

        # --------------------- Final aggregation & chaining ---------------------
        validation_result = {
            "table_id": table_id,
            "all_valid": all_valid,
            "issues": issues,
            "cpt_icd_justification_issue": cpt_icd_issue,
        }

        # Hand off results + CPT codes to the next Lambda
        trigger_next_lambda(event, validation_result, cpt_codes)
        return all_valid

    except Exception as e:
        # Any unexpected exception is treated as a failed validation
        issues.append(str(e))
        # table_id may not exist if the failure happened very early
        trigger_next_lambda(event, {"table_id": table_id, "all_valid": False, "issues": issues}, [])
        return False
