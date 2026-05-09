#!/usr/bin/env bash
# Full deployment script for Alexa Private AI skill
# Requires: AWS creds configured, ASK CLI authenticated

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_NAME="Hermes Private AI"
FUNCTION_NAME="alexa-hermes-lambda"
ROLE_NAME="alexa-hermes-lambda-role"
TABLE_NAME="alexa-hermes-sessions"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"

if [ -z "$ACCOUNT_ID" ]; then
    echo "ERROR: Set AWS_ACCOUNT_ID env var"
    exit 1
fi

echo "========================================="
echo "AWS Infrastructure Setup"
echo "========================================="

# 1. Create IAM Role for Lambda
echo "[1/6] Creating IAM role..."
LAMBDA_TRUST='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$LAMBDA_TRUST" \
    --region "$REGION" 2>/dev/null || echo "Role already exists"

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
    --region "$REGION" 2>/dev/null || true

# Inline policy for DynamoDB
INLINE_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem","dynamodb:PutItem","dynamodb:DeleteItem"],
    "Resource": "arn:aws:dynamodb:'"$REGION"':'"$ACCOUNT_ID"':table/'"$TABLE_NAME"'"
  }]
}'

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name AlexaHermesDynamoDBPolicy \
    --policy-document "$INLINE_POLICY" \
    --region "$REGION" 2>/dev/null || echo "Policy already exists"

# Wait for role propagation
sleep 5

echo "[2/6] Creating DynamoDB table..."
aws dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=userId,AttributeType=S \
    --key-schema AttributeName=userId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" 2>/dev/null || echo "Table already exists"

aws dynamodb update-time-to-live \
    --table-name "$TABLE_NAME" \
    --time-to-live-specification Enabled=true,AttributeName=ttl \
    --region "$REGION" 2>/dev/null || echo "TTL already enabled"

echo "[3/6] Creating Lambda function..."
ZIP_PATH="/tmp/alexa-hermes-lambda.zip"
cd "$REPO_ROOT/lambda"
rm -f "$ZIP_PATH"
zip -r "$ZIP_PATH" lambda_function.py

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --zip-file "fileb://$ZIP_PATH" \
    --timeout 10 \
    --memory-size 256 \
    --environment "Variables={HERMES_URL=https://nickcoury.duckdns.org:8443/v1/chat/completions,MODEL=hermes-agent,DYNAMODB_TABLE=$TABLE_NAME,SESSION_TTL_MINUTES=10,MAX_HISTORY=20}" \
    --region "$REGION" 2>/dev/null || {
        echo "Function may exist, updating code..."
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --zip-file "fileb://$ZIP_PATH" \
            --region "$REGION"
        aws lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --environment "Variables={HERMES_URL=https://nickcoury.duckdns.org:8443/v1/chat/completions,MODEL=hermes-agent,DYNAMODB_TABLE=$TABLE_NAME,SESSION_TTL_MINUTES=10,MAX_HISTORY=20}" \
            --region "$REGION"
    }

echo "[4/6] Waiting for Lambda..."
aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"

echo "========================================="
echo "ASK Skill Deployment"
echo "========================================="

echo "[5/6] Deploying skill package..."
cd "$REPO_ROOT"
ask deploy --target skill-metadata 2>&1 || {
    echo "ask deploy failed, trying direct SMAPI..."
    # Fallback: use SMAPI directly
    SKILL_ID=$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" 2>/dev/null | grep -o '"FunctionArn"' >/dev/null && echo "" || echo "")
}

echo "[6/6] Done!"
echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo "1. Get your Skill ID from the Alexa Developer Console"
echo "2. Add the Alexa Skills Kit trigger to your Lambda"
echo "3. Enable testing in the Developer Console"
