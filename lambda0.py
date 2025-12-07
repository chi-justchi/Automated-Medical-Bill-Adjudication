import json
import boto3
import base64
import os
import io

s3 = boto3.client('s3')
BUCKET_NAME = "farhantest01"

def lambda_handler(event, context):
    try:
        body = json.loads(event['body'])
        file_name = body['file_name']
        file_content = body['file_content'] # base64 encoded
        job_id = body.get('job_id')

        if not file_name or not file_content or not job_id:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing job_id, file_name or file_content"})
            }

        # if statement to check if its not a PDF document it returns a message
        if not file_name.lower().endswith(".pdf"):
            return {
                "statusCode":  400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Invalid file type. Only PDF files are allowed."})
            }

        # decode file content
        file_bytes = base64.b64decode(file_content)

        num_pages = file_bytes.count(b'/Type /Page')

        # if statement to check if the number of pages exceeds 3
        if num_pages > 3:
            return {
                "statusCode":  400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Too many pages. Maximum 3 pages allowed."})
            }

        # Upload to S3
        metadata = {
            "job_id": job_id
        }

        s3_key = file_name
        s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=file_bytes, ContentType="application/pdf",Metadata=metadata)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": f"File {file_name} uploaded successfully. Job ID: {job_id}"})
        }

    except Exception as e:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": str(e)})
            }
