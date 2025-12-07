import boto3
import json
from botocore.exceptions import ClientError

s3 = boto3.client('s3')
BUCKET_NAME = 'chitest02'

# Prefix (folder path)
PREFIX = 'parsed/comparisons/'


def lambda_handler(event, context):
    try:

        job_id = event.get('queryStringParameters', {}).get('jobId')

        if not job_id:
            return {
                'statusCode': 400,
                'headers': {"Content-Type": "application/json"},
                'body': json.dumps({"error": "Missing jobId parameter"})
            }
        # A dictionary that contains all objects with the given prefix
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=PREFIX)

        # if statement to check if there are no objects in response
        if 'Contents' not in response or len(response['Contents']) == 0:
            return {
                'statusCode': 404,
                'headers': {"Content-Type": "application/json"},
                'body': json.dumps({"error": "no files found"})
            }


        
        matched_key = None

        # Loop through each object in the response
        for obj in response['Contents']: 
            key = obj['Key']

            if key.endswith("/"):
                continue
            
            head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
            metadata = head.get('Metadata', {})

            if metadata.get('job_id') == job_id:
                matched_key = key
                break

        # If statement to check if there is no files exist
        if not matched_key:
            return {
                'statusCode': 404,
                'headers': {"Content-Type": "application/json"},
                'body': json.dumps({"error": "No file matches jobId"})
            }

        
        # Retrieve the matched S3 object
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=matched_key) # Get the S3 object
        file_data = obj['Body'].read().decode('utf-8') # Read and decode the file contents
        json_data = json.loads(file_data) # Parses the content as JSON

        s3.delete_object(Bucket=BUCKET_NAME, Key=matched_key) # Delete the S3 object

        return {
            'statusCode': 200,
            'headers': {"Content-Type": "application/json"},
            'body': json.dumps(json_data)
        }

    # Handle AWS ClientError exceptions
    except ClientError as e:
        # if statement to check if the error is NoSuchKey
        if e.response['Error']['Code'] == 'NoSuchKey':
            return {
                'statusCode': 404,
                'headers': {"Content-Type": "application/json"},
                'body': json.dumps({"error": "file not ready yet"})
            }
        # Handle other ClientError exceptions
        else:
            return {
                    'statusCode': 500,
                    'headers': {"Content-Type": "application/json"},
                    'body': json.dumps({"error": str(e)})
                }






