#!/usr/bin/env bash
# Create the DynamoDB table for session storage.
# Run this once after setting up AWS credentials.

TABLE_NAME="${DYNAMODB_TABLE:-alexa-hermes-sessions}"
REGION="${AWS_REGION:-us-east-1}"

echo "Creating DynamoDB table: $TABLE_NAME in $REGION"

aws dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=userId,AttributeType=S \
    --key-schema AttributeName=userId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

echo "Enabling TTL on attribute 'ttl'..."
aws dynamodb update-time-to-live \
    --table-name "$TABLE_NAME" \
    --time-to-live-specification Enabled=true,AttributeName=ttl \
    --region "$REGION"

echo "Done."
