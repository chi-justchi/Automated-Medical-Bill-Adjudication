# Medical Bill Adjudication System

A comprehensive, cloud-native solution for automated medical bill processing, validation, and adjudication using AWS Lambda, DynamoDB, Bedrock AI, and a React frontend.

## 📋 Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Project Structure](#project-structure)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Setup Instructions](#setup-instructions)
- [Lambda Functions](#lambda-functions)
- [Frontend Application](#frontend-application)
- [Database Schema](#database-schema)
- [API Documentation](#api-documentation)
- [Development Guide](#development-guide)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Medical Bill Adjudication System is an intelligent pipeline designed to:

1. **Accept** medical bills (PDFs) from users
2. **Extract** structured data using AI (patient info, procedures, diagnoses, costs)
3. **Validate** extracted data against medical coding standards (CPT, ICD-10)
4. **Compare** bills against insurance policies
5. **Adjudicate** claims to determine coverage and payment

The system leverages AWS Bedrock's Claude AI model for intelligent document parsing and validation, ensuring accuracy and consistency throughout the adjudication process.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         React Frontend (SPA)                         │
│              (Upload Bills, View Results, User Guide)               │
└────────────┬────────────────────────────────────────────────────────┘
             │ HTTP/REST API
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      API Gateway (AWS)                              │
│              Routes requests to Lambda functions                    │
└────────────┬────────────────────────────────────────────────────────┘
             │
    ┌────────┼────────┬────────┐
    ▼        ▼        ▼        ▼
┌────────┐┌────────┐┌────────┐┌────────┐
│Lambda 0││Lambda 1││Lambda 2││Lambda 4│
│Intake  ││Extract ││Validate││Results │
└─┬──────┘└───┬────┘└───┬────┘└───┬────┘
  │           │         │        │
  │ S3        │ S3      │ S3     │ S3
  │ Upload    │ Store   │ Store  │ Retrieve
  ▼           ▼         ▼        ▼
┌──────────────────────────────────────┐
│          AWS S3 Storage              │
│  - Raw PDFs   - Parsed Data          │
│  - Results    - Comparisons          │
└──────────────────────────────────────┘

        ┌──────────────────────────────┐
        │      Lambda 3 (Optional)     │
        │  Policy & Patient Fetching   │
        └──────────────────────────────┘

┌────────────────────────────────────────┐
│         DynamoDB Tables                │
│  - Patient Info       - Temp ICD-10    │
│  - Provider Info      - Reference CPT  │
│  - Bills & Items      - Reference ICD  │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│      AWS Bedrock (Claude AI)           │
│  - Document extraction                 │
│  - Description comparison              │
│  - Justification analysis              │
└────────────────────────────────────────┘
```

### Data Flow

```
User Upload (PDF)
       │
       ▼
   Lambda 0: Validate PDF
       │ (Checks format, size, page count)
       ├─ Reject if invalid
       ▼
   Upload to S3 → Trigger Lambda 1
       │
       ▼
   Lambda 1: Extract Data with Bedrock
       │ (Patient, Hospital, Bills, ICD-10, CPT codes)
       ├─ Parse PDF using Claude AI
       ├─ Store in DynamoDB tables
       ▼
   Trigger Lambda 2
       │
       ▼
   Lambda 2: Validate & Compare
       │ (Compare extracted data against reference tables)
       ├─ Validate ICD codes
       ├─ Validate CPT codes
       ├─ Check CPT/ICD justification
       ▼
   Trigger Lambda 3 (Optional)
       │
       ▼
   Lambda 3: Fetch Additional Data
       │ (Patient policies, provider info)
       ├─ Retrieve from external systems
       ▼
   Store Results in S3 → Lambda 4 retrieves for frontend
       │
       ▼
   Frontend displays adjudication results to user
```

---

## Project Structure

```
MedicalBillAdjudicatin/
├── README.md                          # This file
│
├── front-end/                         # React SPA
│   ├── package.json                   # Dependencies
│   ├── public/
│   │   ├── index.html
│   │   ├── manifest.json
│   │   └── robots.txt
│   └── src/
│       ├── App.js                     # Main routing component
│       ├── App.css
│       ├── Navbar.js                  # Navigation component
│       ├── Navbar.css
│       ├── Homepage.js                # Landing page
│       ├── Uploadpage.js              # PDF upload & results
│       ├── Uploadpage.css
│       ├── UserGuidepage.js           # Help & documentation
│       ├── index.js
│       ├── index.css
│       ├── reportWebVitals.js
│       └── setupTests.js
│
├── lambda0.py                         # Intake & File Validation
├── lambda1.py                         # Data Extraction (Bedrock)
├── lambda2.py                         # Validation & Comparison
├── lambda4.py                         # Results Retrieval
│
└── lambda3/                           # Adjudication & Policy Matching
    ├── index.py                       # Main handler
    ├── fetchPatientData.py            # Patient/Policy queries
    ├── parsingBills.py                # Bill parsing utilities
    ├── parsingPolicies.py             # Policy parsing utilities
    └── testingKnowledgeBase.py        # Testing utilities
```

---

## Features

### Core Functionality

- ✅ **PDF Upload & Validation**: Accepts medical bills up to 3 pages as PDFs
- ✅ **Intelligent Document Parsing**: Uses AWS Bedrock Claude AI to extract:
  - Patient information (name, age, contact, address)
  - Hospital/provider information
  - Medical billing items with CPT codes
  - Medical diagnoses with ICD-10 codes
  - Billing amounts and totals
- ✅ **Medical Coding Validation**:
  - Validates CPT (Current Procedural Terminology) codes
  - Validates ICD-10 (International Classification of Diseases) codes
  - Compares extracted data against authoritative reference tables
- ✅ **Clinical Justification Check**:
  - Ensures CPT procedures are medically justified by associated ICD-10 diagnoses
  - Uses AI to semantically compare descriptions
- ✅ **Batch Processing**: Efficiently processes multiple code pairs using single Bedrock invocations
- ✅ **Results Storage & Retrieval**: Stores adjudication results in S3 with metadata tracking
- ✅ **Error Handling**: Comprehensive error handling with graceful degradation
- ✅ **Retry Logic**: Exponential backoff with jitter for transient failures

### Frontend Features

- 📄 **Intuitive UI**: Easy-to-use interface for bill uploads
- 🔄 **Real-time Status**: Polling mechanism to fetch results as they become available
- 📊 **Results Display**: Shows extraction and validation results in structured format
- 📖 **User Guide**: Help documentation and usage instructions
- 🎨 **Responsive Design**: Mobile-friendly interface

---

## Technology Stack

### Backend

- **AWS Lambda**: Serverless compute for pipeline orchestration
- **AWS S3**: Blob storage for PDFs and results
- **AWS DynamoDB**: NoSQL database for structured data
- **AWS Bedrock**: Managed AI service (Claude 3.5 Sonnet)
- **Python 3.12+**: Lambda runtime

### Frontend

- **React 19.1**: UI framework
- **React Router 7.9**: Client-side routing
- **AWS SDK (S3)**: Direct S3 integration for uploads
- **UUID**: Job tracking
- **Jest & React Testing Library**: Testing

### Infrastructure

- **AWS API Gateway**: REST API endpoints
- **AWS CloudWatch**: Logging and monitoring
- **AWS IAM**: Access control

---

## Prerequisites

### AWS Account Requirements

- S3 buckets configured (`farhantest01` for uploads, `chitest02` for results)
- DynamoDB tables created (see [Database Schema](#database-schema))
- Lambda execution role with appropriate permissions
- Bedrock access enabled in your region
- API Gateway endpoints configured

### Local Development

- Python 3.12+
- Node.js 18+ and npm
- AWS CLI configured with credentials
- Git

### Python Dependencies

```
boto3
botocore
```

### Node.js Dependencies

See `front-end/package.json` for complete list:

- react, react-dom, react-router-dom
- @aws-sdk/client-s3
- @testing-library/react, @testing-library/jest-dom
- uuid

---

## Setup Instructions

### Backend Setup

#### 1. Create DynamoDB Tables

```bash
# Run these AWS CLI commands to create required tables

# Patient Info Table
aws dynamodb create-table \
  --table-name Patient_info \
  --attribute-definitions AttributeName=patient_id,AttributeType=S \
  --key-schema AttributeName=patient_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Provider Info Table
aws dynamodb create-table \
  --table-name Provider_info \
  --attribute-definitions AttributeName=provider_id,AttributeType=S \
  --key-schema AttributeName=provider_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Medical Bill Items Table (CPT codes)
aws dynamodb create-table \
  --table-name temporary_med_bill2 \
  --attribute-definitions \
    AttributeName=code,AttributeType=S \
    AttributeName=table_id,AttributeType=S \
  --key-schema \
    AttributeName=code,KeyType=HASH \
    AttributeName=table_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

# Temporary ICD-10 Codes Table
aws dynamodb create-table \
  --table-name temporary_med_icd \
  --attribute-definitions \
    AttributeName=code,AttributeType=S \
    AttributeName=table_id,AttributeType=S \
  --key-schema \
    AttributeName=code,KeyType=HASH \
    AttributeName=table_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

# Reference CPT Codes Table
aws dynamodb create-table \
  --table-name reference_table \
  --attribute-definitions AttributeName=code,AttributeType=S \
  --key-schema AttributeName=code,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# Reference ICD-10 Codes Table
aws dynamodb create-table \
  --table-name icd_10_reference_table \
  --attribute-definitions AttributeName=code,AttributeType=S \
  --key-schema AttributeName=code,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

#### 2. Create Lambda Functions

For each Lambda (`lambda0.py`, `lambda1.py`, `lambda2.py`, `lambda4.py`):

```bash
# Create deployment package
zip lambda_function.zip lambda_name.py

# Create Lambda function
aws lambda create-function \
  --function-name function-name \
  --runtime python3.12 \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-execution-role \
  --handler lambda_name.lambda_handler \
  --zip-file fileb://lambda_function.zip \
  --environment Variables={AWS_REGION=us-east-2,MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0}

# For Lambda 3 (includes dependencies)
cd lambda3/
pip install -r requirements.txt -t .
zip -r ../lambda3_function.zip .
aws lambda create-function \
  --function-name lambda-3 \
  --runtime python3.12 \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-execution-role \
  --handler index.lambda_handler \
  --zip-file fileb://../lambda3_function.zip
```

#### 3. Set Environment Variables

```bash
# For Lambda 1
aws lambda update-function-configuration \
  --function-name lambda-1 \
  --environment Variables='{
    AWS_REGION=us-east-2,
    MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0,
    PATIENT_TABLE=Patient_info,
    PROVIDER_TABLE=Provider_info,
    BILL_TABLE=temporary_patientMedicalBillInfo,
    BILL_ITEMS_TABLE=temporary_med_bill2,
    ICD10_TABLE=temporary_med_icd,
    Lambda_2=lambda-2,
    DOC_MAX_TOKENS=4500,
    MAX_RETRIES=8
  }'

# Similar for Lambda 2 and Lambda 3
```

#### 4. Configure Lambda Triggers

```bash
# Lambda 1 triggers on S3 PUT events
aws s3api put-bucket-notification-configuration \
  --bucket farhantest01 \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [{
      "LambdaFunctionArn": "arn:aws:lambda:us-east-2:ACCOUNT_ID:function:lambda-1",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {"Key": {"FilterRules": [{"Name": "suffix", "Value": "pdf"}]}}
    }]
  }'
```

#### 5. Set Lambda Permissions

```bash
# Allow S3 to invoke Lambda 1
aws lambda add-permission \
  --function-name lambda-1 \
  --statement-id AllowS3Invoke \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::farhantest01

# Allow Lambda 1 to invoke Lambda 2
aws lambda add-permission \
  --function-name lambda-2 \
  --statement-id AllowLambda1Invoke \
  --action lambda:InvokeFunction \
  --principal lambda.amazonaws.com \
  --source-arn arn:aws:lambda:us-east-2:ACCOUNT_ID:function:lambda-1
```

### Frontend Setup

#### 1. Install Dependencies

```bash
cd front-end
npm install
```

#### 2. Configure API Endpoints

Edit `front-end/src/Uploadpage.js` and update:

```javascript
const API_URL =
  "https://YOUR_API_GATEWAY_ID.execute-api.us-east-2.amazonaws.com/upload";
const API_GET_URL =
  "https://YOUR_API_GATEWAY_ID.execute-api.us-east-2.amazonaws.com/testjson";
```

#### 3. Build and Deploy

```bash
# Development
npm start

# Production build
npm run build

# Deploy to AWS S3 + CloudFront
aws s3 sync build/ s3://your-frontend-bucket/ --delete
```

---

## Lambda Functions

### Lambda 0: Intake & File Validation

**File**: `lambda0.py`

**Purpose**: First entry point for PDF uploads. Validates file format and size.

**Responsibilities**:

- Validates that the uploaded file is a PDF
- Checks file size constraints
- Verifies page count (max 3 pages)
- Stores metadata (job_id) in S3 object metadata
- Uploads validated PDF to S3 bucket

**Input** (from API Gateway):

```json
{
  "file_name": "medical_bill.pdf",
  "file_content": "base64_encoded_pdf_data",
  "job_id": "uuid_from_frontend"
}
```

**Output**:

```json
{
  "statusCode": 200,
  "body": {
    "message": "File uploaded successfully",
    "job_id": "uuid"
  }
}
```

**Error Handling**:

- 400: Invalid file type, missing parameters, too many pages
- 500: S3 upload failures

**Triggers**: Lambda 1 when PDF is successfully uploaded to S3

---

### Lambda 1: Data Extraction with AI

**File**: `lambda1.py`

**Purpose**: Intelligent extraction of structured data from medical bills using AWS Bedrock.

**Responsibilities**:

- Retrieves PDF from S3
- Encodes PDF in base64 format
- Invokes Bedrock Claude AI with full document extraction prompt
- Parses AI response as JSON
- Stores extracted data in DynamoDB tables:
  - Patient information
  - Hospital/provider information
  - Medical bill items (CPT codes)
  - ICD-10 diagnoses
- Generates unique `table_id` for the bill
- Triggers Lambda 2 for validation

**Extracted Data Structure**:

```json
{
  "patient_info": {
    "firstname": "John",
    "lastname": "Doe",
    "age": 45,
    "phone": "555-1234",
    "address": "123 Main St",
    "city": "Columbus",
    "state": "OH",
    "zipcode": "43215"
  },
  "hospital_info": {
    "name": "General Hospital",
    "phone": "555-5678",
    "address": "456 Hospital Dr",
    "city": "Columbus",
    "state": "OH",
    "zipcode": "43216"
  },
  "medical_bill_info": {
    "items": [
      { "code": "99213", "description": "Office visit", "bill": 150.0 },
      { "code": "99214", "description": "Extended visit", "bill": 250.0 }
    ],
    "subtotal": 400.0,
    "discount": 50.0,
    "tax_rate_percent": 5.0,
    "total_tax": 17.5,
    "balance_due": 367.5
  },
  "icd_10_codes": [{ "code": "I10", "description": "Essential hypertension" }]
}
```

**Bedrock Configuration**:

- Model: Claude 3.5 Sonnet
- Max tokens: 4500
- Temperature: 0 (deterministic)
- Retry strategy: Exponential backoff (max 8 retries)

**Error Handling**:

- Automatic retry on throttling/timeouts
- Graceful fallback on persistent failures
- Detailed CloudWatch logging

---

### Lambda 2: Validation & Comparison

**File**: `lambda2.py`

**Purpose**: Validates extracted data against reference tables and ensures medical justification.

**Responsibilities**:

- Fetches extracted CPT and ICD codes from DynamoDB
- Compares CPT descriptions against reference CPT table using Bedrock
- Compares ICD descriptions against reference ICD table using Bedrock
- Validates that CPT codes are medically justified by ICD diagnoses
- Aggregates issues and validation status
- Triggers Lambda 3 (or next pipeline stage)

**Validation Process**:

1. **ICD Validation**:

   - Retrieves temporary ICD codes from `temporary_med_icd` table
   - Looks up each ICD code in `icd_10_reference_table`
   - Uses Bedrock to compare descriptions for semantic equivalence
   - Flags discrepancies

2. **CPT Validation**:

   - Retrieves CPT codes from `temporary_med_bill2` table
   - Looks up each CPT code in `reference_table`
   - Uses Bedrock to compare descriptions for semantic equivalence
   - Flags discrepancies

3. **Justification Check**:
   - Uses Bedrock to verify each CPT is medically justified by ≥1 ICD
   - Ensures clinical appropriateness

**Bedrock Batch Comparison**:

```json
{
  "pairs": [
    {
      "description_a": "Office visit, established patient",
      "description_b": "Office consultation"
    },
    {
      "description_a": "Extended office visit",
      "description_b": "Extended consultation"
    }
  ],
  "label": "CPT"
}
```

**Output** (Validation Result):

```json
{
  "table_id": "bill_12345",
  "all_valid": true,
  "issues": [],
  "cpt_icd_justification_issue": null
}
```

**Error Handling**:

- Handles missing reference data gracefully
- Returns `None` for indeterminate comparisons
- Continues processing even if individual validations fail

---

### Lambda 3: Adjudication & Policy Matching

**File**: `lambda3/index.py`

**Purpose**: Performs final adjudication by matching bills against insurance policies.

**Module Breakdown**:

#### `index.py` (Main Handler)

- Orchestrates adjudication workflow
- Fetches bill and policy data
- Compares bills against coverage policies
- Applies policy rules and limitations
- Generates adjudication determination

#### `fetchPatientData.py`

- Queries patient insurance policies from database
- Retrieves policy details and coverage limits
- Handles policy lookups and caching

#### `parsingBills.py`

- Parses bill data from DynamoDB
- Extracts billing details and line items
- Normalizes bill format for comparison

#### `parsingPolicies.py`

- Parses insurance policy documents
- Extracts coverage rules and limitations
- Builds policy comparison data structures

#### `testingKnowledgeBase.py`

- Testing utilities for validation
- Sample data generators
- Debug helpers

**Adjudication Logic**:

1. Retrieve patient's insurance policies
2. Parse bill line items and totals
3. Apply policy coverage rules:
   - Check procedure coverage (in-network, out-of-network)
   - Apply deductibles and copayments
   - Check procedure limits and thresholds
   - Verify prior authorization requirements
4. Calculate patient responsibility vs. insurance payment
5. Generate adjudication result with rationale

---

### Lambda 4: Results Retrieval

**File**: `lambda4.py`

**Purpose**: Retrieves completed adjudication results from S3.

**Responsibilities**:

- Accepts `jobId` query parameter from frontend
- Searches S3 `parsed/comparisons/` folder for matching results
- Matches results by job_id stored in S3 object metadata
- Decodes JSON result file
- Deletes result file from S3 (cleanup)
- Returns result to frontend

**Input**:

```
GET /testjson?jobId=abc-123-def-456
```

**Output**:

```json
{
  "statusCode": 200,
  "body": {
    "validation_result": {...},
    "adjudication": {...}
  }
}
```

**Error Handling**:

- 400: Missing jobId parameter
- 404: No results found for jobId
- 500: AWS service errors

---

## Frontend Application

### Component Structure

#### `App.js`

- Main routing component
- Sets up React Router with three routes
- Includes Navbar wrapper

**Routes**:

- `/` → Homepage
- `/upload` → Uploadpage
- `/userguide` → UserGuidepage

#### `Navbar.js`

- Navigation menu with links to all pages
- Styled with `Navbar.css`

#### `Homepage.js`

- Landing page with project overview
- Introduction to medical bill adjudication

#### `Uploadpage.js`

- Main interaction component (287 lines)
- File upload via file input
- Base64 encoding of PDF
- API calls to Lambda 0
- Polling mechanism to fetch results from Lambda 4
- Results display with formatting

**Key Functionality**:

```javascript
// Upload flow
1. User selects PDF file
2. Frontend encodes file to base64
3. Generates unique job_id (UUID)
4. Sends to Lambda 0 via API Gateway
5. On success, starts polling Lambda 4
6. Retries every 30 seconds (max 6 times = 3 minutes)
7. Displays results when available
```

#### `UserGuidepage.js`

- Help documentation
- Instructions for using the system
- FAQ and troubleshooting

### Styling

- `App.css` - Main app styles
- `Uploadpage.css` - Upload page styles
- `Navbar.css` - Navigation styles
- `index.css` - Global styles

### Key Libraries

- **React Router DOM 7.9**: Client-side routing
- **AWS SDK S3**: For potential direct S3 uploads
- **UUID**: Generate unique job IDs
- **Jest + React Testing Library**: Testing framework

---

## Database Schema

### DynamoDB Tables

#### 1. `Patient_info`

**Purpose**: Store patient information extracted from bills

**Schema**:

```
PrimaryKey: patient_id (String)

Attributes:
- patient_id (S) - UUID
- firstname (S)
- lastname (S)
- age (N)
- phone (S)
- address (S)
- city (S)
- state (S)
- zipcode (S)
- insurance_provider (S) - Optional
- policy_number (S) - Optional
- created_at (S) - ISO timestamp
```

#### 2. `Provider_info`

**Purpose**: Store healthcare provider information

**Schema**:

```
PrimaryKey: provider_id (String)

Attributes:
- provider_id (S) - UUID
- name (S)
- phone (S)
- address (S)
- city (S)
- state (S)
- zipcode (S)
- npi (S) - National Provider Identifier
- specialty (S)
- network_status (S) - "in-network", "out-of-network"
- created_at (S) - ISO timestamp
```

#### 3. `temporary_med_bill2`

**Purpose**: Store medical billing items (CPT codes) from extracted bills

**Schema**:

```
PrimaryKey: code (String, HASH)
SortKey: table_id (String, RANGE)

Attributes:
- code (S) - CPT code (e.g., "99213")
- table_id (S) - Links to specific bill
- description (S) - Procedure description
- bill (N) - Billed amount
- modifiers (S) - Optional CPT modifiers
- quantity (N) - Number of services
- units (S) - Service units (e.g., "per session")
- created_at (S) - ISO timestamp
```

#### 4. `temporary_med_icd`

**Purpose**: Store ICD-10 diagnosis codes extracted from bills

**Schema**:

```
PrimaryKey: code (String, HASH)
SortKey: table_id (String, RANGE)

Attributes:
- code (S) - ICD-10 code (e.g., "I10")
- table_id (S) - Links to specific bill
- description (S) - Diagnosis description
- principal (BOOL) - Is this the principal diagnosis
- created_at (S) - ISO timestamp
```

#### 5. `reference_table`

**Purpose**: Authoritative reference of CPT codes and descriptions

**Schema**:

```
PrimaryKey: code (String)

Attributes:
- code (S) - CPT code
- description (S) - Standard description
- category (S) - Code category
- last_updated (S) - Update timestamp
```

#### 6. `icd_10_reference_table`

**Purpose**: Authoritative reference of ICD-10 codes and descriptions

**Schema**:

```
PrimaryKey: code (String)

Attributes:
- code (S) - ICD-10 code
- description (S) - Standard description
- category (S) - Code category
- version (S) - ICD version year
- last_updated (S) - Update timestamp
```

#### 7. `temporary_patientMedicalBillInfo`

**Purpose**: Overall bill summary information

**Schema**:

```
PrimaryKey: table_id (String)

Attributes:
- table_id (S) - Unique bill identifier
- patient_id (S) - Foreign key to Patient_info
- provider_id (S) - Foreign key to Provider_info
- job_id (S) - Links to S3 job tracking
- subtotal (N) - Bill subtotal
- discount (N) - Discount amount
- tax (N) - Tax amount
- total (N) - Total amount due
- date_of_service (S) - Service date
- status (S) - "extracted", "validated", "adjudicated"
- created_at (S) - ISO timestamp
- updated_at (S) - ISO timestamp
```

### Indexing Strategy

- **GSI on `job_id`**: Fast lookup by job ID across tables
- **GSI on `status`**: Query bills by adjudication status
- **TTL on temporary tables**: Auto-delete old records after 90 days

---

## API Documentation

### API Gateway Endpoints

#### 1. Upload PDF

**Endpoint**: `POST /upload`

**Request**:

```bash
curl -X POST https://api.example.com/upload \
  -H "Content-Type: application/json" \
  -d '{
    "file_name": "medical_bill.pdf",
    "file_content": "JVBERi0xLjQKJeLjz9MNCjEgMCBvYmoNCjw8L1R5cGUgL0NhdGFsb2cvUGFnZXMgMiAwIFI+Pg0KZW5kb2JqDQo...",
    "job_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

**Response** (Success):

```json
{
  "statusCode": 200,
  "body": {
    "message": "File medical_bill.pdf uploaded successfully. Job ID: 550e8400-e29b-41d4-a716-446655440000"
  }
}
```

**Response** (Error):

```json
{
  "statusCode": 400,
  "body": {
    "error": "Invalid file type. Only PDF files are allowed."
  }
}
```

**Status Codes**:

- `200` - Upload successful
- `400` - Invalid file format, missing parameters
- `413` - File too large
- `500` - Server error

---

#### 2. Retrieve Results

**Endpoint**: `GET /testjson?jobId={job_id}`

**Request**:

```bash
curl -X GET "https://api.example.com/testjson?jobId=550e8400-e29b-41d4-a716-446655440000"
```

**Response** (Success):

```json
{
  "statusCode": 200,
  "body": {
    "table_id": "bill_12345",
    "patient_info": {...},
    "hospital_info": {...},
    "validation_result": {
      "all_valid": true,
      "issues": []
    },
    "adjudication_result": {...}
  }
}
```

**Response** (In Progress):

```json
{
  "statusCode": 404,
  "body": {
    "error": "file not ready yet"
  }
}
```

**Status Codes**:

- `200` - Results available
- `400` - Missing jobId parameter
- `404` - Results not ready or not found
- `500` - Server error

---

### EventBridge/Lambda Invocation

#### Lambda-to-Lambda Invocation Format

**Lambda 0 → Lambda 1** (S3 Event):

```json
{
  "Records": [
    {
      "s3": {
        "bucket": {
          "name": "farhantest01"
        },
        "object": {
          "key": "medical_bill.pdf",
          "metadata": {
            "job_id": "550e8400-e29b-41d4-a716-446655440000"
          }
        }
      }
    }
  ]
}
```

**Lambda 1 → Lambda 2**:

```json
{
  "source": "lambda-chain",
  "s3": {
    "bucket_name": "farhantest01",
    "object_key": "medical_bill.pdf",
    "version_id": "null"
  },
  "table_id": "bill_12345",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

## Development Guide

### Local Development Setup

#### Backend Development

```bash
# Clone repository
git clone <repo-url>
cd MedicalBillAdjudicatin

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install boto3 botocore

# Set AWS credentials
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_REGION=us-east-2

# Test Lambda locally using SAM
sam local start-api
```

#### Frontend Development

```bash
# Navigate to frontend directory
cd front-end

# Install dependencies
npm install

# Start development server
npm start

# Server runs on http://localhost:3000
```

### Testing

#### Python Lambda Testing

```bash
# Create test event
cat > test_event.json << EOF
{
  "queryStringParameters": {
    "jobId": "test-job-123"
  }
}
EOF

# Test Lambda 4 locally
python3 -m pytest tests/ -v
```

#### Frontend Testing

```bash
cd front-end

# Run tests
npm test

# Run tests with coverage
npm test -- --coverage

# Build for production
npm run build
```

### Debugging

#### CloudWatch Logs

```bash
# View Lambda logs
aws logs tail /aws/lambda/lambda-1 --follow

# View specific error
aws logs filter-log-events \
  --log-group-name /aws/lambda/lambda-1 \
  --filter-pattern "ERROR"
```

#### X-Ray Tracing

```bash
# Enable X-Ray for Lambda
aws lambda update-function-configuration \
  --function-name lambda-1 \
  --tracing-config Mode=Active

# View traces
aws xray get-trace-summaries --start-time $(date -u -d '1 hour ago' +%s)
```

### Code Style & Best Practices

- **Python**: Follow PEP 8 guidelines
- **JavaScript**: Use ESLint and Prettier
- **Type Hints**: Use Python type hints for Lambda functions
- **Error Handling**: Always handle AWS service exceptions
- **Logging**: Use structured logging with appropriate levels (INFO, WARNING, ERROR)
- **Security**: Never hardcode AWS credentials or secrets

---

## Deployment

### Prerequisites for Deployment

1. AWS Account with appropriate permissions
2. AWS CLI configured
3. S3 buckets created
4. DynamoDB tables created
5. IAM roles and policies configured
6. Bedrock access enabled

### Deployment Steps

#### 1. Deploy Lambda Functions

```bash
#!/bin/bash
# deploy_lambdas.sh

REGION="us-east-2"
ROLE_ARN="arn:aws:iam::ACCOUNT_ID:role/lambda-execution-role"
MODEL_ID="anthropic.claude-4-0-sonnet-20241022-v2:0"

# Deploy Lambda 0
zip -j lambda0.zip lambda0.py
aws lambda create-function \
  --function-name medical-bill-intake \
  --runtime python3.12 \
  --role $ROLE_ARN \
  --handler lambda0.lambda_handler \
  --zip-file fileb://lambda0.zip \
  --region $REGION

# Deploy Lambda 1
zip -j lambda1.zip lambda1.py
aws lambda create-function \
  --function-name medical-bill-extraction \
  --runtime python3.12 \
  --role $ROLE_ARN \
  --handler lambda1.lambda_handler \
  --zip-file fileb://lambda1.zip \
  --environment Variables={AWS_REGION=$REGION,MODEL_ID=$MODEL_ID} \
  --timeout 300 \
  --memory-size 1024 \
  --region $REGION

# Deploy Lambda 2
zip -j lambda2.zip lambda2.py
aws lambda create-function \
  --function-name medical-bill-validation \
  --runtime python3.12 \
  --role $ROLE_ARN \
  --handler lambda2.lambda_handler \
  --zip-file fileb://lambda2.zip \
  --environment Variables={AWS_REGION=$REGION,MODEL_ID=$MODEL_ID} \
  --timeout 300 \
  --memory-size 1024 \
  --region $REGION

# Deploy Lambda 4
zip -j lambda4.zip lambda4.py
aws lambda create-function \
  --function-name medical-bill-results \
  --runtime python3.12 \
  --role $ROLE_ARN \
  --handler lambda4.lambda_handler \
  --zip-file fileb://lambda4.zip \
  --timeout 60 \
  --region $REGION
```

#### 2. Deploy Frontend

```bash
cd front-end

# Build React app
npm run build

# Deploy to S3
aws s3 sync build/ s3://your-frontend-bucket/ --delete

# Invalidate CloudFront cache (if using CloudFront)
aws cloudfront create-invalidation \
  --distribution-id YOUR_DISTRIBUTION_ID \
  --paths "/*"
```

#### 3. Configure API Gateway

```bash
# Create REST API
aws apigateway create-rest-api --name MedicalBillAPI

# Create resources and methods for /upload and /testjson endpoints
# Link to Lambda functions
# Configure CORS

# Deploy to stage
aws apigateway create-deployment \
  --rest-api-id YOUR_API_ID \
  --stage-name prod
```

### Infrastructure as Code (Terraform/CloudFormation)

For production deployments, use CloudFormation or Terraform:

```yaml
# cloudformation-template.yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: "Medical Bill Adjudication System"

Resources:
  # S3 Buckets
  UploadBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: medical-bill-uploads
      VersioningConfiguration:
        Status: Enabled

  ResultsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: medical-bill-results

  # DynamoDB Tables
  PatientInfoTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: Patient_info
      AttributeDefinitions:
        - AttributeName: patient_id
          AttributeType: S
      KeySchema:
        - AttributeName: patient_id
          KeyType: HASH
      BillingMode: PAY_PER_REQUEST

  # Lambda Functions
  LambdaIntakeFunction:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: medical-bill-intake
      Runtime: python3.12
      Handler: lambda0.lambda_handler
      Code:
        S3Bucket: deployment-bucket
        S3Key: lambda0.zip
      Role: !GetAtt LambdaExecutionRole.Arn

  # API Gateway
  APIGateway:
    Type: AWS::ApiGateway::RestApi
    Properties:
      Name: MedicalBillAPI
      Description: API for Medical Bill Adjudication

  # ... more resources ...
```

---

## Troubleshooting

### Common Issues

#### Issue: "File not ready yet" on results retrieval

**Cause**: Results haven't been generated yet or job_id mismatch

**Solution**:

- Wait 30 seconds and retry (frontend auto-retries)
- Verify job_id matches in both upload and retrieval calls
- Check Lambda logs for processing errors

```bash
# Check Lambda 4 logs
aws logs tail /aws/lambda/medical-bill-results --follow
```

---

#### Issue: "No ICD entries found" validation error

**Cause**: Bill PDF didn't contain ICD-10 diagnosis codes

**Solution**:

- Ensure medical bill includes diagnosis section
- Verify Bedrock model is correctly parsing PDF
- Check CloudWatch logs for extraction details

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/medical-bill-extraction \
  --filter-pattern "icd_10_codes"
```

---

#### Issue: Bedrock throttling errors

**Cause**: Too many concurrent requests to Bedrock

**Solution**:

- Adjust `MAX_RETRIES` and `RETRY_SLEEP_BASE` environment variables
- Implement request batching (already done in Lambda 2)
- Request Bedrock quota increase

```bash
aws lambda update-function-configuration \
  --function-name medical-bill-extraction \
  --environment Variables={MAX_RETRIES=12,RETRY_SLEEP_BASE=1.0}
```

---

#### Issue: DynamoDB Item size exceeded

**Cause**: Bill extraction produced item >400KB

**Solution**:

- Implement item compression
- Split large items across multiple DynamoDB entries
- Reduce token budget for PDF extraction

---

#### Issue: CORS errors on frontend

**Cause**: API Gateway doesn't have CORS configured

**Solution**:

```bash
# Enable CORS on API Gateway
aws apigateway put-integration-response \
  --rest-api-id YOUR_API_ID \
  --resource-id YOUR_RESOURCE_ID \
  --http-method POST \
  --status-code 200 \
  --response-parameters '{"method.response.header.Access-Control-Allow-Origin":"'"'"'*'"'"'"}' \
  --response-templates '{"application/json":""}'
```

---

#### Issue: Lambda timeout on large PDFs

**Cause**: Bedrock processing takes too long

**Solution**:

- Increase Lambda timeout to 5 minutes
- Increase memory allocation (improves CPU, reduces timeout)

```bash
aws lambda update-function-configuration \
  --function-name medical-bill-extraction \
  --timeout 300 \
  --memory-size 1024
```

---

### Performance Optimization Tips

1. **Optimize DynamoDB Queries**:

   - Use projection expressions to fetch only needed attributes
   - Implement query pagination for large result sets
   - Use batch operations where possible

2. **Optimize Bedrock Calls**:

   - Use batch comparison instead of individual calls
   - Adjust token limits based on document complexity
   - Consider caching reference table lookups

3. **Optimize Frontend**:

   - Implement result caching
   - Use lazy loading for large result displays
   - Optimize bundle size with code splitting

4. **Optimize Cost**:
   - Use S3 Intelligent-Tiering for old PDFs
   - Set DynamoDB TTL on temporary tables
   - Monitor CloudWatch metrics for unused capacity

---

### Monitoring & Alerting

#### CloudWatch Metrics to Monitor

```bash
# Lambda duration
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=medical-bill-extraction \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum

# Lambda errors
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=medical-bill-extraction \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum
```

#### Create CloudWatch Alarms

```bash
# Alert on Lambda errors
aws cloudwatch put-metric-alarm \
  --alarm-name medical-bill-extraction-errors \
  --alarm-description "Alert when extraction Lambda has errors" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Make changes and commit (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## Support & Contact

For issues, questions, or feedback:

- **Documentation**: See this README and inline code comments
- **Issues**: File GitHub issues for bugs and feature requests
- **AWS Support**: Use AWS Support Console for infrastructure issues
- **Bedrock Documentation**: https://docs.aws.amazon.com/bedrock/

---

## Acknowledgments

- AWS Bedrock Claude AI for intelligent document processing
- AWS Lambda for serverless computing
- React community for frontend framework
- Medical coding standards (CPT, ICD-10)

---

**Last Updated**: December 7, 2025  
**Version**: 1.0  
**Status**: Production Ready
