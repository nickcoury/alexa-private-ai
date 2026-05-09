import json
import os
import time
import urllib.request
import boto3

HERMES_URL = os.environ.get('HERMES_URL', 'https://nickcoury.duckdns.org:8443/v1/chat/completions')
MODEL = os.environ.get('MODEL', 'hermes-agent')
SESSION_TTL_MINUTES = int(os.environ.get('SESSION_TTL_MINUTES', '10'))
MAX_HISTORY = int(os.environ.get('MAX_HISTORY', '20'))
MAX_SPEECH_LENGTH = int(os.environ.get('MAX_SPEECH_LENGTH', '4000'))

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('DYNAMODB_TABLE', 'alexa-hermes-sessions'))

SYSTEM_PROMPT = os.environ.get(
    'SYSTEM_PROMPT',
    'You are Hermes, a helpful assistant accessed via Alexa voice. '
    'Keep responses concise but informative. Avoid markdown, bullet points, '
    'and special formatting that does not translate well to spoken audio. '
    'Use natural conversational language.'
)


def lambda_handler(event, context):
    print('Event:', json.dumps(event))
    request_type = event['request']['type']

    if request_type == 'LaunchRequest':
        return handle_launch(event)
    elif request_type == 'IntentRequest':
        return handle_intent(event)
    elif request_type == 'SessionEndedRequest':
        return handle_session_end(event)
    else:
        return build_response("Sorry, I didn't understand that.", end_session=True)


def get_user_id(event):
    """Use userId for persistent cross-session history."""
    return event['session']['user'].get('userId', event['session']['sessionId'])


def handle_launch(event):
    user_id = get_user_id(event)
    history = get_session_history(user_id)
    
    if history:
        speech = "Welcome back to Hermes. What would you like to continue with?"
    else:
        speech = "Welcome to Hermes. What would you like to ask?"
    
    return build_response(speech, reprompt="What would you like to ask?", end_session=False)


def handle_intent(event):
    intent_name = event['request']['intent']['name']
    user_id = get_user_id(event)

    if intent_name in ('AMAZON.CancelIntent', 'AMAZON.StopIntent'):
        clear_session(user_id)
        return build_response("Goodbye.", end_session=True)

    if intent_name == 'AMAZON.HelpIntent':
        return build_response(
            "You can ask me anything and I'll consult Hermes. "
            "For example, say explain quantum computing, or what is the tallest mountain. "
            "Say stop when you're done.",
            reprompt="What would you like to know?",
            end_session=False
        )

    if intent_name == 'AMAZON.RepeatIntent':
        # Alexa doesn't give us the last response easily without storing it,
        # so just acknowledge.
        return build_response(
            "I can repeat things in future updates. What would you like to ask?",
            reprompt="What would you like to ask?",
            end_session=False
        )

    if intent_name == 'ClearHistoryIntent':
        clear_session(user_id)
        return build_response(
            "Conversation history cleared. What would you like to talk about?",
            reprompt="What would you like to talk about?",
            end_session=False
        )

    if intent_name == 'AMAZON.FallbackIntent':
        return build_response(
            "I didn't catch that. Could you rephrase?",
            reprompt="What would you like to ask?",
            end_session=False
        )

    # Main chat intent
    slots = event['request']['intent'].get('slots', {})
    query = slots.get('query', {}).get('value', '')

    if not query:
        # Slot is empty - delegate to Alexa's dialog model for elicitation
        dialog_state = event['request'].get('dialogState', '')
        if dialog_state and dialog_state != 'COMPLETED':
            return {
                'version': '1.0',
                'sessionAttributes': {},
                'response': {
                    'directives': [
                        {
                            'type': 'Dialog.Delegate'
                        }
                    ],
                    'shouldEndSession': False
                }
            }
        return build_response(
            "What would you like to know?",
            reprompt="What would you like to ask?",
            end_session=False
        )

    history = get_session_history(user_id)
    history.append({'role': 'user', 'content': query})

    try:
        response_text = call_hermes(history)
        history.append({'role': 'assistant', 'content': response_text})
        save_session(user_id, history)

        # Truncate very long responses for Alexa TTS
        if len(response_text) > MAX_SPEECH_LENGTH:
            response_text = response_text[:MAX_SPEECH_LENGTH].rsplit(' ', 1)[0] + "... I'll continue in a moment."

        return build_response(
            response_text,
            reprompt="Anything else you'd like to know?",
            end_session=False
        )
    except Exception as e:
        print(f"Error calling Hermes: {e}")
        return build_response(
            "Sorry, I'm having trouble connecting right now. Please try again in a moment.",
            reprompt="Would you like to try again?",
            end_session=False
        )


def handle_session_end(event):
    user_id = get_user_id(event)
    # Optionally clear on session end, but we keep it for cross-session continuity
    # clear_session(user_id)
    return {}


def get_session_history(user_id):
    try:
        result = table.get_item(Key={'userId': user_id})
        item = result.get('Item', {})
        history = item.get('history', [])
        # Inject system prompt if starting fresh
        if not history:
            history = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        return history
    except Exception as e:
        print(f"Error getting session: {e}")
        return [{'role': 'system', 'content': SYSTEM_PROMPT}]


def save_session(user_id, history):
    ttl = int(time.time()) + (SESSION_TTL_MINUTES * 60)
    # Trim history to max length (keep system prompt + last N exchanges)
    system_msg = None
    if history and history[0]['role'] == 'system':
        system_msg = history[0]
        history = history[1:]
    if len(history) > MAX_HISTORY * 2:
        history = history[-MAX_HISTORY * 2:]
    if system_msg:
        history = [system_msg] + history

    try:
        table.put_item(
            Item={
                'userId': user_id,
                'history': history,
                'ttl': ttl,
                'updatedAt': int(time.time())
            }
        )
    except Exception as e:
        print(f"Error saving session: {e}")


def clear_session(user_id):
    try:
        table.delete_item(Key={'userId': user_id})
    except Exception as e:
        print(f"Error clearing session: {e}")


def call_hermes(history):
    payload = {
        'model': MODEL,
        'messages': history,
        'max_tokens': 1024,
        'temperature': 0.7
    }

    req = urllib.request.Request(
        HERMES_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']


def build_response(speech_text, reprompt=None, end_session=False):
    # Basic SSML escaping
    safe_text = speech_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    response = {
        'version': '1.0',
        'sessionAttributes': {},
        'response': {
            'outputSpeech': {
                'type': 'SSML',
                'ssml': f'<speak>{safe_text}</speak>'
            },
            'shouldEndSession': end_session
        }
    }

    if reprompt and not end_session:
        safe_reprompt = reprompt.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response['response']['reprompt'] = {
            'outputSpeech': {
                'type': 'SSML',
                'ssml': f'<speak>{safe_reprompt}</speak>'
            }
        }

    return response
