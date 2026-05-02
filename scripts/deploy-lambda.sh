#!/usr/bin/env bash
# Package and deploy the Lambda function.
# Usage: ./scripts/deploy-lambda.sh [function-name]

set -e

FUNCTION_NAME="${1:-alexa-hermes-lambda}"
REGION="${AWS_REGION:-us-east-1}"
ZIP_PATH="/tmp/alexa-hermes-lambda.zip"

cd "$(dirname "$0")/../lambda"

echo "Packaging Lambda..."
rm -f "$ZIP_PATH"
zip -r "$ZIP_PATH" lambda_function.py

echo "Deploying to $FUNCTION_NAME..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_PATH" \
    --region "$REGION"

echo "Waiting for update..."
aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"

echo "Done."
