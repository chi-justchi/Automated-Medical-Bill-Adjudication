import boto3
import os
import logging
from typing import List, Dict, Optional
from boto3.dynamodb.conditions import Key
from datetime import datetime
from boto3.dynamodb.conditions import Attr



logger = logging.getLogger()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

# Table names from environment variables
LAMBDA2_TRACKING_TABLE = os.environ.get("LAMBDA2_TRACKING_TABLE", "lambda2_executions")
PATIENT_INFO_TABLE = os.environ.get("PATIENT_INFO_TABLE", "Patient_info")
MED_BILL_TABLE = os.environ.get("MED_BILL_TABLE", "temporary_med_bill2")
PROVIDER_TABLE = os.environ.get("PROVIDER_TABLE", "Provider_info")
TEMP_MED_BILL_TABLE = os.environ.get("TEMP_MED_BILL_TABLE", "temporary_patientMedicalBillInfo")
TEMP_ICD = os.environ.get("TEMP_ICD", "temporary_med_icd")

tracking_table = dynamodb.Table(LAMBDA2_TRACKING_TABLE)
patient_table = dynamodb.Table(PATIENT_INFO_TABLE)
med_bill_table = dynamodb.Table(MED_BILL_TABLE)
provider_table = dynamodb.Table(PROVIDER_TABLE)  # or whatever your table name is
medical_bill_table = dynamodb.Table(TEMP_MED_BILL_TABLE)
icd_temp_table = dynamodb.Table(TEMP_ICD)

# def get_latest_table_id() -> Optional[str]:
#     """
#     Fetch the most recent table_id from Lambda 2's tracking table.
#     Assumes the tracking table has a timestamp attribute for sorting.
#     """
#     try:
#         # Query or scan to get the most recent execution
#         response = tracking_table.scan(
#             Limit=50  # Get recent items
#         )
        
#         items = response.get('Items', [])
        
#         if not items:
#             logger.warning("No executions found in Lambda 2 tracking table")
#             return None
        
#         # Sort by timestamp (assuming timestamp field exists)
#         sorted_items = sorted(
#             items,
#             key=lambda x: x.get('timestamp', ''),
#             reverse=True
#         )
        
#         latest_item = sorted_items[0]
#         table_id = latest_item.get('table_id')
        
#         logger.info(f"Latest table_id from Lambda 2: {table_id}")
#         return table_id
        
#     except Exception as e:
#         logger.error(f"Error fetching latest table_id: {e}")
#         return None

def get_patient_info_by_table_id(table_id: str):
    """
    Fetch patient info from Patient_info table using table_id (non-key).
    Uses scan because table_id is not the PK.
    """
    try:
        response = patient_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"No patient info found for table_id: {table_id}")
            return None
        
        return items[0]
    
    except Exception as e:
        logger.error(f"Error scanning patient info by table_id: {e}")
        return None

def get_provider_info_by_table_id(table_id: str):
    """
    Fetch provider info from provider_info table using table_id (non-key).
    Uses scan because table_id is not the PK.
    """
    try:
        response = provider_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"No provider info found for table_id: {table_id}")
            return None
        
        return items[0]
    
    except Exception as e:
        logger.error(f"Error scanning provider info by table_id: {e}")
        return None

def get_medical_bill_info_by_table_id(table_id: str):
    """
    Fetch medical bill info from temporary_patientMedicalBillInfo table using table_id (PK).
    """
    try:
        response = medical_bill_table.get_item(
            Key={'table_id': table_id}
        )
        
        item = response.get('Item')
        
        if not item:
            logger.warning(f"No medical bill info found for table_id: {table_id}")
            return None
        
        return item
    
    except Exception as e:
        logger.error(f"Error getting medical bill info by table_id: {e}")
        return None

def get_charge_by_code(code: str, table_id: str):
    """
    Fetch charge amount from temporary_med_bill2 table using code (PK).
    """
    try:
        response = med_bill_table.get_item(
            Key={
                'code': code,  # partition key
                'table_id': table_id            # sort key
            }
        )
        
        item = response.get('Item')
        
        if not item:
            logger.warning(f"No charge found for code: {code}")
            return None
        
        return item
    
    except Exception as e:
        logger.error(f"Error getting charge by code: {e}")
        return None


def get_patient_info(table_id: str) -> Optional[Dict]:
    """
    Fetch patient information from Patient_info table using table_id as FK.
    """
    try:
        # Query using table_id as the key
        # response = patient_table.query(
        #     KeyConditionExpression=Key('table_id').eq(table_id)
        # )
        response = patient_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )

        print(f'response = {response}')
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"No patient info found for table_id: {table_id}")
            return None
        
        # Return the first matching record
        patient_data = items[0]
        
        logger.info(f"Patient data retrieved for table_id {table_id}: "
                   f"{patient_data.get('patient_name', 'Unknown')}")
        
        return patient_data
        
    except Exception as e:
        logger.error(f"Error fetching patient info: {e}")
        return None


