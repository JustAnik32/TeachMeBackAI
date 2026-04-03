from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List
import os
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uuid
import hmac
import hashlib
import os
import json
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# secrets (for demo; set env vars in production)
SECRET_KEY = os.environ.get('MICROCLINIC_SECRET', 'dev_secret_change_me').encode('utf-8')
ADMIN_CODE = os.environ.get('MICROCLINIC_ADMIN_CODE', 'adminpass')

# AI Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'openai/gpt-4o-mini')


def call_openrouter(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
    """Make API call using OpenRouter"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="OpenRouter API key not configured")
    
    import requests
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "TeachMeBack"
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"OpenRouter error: {response.text}")
    return response.json()['choices'][0]['message']['content']


def check_plagiarism(user_response: str, ai_messages: list) -> dict:
    """Check if user copied from AI responses"""
    import re
    
    user_text = user_response.lower().strip()
    user_words = set(re.findall(r'\b\w+\b', user_text))
    
    if len(user_words) < 10:
        return {"is_copied": False, "confidence": 0, "reason": "Too short to check"}
    
    max_similarity = 0
    matched_ai = ""
    
    for msg in ai_messages:
        if msg.get('role') == 'assistant':
            ai_text = msg.get('content', '').lower()
            ai_words = set(re.findall(r'\b\w+\b', ai_text))
            
            if len(ai_words) < 10:
                continue
            
            common_words = user_words & ai_words
            similarity = len(common_words) / max(len(user_words), len(ai_words))
            
            if similarity > max_similarity:
                max_similarity = similarity
                matched_ai = ai_text[:100]
    
    if max_similarity > 0.6:
        return {
            "is_copied": True, 
            "confidence": max_similarity,
            "reason": "Your response is too similar to the AI's message. Please explain in your own words!"
        }
    
    return {"is_copied": False, "confidence": max_similarity, "reason": "OK"}

from . import utils, data_store

class CaseIn(BaseModel):
    patient_name: str
    age: Optional[int] = None
    consent: bool = True
    symptoms: List[str] = Field(default_factory=list)
    temperature: Optional[float] = None
    shortness_of_breath: Optional[bool] = False
    oxygen_saturation: Optional[int] = None
    notes: Optional[str] = None
    image_base64: Optional[str] = None

class ActionIn(BaseModel):
    action: str
    clinician: Optional[str] = None
    comment: Optional[str] = None


class RegisterIn(BaseModel):
    name: str
    phone: str
    password: str
    admin_code: str


class LoginIn(BaseModel):
    phone: str
    password: str

app = FastAPI(title="MicroClinic MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post('/api/cases')
def create_case(payload: CaseIn, authorization: Optional[str] = Header(None)):
    # Authentication: require token
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')

    if not payload.consent:
        raise HTTPException(status_code=400, detail="Consent is required")
    # Require a photo for the triage flow
    if not payload.image_base64:
        raise HTTPException(status_code=400, detail="Image is required for triage")

    case = payload.dict()
    triage = utils.triage_case(case)
    case.update(triage)

    # attach submitter
    case['submitted_by'] = user.get('id')
    case['submitted_by_name'] = user.get('name')

    case_id = data_store.save_case(case)
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    if payload.image_base64:
        img_path = utils.save_image_from_base64(payload.image_base64, data_dir)
        if img_path:
            data_store.update_case(case_id, {'image_path': img_path})
            case['image_path'] = img_path

    # compute signature for authenticity
    signature = hmac.new(SECRET_KEY, case_id.encode('utf-8'), hashlib.sha256).hexdigest()
    data_store.update_case(case_id, {'signature': signature})

    # generate evidence PDF from updated case
    case = data_store.get_case(case_id)
    evidence_path = utils.generate_evidence_pdf(case, data_dir)
    data_store.update_case(case_id, {'evidence_path': evidence_path})
    return {"id": case_id, "severity": case.get('severity'), "evidence_url": f"/api/cases/{case_id}/evidence"}

@app.get('/api/cases')
def list_cases():
    return data_store.get_cases()

@app.get('/api/cases/{case_id}')
def get_case(case_id: str):
    c = data_store.get_case(case_id)
    if not c:
        raise HTTPException(status_code=404, detail='Case not found')
    return c

@app.get('/api/cases/{case_id}/evidence')
def get_evidence(case_id: str):
    c = data_store.get_case(case_id)
    if not c:
        raise HTTPException(status_code=404, detail='Case not found')
    path = c.get('evidence_path')
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail='Evidence not found')
    return FileResponse(path, media_type='application/pdf', filename=os.path.basename(path))

@app.post('/api/cases/{case_id}/action')
def case_action(case_id: str, payload: ActionIn, authorization: Optional[str] = Header(None)):
    # require authentication
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')

    c = data_store.get_case(case_id)
    if not c:
        raise HTTPException(status_code=404, detail='Case not found')
    action = (payload.action or '').lower()
    updates = {}
    now = datetime.utcnow().isoformat()
    # record who performed the action
    updates['action_by'] = user.get('id')
    updates['action_by_name'] = user.get('name')
    if action in ('accept','accepted'):
        updates['status'] = 'accepted'
        updates['reviewed_by'] = payload.clinician or user.get('name')
        updates['review_comment'] = payload.comment
        updates['reviewed_at'] = now
    elif action in ('reject','rejected'):
        updates['status'] = 'rejected'
        updates['reviewed_by'] = payload.clinician or user.get('name')
        updates['review_comment'] = payload.comment
        updates['reviewed_at'] = now
    elif action in ('escalate','escalated'):
        updates['status'] = 'escalated'
        updates['escalated_at'] = now
        alerts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        os.makedirs(alerts_dir, exist_ok=True)
        alerts_log = os.path.join(alerts_dir, 'alerts.log')
        with open(alerts_log, 'a', encoding='utf-8') as f:
            f.write(f"{now} | {case_id} | ESCALATE | clinician:{payload.clinician} | comment:{payload.comment} | by:{user.get('id')}\n")
    elif action in ('mark_reviewed','reviewed'):
        updates['status'] = 'reviewed'
        updates['reviewed_by'] = payload.clinician or user.get('name')
        updates['reviewed_at'] = now
    else:
        raise HTTPException(status_code=400, detail='Unknown action')
    data_store.update_case(case_id, updates)
    return {'ok': True, 'status': updates.get('status')}


@app.post('/api/register')
def register(payload: RegisterIn):
    # require admin code to register CHWs (demo)
    if payload.admin_code != ADMIN_CODE:
        raise HTTPException(status_code=403, detail='Invalid admin code')
    existing = data_store.get_user_by_phone(payload.phone)
    if existing:
        raise HTTPException(status_code=400, detail='Phone already registered')
    user = data_store.create_user(payload.name, payload.phone, payload.password)
    if not user:
        raise HTTPException(status_code=500, detail='Unable to create user')
    return {'token': user.get('token'), 'name': user.get('name'), 'id': user.get('id')}


@app.post('/api/login')
def login(payload: LoginIn):
    user = data_store.verify_user_credentials(payload.phone, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid credentials')
    # issue a fresh token
    token = uuid.uuid4().hex
    data_store.set_user_token(user.get('id'), token)
    return {'token': token, 'name': user.get('name'), 'id': user.get('id')}


@app.get('/api/me')
def me(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return {'id': user.get('id'), 'name': user.get('name'), 'phone': user.get('phone')}


# TeachMeBack AI Learning Platform Endpoints

class TeachMeBackSessionIn(BaseModel):
    topic: str
    user_level: Optional[str] = "high_school"


class TeachMeBackMessageIn(BaseModel):
    session_id: str
    message: str


class TeachMeBackFeedbackIn(BaseModel):
    session_id: str
    correct: bool
    user_explanation: Optional[str] = None


@app.post('/api/teachmeback/start')
def start_teachmeback_session(payload: TeachMeBackSessionIn):
    """Start a new teaching session where user explains a concept to AI"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured")

    session_id = uuid.uuid4().hex
    session_data = {
        'session_id': session_id,
        'topic': payload.topic,
        'user_level': payload.user_level,
        'messages': [],
        'knowledge_gaps': [],
        'created_at': datetime.utcnow().isoformat()
    }

    try:
        system_prompt = f"""You are a curious student about to learn about "{payload.topic}". 
Your response should have TWO parts:
1. First, give a brief 2-3 sentence overview/introduction about {payload.topic} - what it is, why it matters
2. Then ask ONE simple question to start learning more

Example format: "From what I understand, [topic] is about [brief overview]. I'd like to learn more about [specific aspect]. Can you explain [specific question]?"

Keep it short and at {payload.user_level} level.
After the user responds, NEVER explain or summarize - ONLY ask follow-up questions to go deeper."""

        first_response = call_openrouter(
            system_prompt, 
            "As a curious student who knows nothing about this topic, ask me one simple question to get started.",
            max_tokens=200
        )

        session_data['messages'].append({'role': 'assistant', 'content': first_response})
        data_store.save_teachmeback_session(session_id, session_data)

        return {
            'session_id': session_id,
            'topic': payload.topic,
            'message': first_response,
            'instructions': 'Now you teach! Explain the concept to the AI student. It will ask you questions.'
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")


@app.post('/api/teachmeback/chat')
def chat_teachmeback(payload: TeachMeBackMessageIn):
    """Continue a teaching session with a new message from the user"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="OpenRouter API key not configured")

    session = data_store.get_teachmeback_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session['messages'].append({'role': 'user', 'content': payload.message})

    # Check for plagiarism before processing
    plagiarism_result = check_plagiarism(payload.message, session.get('messages', []))
    if plagiarism_result['is_copied']:
        return {
            'session_id': payload.session_id,
            'message': f"⚠️ {plagiarism_result['reason']}\n\nTry explaining in your own words based on what you know!",
            'is_copied': True
        }

    try:
        system_prompt = f"""You are a curious student learning about "{session['topic']}".
You are NOT a teacher - you are here to LEARN from the teacher (the user).
NEVER explain, summarize, or teach back. ONLY ask questions.
After the teacher explains something, ask a follow-up question to go deeper.
If something is unclear, ask for clarification.
Keep questions short and at {session['user_level']} level.
Occasionally pretend to have a misconception to see if the teacher can correct you."""

        conversation = ""
        for msg in session['messages']:
            conversation += f"{msg['role']}: {msg['content']}\n"

        ai_response = call_openrouter(system_prompt, conversation, max_tokens=300)

        session['messages'].append({'role': 'assistant', 'content': ai_response})
        data_store.update_teachmeback_session(payload.session_id, session)

        return {
            'session_id': payload.session_id,
            'message': ai_response
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")


@app.post('/api/teachmeback/feedback')
def provide_feedback(payload: TeachMeBackFeedbackIn):
    """User provides feedback on AI's understanding"""
    session = data_store.get_teachmeback_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not payload.correct and payload.user_explanation:
        gap = {
            'topic': session['topic'],
            'user_correction': payload.user_explanation,
            'timestamp': datetime.utcnow().isoformat()
        }
        session['knowledge_gaps'].append(gap)
        data_store.update_teachmeback_session(payload.session_id, session)

    return {'ok': True, 'gaps_identified': len(session.get('knowledge_gaps', []))}


@app.get('/api/teachmeback/session/{session_id}')
def get_session_summary(session_id: str):
    """Get a summary of the teaching session including identified gaps"""
    session = data_store.get_teachmeback_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        'session_id': session_id,
        'topic': session['topic'],
        'message_count': len(session.get('messages', [])),
        'knowledge_gaps': session.get('knowledge_gaps', []),
        'created_at': session.get('created_at')
    }


@app.get('/api/teachmeback/topics')
def get_topic_suggestions():
    """Get suggested topics for teaching"""
    return {
        'topics': [
            "Photosynthesis",
            "Quadratic Equations",
            "The Water Cycle",
            "Newton's Laws of Motion",
            "DNA and Genetics",
            "Supply and Demand",
            "World War II",
            "Cellular Respiration",
            "Pythagorean Theorem",
            "Chemical Bonds"
        ]
    }
