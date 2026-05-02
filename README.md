# Alexa Private AI — Hermes Skill

Talk to your local Hermes AI agent through Amazon Echo devices.

**Architecture:**

```
Echo → Alexa Skill → AWS Lambda → HTTPS → Caddy → Hermes Gateway (local)
                                       ↑
                             Let's Encrypt cert on DuckDNS domain
```

## Prerequisites

- AWS account (free tier works)
- Alexa Developer account
- DuckDNS domain with A record pointing to your public IP
- Router port-forwarding external port 8443 → your ProBook:8443
- Hermes gateway running on port 8642
- Caddy reverse proxy running with TLS (see previous setup)

## 1. Local HTTPS Gateway (Done)

Your local stack should already be running:

- **Hermes API:** `http://localhost:8642`
- **Caddy proxy:** `https://nickcoury.duckdns.org:8443`
- **Health check:** `curl https://nickcoury.duckdns.org:8443/health`

If Caddy is not running:

```bash
~/bin/caddy run --config ~/Caddyfile
```

## 2. Create the Alexa Skill

1. Go to [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask)
2. Click **Create Skill**
3. Name: `Hermes Private AI`
4. Default language: **English (US)**
5. Choose **Custom** model
6. Choose **Alexa-hosted (Node.js)** or **Provision your own** → select **Provision your own**
7. Click **Create skill**

### Interaction Model

1. In the left sidebar, go to **Interaction Model → JSON Editor**
2. Drag/drop or paste the contents of `skill/interactionModels/custom/en-US.json`
3. Click **Save Model**, then **Build Model**

### Endpoint

1. Go to **Endpoint** in the left sidebar
2. Select **AWS Lambda ARN**
3. Note your **Skill ID** (you'll need it for the Lambda trigger)
4. Paste your Lambda ARN (see step 3)
5. Save

## 3. Deploy AWS Lambda

### Create IAM Role

Create a role that Lambda can assume with these permissions:

- `AWSLambdaBasicExecutionRole`
- Custom inline policy for DynamoDB:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/alexa-hermes-sessions"
    }
  ]
}
```

### Create Lambda Function

1. Go to [AWS Lambda Console](https://console.aws.amazon.com/lambda)
2. Click **Create function**
3. Name: `alexa-hermes-lambda`
4. Runtime: **Python 3.12**
5. Architecture: **x86_64**
6. Execution role: use the IAM role above
7. Click **Create function**

### Environment Variables

Add these environment variables in the Lambda config:

| Variable | Value |
|----------|-------|
| `HERMES_URL` | `https://nickcoury.duckdns.org:8443/v1/chat/completions` |
| `MODEL` | `hermes-agent` |
| `DYNAMODB_TABLE` | `alexa-hermes-sessions` |
| `SESSION_TTL_MINUTES` | `10` |
| `MAX_HISTORY` | `20` |

### Add Alexa Trigger

1. In the Lambda designer, click **Add trigger**
2. Select **Alexa Skills Kit**
3. Paste your **Skill ID** from the Alexa Developer Console
4. Click **Add**

### Create DynamoDB Table

With AWS CLI configured:

```bash
./scripts/create-dynamodb-table.sh
```

Or manually in the [DynamoDB Console](https://console.aws.amazon.com/dynamodb):
- Table name: `alexa-hermes-sessions`
- Partition key: `userId` (String)
- Enable TTL on attribute: `ttl`

### Deploy Code

```bash
./scripts/deploy-lambda.sh alexa-hermes-lambda
```

Or manually:
1. Zip `lambda/lambda_function.py`
2. In Lambda console, upload the zip under **Code → Upload from → .zip file**

## 4. Test the Skill

### In the Developer Console

1. Go to **Test** tab
2. Enable testing for this skill
3. Type or speak: `open hermes`
4. Then ask a question

### On Your Echo

1. Open the Alexa app on your phone
2. Go to **More → Skills & Games → Your Skills → Dev**
3. Find **Hermes Private AI** and enable it
4. Say: **"Alexa, open Hermes"**
5. Ask anything: **"What is the capital of France?"**

## 5. Multi-Turn Conversations

The skill keeps conversation history in DynamoDB keyed by your Alexa `userId`, so:
- You can say **"Alexa, open Hermes"** and continue previous conversations
- History auto-expires after 10 minutes of inactivity (configurable via `SESSION_TTL_MINUTES`)
- Say **"clear history"** or **"start over"** to reset

## 6. Cert Renewal

`acme.sh` auto-renews the Let's Encrypt cert. Caddy is reloaded automatically via the `--reloadcmd` hook. No manual action needed.

To force a test renewal:

```bash
~/.acme.sh/acme.sh --renew -d nickcoury.duckdns.org --force
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Skill not responding" | Check Caddy is running; verify `curl https://nickcoury.duckdns.org:8443/health` from outside your network |
| "There was a problem with the requested skill's response" | Check CloudWatch Logs for the Lambda function |
| Lambda timeout | Increase Lambda timeout to 10s; verify Hermes gateway responds quickly |
| No session memory | Verify DynamoDB table exists and Lambda IAM role has CRUD permissions |
| Long responses cut off | `MAX_SPEECH_LENGTH` truncates at 4000 chars; adjust env var or use shorter prompts |

## Project Structure

```
alexa-private-ai/
├── lambda/
│   ├── lambda_function.py   # Main Lambda handler
│   └── requirements.txt     # Python deps (boto3 is built-in)
├── skill/
│   ├── skill.json           # Skill manifest
│   └── interactionModels/
│       └── custom/
│           └── en-US.json   # Voice interaction model
├── scripts/
│   ├── create-dynamodb-table.sh
│   └── deploy-lambda.sh
└── README.md
```

## TODO / Future

- [ ] Add AudioPlayer support for responses > 90 seconds
- [ ] Support multiple languages
- [ ] Add card output for Alexa app display
- [ ] Whisper audio forwarding for higher-quality STT
- [ ] Home Assistant integration for smart home context