def get_codes_for_table_id(table_id: str) -> List[Dict[str, str]]:
    """
    Fetch all CPT codes associated with a table_id from temporary_med_bill2.
    Returns a list of dicts with 'code' and 'description' keys.
    """    
    try:
        response = med_bill_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        
        # Handle pagination if there are many items
        while 'LastEvaluatedKey' in response:
            response = med_bill_table.query(
                KeyConditionExpression=Key('table_id').eq(table_id),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))
        
        # Extract code and description
        codes = []
        for item in items:
            if 'code' in item:
                codes.append({
                    'code': item['code'],
                    'description': item.get('description', ''),
                    'charge_amount': item.get('charge_amount', 0)
                })
        
        logger.info(f"Found {len(codes)} codes for table_id {table_id}")
        return codes
        
    except Exception as e:
        logger.error(f"Error fetching codes from DynamoDB: {e}")
        return []


##################################
# DELETION LOGIC
def delete_patient_info(table_id: str) -> bool:
    """
    Delete patient info record by table_id.
    Assumes patient_id is the primary key.
    """
    try:
        # First, find the record to get the primary key
        response = patient_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"No patient info found for table_id: {table_id}")
            return False
        
        # Delete each matching record (should be only one)
        for item in items:
            patient_id = item.get('patient_id')  # Assuming patient_id is the PK
            if patient_id:
                patient_table.delete_item(Key={'patient_id': patient_id})
                logger.info(f"Deleted patient_id: {patient_id} (table_id: {table_id})")
        
        return True
        
    except Exception as e:
        logger.error(f"Error deleting patient info for table_id {table_id}: {e}")
        return False


def delete_provider_info(table_id: str) -> bool:
    """
    Delete provider info record by table_id.
    Assumes provider_id is the primary key.
    """
    try:
        response = provider_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"No provider info found for table_id: {table_id}")
            return False
        
        for item in items:
            provider_id = item.get('provider_id')  # Assuming provider_id is the PK
            if provider_id:
                provider_table.delete_item(Key={'provider_id': provider_id})
                logger.info(f"Deleted provider_id: {provider_id} (table_id: {table_id})")
        
        return True
        
    except Exception as e:
        logger.error(f"Error deleting provider info for table_id {table_id}: {e}")
        return False


def delete_medical_bill_info(table_id: str) -> bool:
    """
    Delete medical bill info record by table_id (PK).
    """
    try:
        response = medical_bill_table.delete_item(
            Key={'table_id': table_id}
        )
        
        logger.info(f"Deleted medical bill info for table_id: {table_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting medical bill info for table_id {table_id}: {e}")
        return False


def delete_cpt_codes(table_id: str) -> bool:
    """
    Delete all CPT codes (from temporary_med_bill2) for a given table_id.
    Composite key: (code, table_id)
    """
    try:
        # Scan for all items with this table_id
        response = med_bill_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        deleted_count = 0
        
        # Handle pagination
        while True:
            for item in items:
                code = item.get('code')
                if code:
                    med_bill_table.delete_item(
                        Key={
                            'code': code,
                            'table_id': table_id
                        }
                    )
                    deleted_count += 1
            
            # Check for more pages
            if 'LastEvaluatedKey' in response:
                response = med_bill_table.scan(
                    FilterExpression=Attr('table_id').eq(table_id),
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                items = response.get('Items', [])
            else:
                break
        
        logger.info(f"Deleted {deleted_count} CPT codes for table_id: {table_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting CPT codes for table_id {table_id}: {e}")
        return False


def delete_icd_codes(table_id: str) -> bool:
    """
    Delete all ICD codes (from temporary_med_icd) for a given table_id.
    Composite key: (code, table_id)
    """
    try:
        response = icd_temp_table.scan(
            FilterExpression=Attr('table_id').eq(table_id)
        )
        
        items = response.get('Items', [])
        deleted_count = 0
        
        # Handle pagination
        while True:
            for item in items:
                code = item.get('code')
                if code:
                    icd_temp_table.delete_item(
                        Key={
                            'code': code,
                            'table_id': table_id
                        }
                    )
                    deleted_count += 1
            
            if 'LastEvaluatedKey' in response:
                response = icd_temp_table.scan(
                    FilterExpression=Attr('table_id').eq(table_id),
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                items = response.get('Items', [])
            else:
                break
        
        logger.info(f"Deleted {deleted_count} ICD codes for table_id: {table_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting ICD codes for table_id {table_id}: {e}")
        return False


def cleanup_all_data_for_table_id(table_id: str) -> Dict[str, bool]:
    """
    Delete ALL data associated with a table_id from all temporary tables.
    Returns a dict showing success/failure for each table.
    """
    results = {
        'patient_info': False,
        'provider_info': False,
        'medical_bill_info': False,
        'cpt_codes': False,
        'icd_codes': False
    }
    
    logger.info(f"Starting cleanup for table_id: {table_id}")
    
    # Delete from all tables
    results['patient_info'] = delete_patient_info(table_id)
    results['provider_info'] = delete_provider_info(table_id)
    results['medical_bill_info'] = delete_medical_bill_info(table_id)
    results['cpt_codes'] = delete_cpt_codes(table_id)
    results['icd_codes'] = delete_icd_codes(table_id)
    
    # Log summary
    success_count = sum(results.values())
    logger.info(f"Cleanup complete for table_id {table_id}: "
                f"{success_count}/5 operations successful")
    
    return results