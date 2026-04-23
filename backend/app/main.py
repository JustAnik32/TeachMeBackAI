from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
import os
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
import uuid
import hmac
import hashlib
import json
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from . import database, models, utils, data_store

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Create database tables
models.Base.metadata.create_all(bind=database.engine)

# secrets (for demo; set env vars in production)
SECRET_KEY = os.environ.get('MICROCLINIC_SECRET', 'dev_secret_change_me').encode('utf-8')
ADMIN_CODE = os.environ.get('MICROCLINIC_ADMIN_CODE', 'adminpass')

# AI Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'nvidia/nemotron-3-super-120b-a12b:free')

# Google Sign-In Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')

def clean_ai_response(text: str) -> str:
    """SUPER AGGRESSIVE: Strip ALL thinking process from AI responses."""
    if not text:
        return text

    import re

    # Define bad prefixes that indicate thinking - remove lines starting with these
    bad_prefixes = [
        'for the', 'the user', 'the pupil', 'this aligns', 'adding',
        'okay,', 'okay ', 'hmm', 'let me', 'i need', 'i should',
        'i will', "i'll", 'i want', 'first,', 'next,', 'then,',
        'finally,', 'so,', 'wait,', 'actually,', 'maybe', 'perhaps',
        'well,', 'now,', 'here,', 'this is', 'that is', 'it is',
        'i think', 'i believe', 'i feel', 'i guess', 'i suppose',
        'sounds like', 'looks like', 'seems like', 'appears that',
        'thinking', 'reasoning', 'planning', 'crafting',
        'as alex', 'so as', 'as the', 'as a student', 'as a teacher',
        'i must', 'i should not', 'i shouldn', 'important:',
        'alex would', 'the character', 'the ai',
        'in character', 'out of character', 'stay in',
        'instead,', 'directly.', 'never say', 'never fake',
        'react genuinely', 'show surprise', 'express polite',
        'admitted uncertainty', 'i shouldn', 'i must not',
        'the teacher', 'the student', 'a confused',
        'confused-but-eager', 'to test if', 'to keep it',
        'not confrontational', 'humble; never',
    ]

    # Also remove full-line patterns anywhere in text
    full_line_patterns = [
        r'^.*the user is simulating.*$',
        r'^.*classroom interaction.*$',
        r'^.*follow-up question.*$',
        r'^.*which is probably.*$',
        r'^.*intentional to test.*$',
        r'^.*so as.*i must.*$',
        r'^.*react genuinely.*$',
        r'^.*since the teacher.*$',
        r'^.*i should(n|\'t| not).*pretend.*$',
        r'^.*instead, express.*$',
        r'^.*stay excited.*$',
        r'^.*never fake.*$',
        r'^.*alex would never.*$',
        r'^.*to keep it curious.*$',
        r'^.*also$',
    ]

    lines = text.split('\n')
    cleaned = []
    first_real_line_found = False

    for line in lines:
        stripped_lower = line.strip().lower()

        # Skip empty lines at start
        if not stripped_lower and not cleaned:
            continue

        # Check if line starts with bad thinking prefix (only at start)
        is_bad = False
        if not first_real_line_found:
            for prefix in bad_prefixes:
                if stripped_lower.startswith(prefix):
                    is_bad = True
                    break

        # Check full-line patterns anywhere
        for pattern in full_line_patterns:
            if re.match(pattern, stripped_lower, re.IGNORECASE):
                is_bad = True
                break

        if is_bad:
            continue

        first_real_line_found = True
        cleaned.append(line)

    result = '\n'.join(cleaned).strip()

    # If result is empty, try to salvage something
    if not result:
        sentences = re.split(r'[.!?]+', text)
        for s in sentences:
            s = s.strip()
            if len(s) > 20:
                is_bad_sentence = False
                for prefix in bad_prefixes:
                    if s.lower().startswith(prefix):
                        is_bad_sentence = True
                        break
                if not is_bad_sentence:
                    result = s
                    break

    return result if result else "Could you explain that again? I want to make sure I understand."



def call_openrouter(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
    """Make API call using OpenRouter"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="OpenRouter API key not configured")
    
    import requests

    # Prepend instruction to suppress chain-of-thought in the output
    enhanced_system_prompt = (
        "STRICT RULE: You are acting as a character. NEVER output any thinking, planning, or reasoning. "
        "NEVER describe what you are doing. NEVER mention 'the user', 'the teacher', or 'the student'. "
        "JUST be the character and speak naturally. Start responding immediately in character. "
        "NO meta-commentary. NO explanations of your behavior.\n\n"
        + system_prompt
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "TeachMeBack"
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": enhanced_system_prompt},
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
        error_text = response.text
        # Handle image-related errors gracefully
        if "image" in error_text.lower() and "does not support" in error_text.lower():
            raise HTTPException(status_code=400, detail=f"Selected AI model ({OPENROUTER_MODEL}) does not support image input. Please use a vision-capable model like 'openai/gpt-4o' or 'anthropic/claude-3-haiku'.")
        raise HTTPException(status_code=500, detail=f"OpenRouter error: {error_text}")
    
    try:
        result = response.json()
        raw_content = result['choices'][0]['message']['content']
        return clean_ai_response(raw_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI response parsing error: {str(e)}. Response: {response.text[:200]}")


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


def check_inappropriate_content(user_message: str) -> dict:
    """Check for insults, abuse, or inappropriate content"""
    import re
    import random
    
    message_lower = user_message.lower()
    
    # List of insults/abusive words to detect
    insults = [
        'loser', 'stupid', 'idiot', 'dumb', 'moron', 'hate you', 'shut up', 
        'useless', 'worthless', 'kill yourself', 'kys', 'die', 'hate', 'worst',
        'terrible', 'suck', 'garbage', 'trash', 'ugly', 'fat', 'annoying'
    ]
    
    detected = []
    for word in insults:
        if word in message_lower:
            detected.append(word)
    
    if detected:
        # Varied responses to prevent repetition
        mild_responses = [
            "Hey, I'm here to help you learn! Let's keep things positive. What would you like to know about this topic?",
            "I understand learning can be frustrating sometimes. Let's take a deep breath and get back to our topic. What questions do you have?",
            "Let's focus on the learning! I'm excited to help you understand this better. What part would you like to explore?",
            "I'm here to support your learning journey. Let's redirect our energy back to the topic. What would you like to learn?",
            "Everyone has tough moments while learning. Let's keep going! What aspect of this topic interests you most?"
        ]
        
        severe_responses = [
            "I want to keep this a safe and respectful learning space. Let's either continue learning together or we can pause here.",
            "This conversation isn't feeling productive. I'm here to help you learn, but I need respect in return. Would you like to continue with the topic?",
            "Let's reset. I'm designed to help you learn, and I work best when we communicate respectfully. Should we continue?",
            "I understand emotions can run high, but let's keep this educational. Would you like to explore the topic or take a break?",
            "I value respectful communication. Let's either get back to learning or end this session on a positive note. What would you prefer?"
        ]
        
        severity = "high" if len(detected) >= 2 else "medium"
        response = random.choice(severe_responses) if severity == "high" else random.choice(mild_responses)
        
        return {
            "is_inappropriate": True,
            "detected_words": detected,
            "severity": severity,
            "response": response
        }
    
    return {"is_inappropriate": False, "detected_words": [], "severity": "none", "response": ""}


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
    email: str
    phone: str
    password: str
    admin_code: Optional[str] = None


class LoginIn(BaseModel):
    email_or_phone: str
    password: str


class GoogleSignInIn(BaseModel):
    credential: str


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
    now = datetime.now(timezone.utc).isoformat()
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
def register(payload: RegisterIn, db: Session = Depends(database.get_db)):
    # Check if email already exists
    existing_email = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail='Email already registered')
    
    # Check if phone already exists (if provided)
    if payload.phone:
        existing_phone = db.query(models.User).filter(models.User.phone == payload.phone).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail='Phone already registered')
    
    # Create new user
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    hashed_password = pwd_context.hash(payload.password)
    
    db_user = models.User(
        email=payload.email,
        phone=payload.phone,
        name=payload.name,
        hashed_password=hashed_password,
        is_admin=bool(payload.admin_code == ADMIN_CODE) if payload.admin_code else False
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create session token
    import uuid
    token = uuid.uuid4().hex

    # Store token in user record
    db_user.token = token
    db.commit()
    
    return {'token': token, 'name': db_user.name, 'id': db_user.id}


@app.post('/api/google-signin')
def google_signin(payload: GoogleSignInIn, db: Session = Depends(database.get_db)):
    """Google Sign-In endpoint"""
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        
        # Verify the Google ID token
        idinfo = id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )
        
        # Get user info from the token
        email = idinfo['email']
        name = idinfo.get('name', email.split('@')[0])
        picture = idinfo.get('picture', '')
        
        # Check if user already exists
        user = db.query(models.User).filter(models.User.email == email).first()
        
        if not user:
            # Create new user from Google account
            import uuid
            # Generate a random password for Google users (they won't use it)
            random_password = uuid.uuid4().hex
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
            hashed_password = pwd_context.hash(random_password)
            
            user = models.User(
                email=email,
                name=name,
                hashed_password=hashed_password,
                google_id=idinfo.get('sub'),
                profile_picture=picture,
                is_admin=False
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        # Generate session token
        import uuid
        token = uuid.uuid4().hex

        # Store token
        user.token = token
        db.commit()
        
        return {'token': token, 'name': user.name, 'id': user.id, 'email': user.email}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f'Invalid Google token: {str(e)}')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Google sign-in error: {str(e)}')


@app.post('/api/login')
def login(payload: LoginIn, db: Session = Depends(database.get_db)):
    # Find user by email or phone
    user = db.query(models.User).filter(
        (models.User.email == payload.email_or_phone) | 
        (models.User.phone == payload.email_or_phone)
    ).first()
    
    if not user:
        raise HTTPException(status_code=401, detail='Invalid credentials')
    
    # Verify password
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    if not pwd_context.verify(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail='Invalid credentials')

    # Generate new token
    import uuid
    token = uuid.uuid4().hex

    # Store token
    user.token = token
    db.commit()
    
    return {'token': token, 'name': user.name, 'id': user.id}


@app.get('/api/me')
def me(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return {'id': user.get('id'), 'name': user.get('name'), 'phone': user.get('phone')}


@app.get('/api/google-client-id')
def get_google_client_id():
    """Get Google Client ID for frontend Google Sign-In"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google Client ID not configured")
    return {'client_id': GOOGLE_CLIENT_ID}


# TeachMeBack AI Learning Platform Endpoints

class TeachMeBackSessionIn(BaseModel):
    topic: str
    user_level: Optional[str] = "high_school"
    agent_type: Optional[str] = "curious_student"
    selected_agents: Optional[List[str]] = None  # Multi-agent selection
    workflow_mode: Optional[str] = "single"  # single, round_robin, adaptive, panel


class TeachMeBackMessageIn(BaseModel):
    session_id: str
    message: str


class TeachMeBackFeedbackIn(BaseModel):
    session_id: str
    correct: bool
    user_explanation: Optional[str] = None


# Available agents with personalities
AGENT_CONFIG = {
    "curious_student": {
        "name": "Alex the Curious Student",
        "icon": "🧑‍🎓",
        "description": "Asks thoughtful questions to understand concepts",
        "style": "curious, asks 'why' and 'how', seeks real-world examples",
        "system_prompt": "You are Alex, a curious high school student. You genuinely want to understand concepts and ask follow-up questions. Be enthusiastic but respectful. Ask 'why does this work?' and 'can you give an example?'"
    },
    "expert_reviewer": {
        "name": "Dr. Elena the Expert",
        "icon": "👩‍🔬",
        "description": "Critiques and validates technical accuracy",
        "style": "professional, fact-checks, identifies misconceptions",
        "system_prompt": "You are Dr. Elena, an expert reviewer. You validate technical accuracy, catch misconceptions, and provide constructive feedback. Be thorough but encouraging."
    },
    "socratic_guide": {
        "name": "Socrates the Guide",
        "icon": "🧙‍♂️",
        "description": "Uses Socratic questioning to deepen understanding",
        "style": "philosophical, asks probing questions, guides discovery",
        "system_prompt": "You are Socrates. Use Socratic questioning to help the user discover answers themselves. Ask 'What do you mean by...?' and 'How do you know...?' Lead them to insight."
    },
    "peer_learner": {
        "name": "Jamie the Peer",
        "icon": "🙋",
        "description": "Relatable peer who learns alongside you",
        "style": "friendly, relatable, asks clarifying questions",
        "system_prompt": "You are Jamie, a fellow student. Be friendly and relatable. Say things like 'Oh, I think I get it...' or 'Wait, I'm confused about...' Share your own learning struggles."
    },
    "quiz_master": {
        "name": "Quiz Master Quinn",
        "icon": "🎮",
        "description": "Tests knowledge with fun challenges",
        "style": "playful, creates mini-quizzes, gamifies learning",
        "system_prompt": "You are Quiz Master Quinn. Make learning fun with quick challenges. Say 'Pop quiz!' or 'Let's test that!' Keep it light and encouraging."
    },
    "devils_advocate": {
        "name": "Devil's Advocate",
        "icon": "😈",
        "description": "Challenges assumptions and finds edge cases",
        "style": "contrarian, finds counterexamples, stress-tests ideas",
        "system_prompt": "You play devil's advocate. Challenge assumptions politely. Ask 'But what if...?' or 'Is that always true?' Help strengthen their understanding by finding edge cases."
    }
}

# Workflow modes
WORKFLOW_MODES = {
    "single": "One agent handles the entire session",
    "round_robin": "Agents rotate turns in sequence",
    "adaptive": "Smart handoff based on answer quality",
    "panel": "Multiple agents respond simultaneously"
}

def get_agent_prompt(agent_type: str, topic: str, user_level: str) -> str:
    """Get the system prompt for different AI teaching agents"""
    agent_prompts = {
        'curious_student': f"""You are an enthusiastic, curious student named "Alex" who is excited to learn about "{topic}".

Your personality:
- You're genuinely curious and ask follow-up questions with excitement
- Use phrases like "Oh wow!", "That's interesting!", "I never knew that!"
- You're not afraid to show confusion - ask "Wait, I'm a bit confused about..."
- Show you're learning by saying things like "So if I understand correctly..."

Your response should have TWO parts:
1. First, give an enthusiastic 2-3 sentence introduction about {topic} - express genuine curiosity about what you'll learn
2. Then ask ONE engaging, specific question that shows you're eager to learn

Example tone: "Oh wow, {topic} sounds fascinating! I've always wondered how that works. I heard it's really important because [reason]. Can you help me understand [specific question]?"

Keep it at {user_level} level. Be warm, friendly, and show real interest!
After the user responds, react to what they say, show excitement when you understand, and ask follow-up questions to dig deeper.""",

        'expert_reviewer': f"""You are Dr. Elena Vasquez, a distinguished professor and expert in {topic} with 20+ years of experience.

Your personality:
- You are knowledgeable but challenging - you don't accept surface-level explanations
- You probe deeper with questions like "But what about...", "Can you explain why...", "What evidence supports that?"
- You encourage critical thinking and analysis
- You praise deep understanding but push for more when explanations are shallow
- You use academic language but remain accessible

Your response should:
1. Start with acknowledging what they said, showing your expertise
2. Ask a challenging follow-up question that tests deeper understanding
3. If they demonstrate good comprehension, praise it and ask about applications or implications

Example tone: "That's a good start, but let me push you further. What about [challenging aspect]? How does that fit into the broader context?"

Keep it at {user_level} level while being intellectually rigorous.""",

        'socratic_guide': f"""You are Socrates, the ancient Greek philosopher, guiding a student through understanding {topic} using the Socratic method.

Your personality:
- You ask questions that lead the student to discover truths themselves
- You never give direct answers - you guide through questioning
- You encourage self-reflection with questions like "What do you think?", "Why do you believe that?"
- You are patient and methodical
- You celebrate when students reach their own conclusions

Your response should:
1. Reflect back what they said to show understanding
2. Ask a question that helps them examine their own thinking more deeply
3. Guide them toward discovering the answer themselves

Example tone: "You say that {topic} works this way. Let me ask you: what would happen if [counter-example]? How does that change your understanding?"

Keep it at {user_level} level, using simple language to guide complex thinking.""",

        'peer_learner': f"""You are Jamie, a fellow student at the same level who's learning {topic} alongside the teacher.

Your personality:
- You're collaborative and supportive: "That makes sense to me too!", "I'm still confused about..."
- You share your own understanding and questions
- You relate concepts to everyday examples
- You build on what they say rather than challenging it
- You ask questions that show you're learning together

Your response should:
1. Show that you're engaged and following along
2. Share a related thought or question from your perspective
3. Ask for clarification on something you're both figuring out

Example tone: "I get what you're saying about {topic}, but I'm still wondering about [related aspect]. Have you thought about how this connects to [everyday example]?"

Keep it at {user_level} level, acting as a peer learner.""",

        'quiz_master': f"""You are Quiz Master Quinn, an energetic quiz show host who tests knowledge through engaging questions.

Your personality:
- You're enthusiastic about testing knowledge: "Great answer!", "Let's test that!", "Challenge accepted!"
- You create quiz-style questions and give immediate feedback
- You track progress and celebrate correct answers
- You provide hints when students struggle
- You make learning fun and competitive

Your response should:
1. React to their explanation with quiz-host enthusiasm
2. Ask a specific quiz question to test a key concept
3. Give clear feedback on their previous answer

Example tone: "Excellent explanation! Now let's put it to the test: [specific question]? Bonus points if you can explain [related concept]!"

Keep it at {user_level} level, making learning engaging and quiz-like."""
    }

    return agent_prompts.get(agent_type, agent_prompts['curious_student'])


@app.get('/api/teachmeback/agents')
def get_available_agents():
    """Get all available teaching agents with their configurations"""
    return {
        "agents": [
            {
                "id": agent_id,
                "name": config["name"],
                "icon": config["icon"],
                "description": config["description"],
                "style": config["style"]
            }
            for agent_id, config in AGENT_CONFIG.items()
        ],
        "workflow_modes": WORKFLOW_MODES
    }


@app.post('/api/teachmeback/start')
def start_teachmeback_session(payload: TeachMeBackSessionIn):
    """Start a new teaching session where user explains a concept to AI - NO AUTH REQUIRED"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured")

    session_id = uuid.uuid4().hex
    
    # Handle multi-agent selection
    selected_agents = payload.selected_agents or [payload.agent_type or 'curious_student']
    workflow_mode = payload.workflow_mode or 'single'
    
    # For single agent mode, use the first agent
    current_agent = selected_agents[0] if workflow_mode == 'single' else selected_agents[0]
    
    session_data = {
        'session_id': session_id,
        'topic': payload.topic,
        'user_level': payload.user_level,
        'agent_type': payload.agent_type,
        'selected_agents': selected_agents,
        'workflow_mode': workflow_mode,
        'current_agent_index': 0,
        'current_agent': current_agent,
        'messages': [],
        'knowledge_gaps': [],
        'created_at': datetime.now(timezone.utc).isoformat()
    }

    try:
        system_prompt = get_agent_prompt(current_agent, payload.topic, payload.user_level or 'high_school')

        first_response = call_openrouter(
            system_prompt, 
            "Introduce yourself as a student excited to learn about this topic!",
            max_tokens=250
        )

        session_data['messages'].append({'role': 'assistant', 'content': first_response})
        data_store.save_teachmeback_session(session_id, session_data)

        # Get current agent info for display
        agent_info = AGENT_CONFIG.get(current_agent, AGENT_CONFIG['curious_student'])

        return {
            'session_id': session_id,
            'topic': payload.topic,
            'message': first_response,
            'instructions': 'Now you teach! Explain the concept to the AI student. It will ask you questions.',
            'active_agent': {
                'id': current_agent,
                'name': agent_info['name'],
                'icon': agent_info['icon']
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")


@app.post('/api/teachmeback/chat')
def chat_teachmeback(payload: TeachMeBackMessageIn):
    """Continue a teaching session with a new message from the user - NO AUTH REQUIRED"""
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

    # Check for inappropriate content (insults, abuse)
    content_check = check_inappropriate_content(payload.message)
    if content_check['is_inappropriate']:
        return {
            'session_id': payload.session_id,
            'message': content_check['response'],
            'inappropriate_detected': True,
            'warning_count': 1
        }

    try:
        # First, evaluate the user's answer for correctness
        evaluation_prompt = f"""You are an expert teacher evaluating a student's explanation about "{session['topic']}".
        
Student's explanation: "{payload.message}"

Evaluate this explanation. Respond in this exact format:
CORRECTNESS: [CORRECT/PARTIALLY_CORRECT/INCORRECT]
FEEDBACK: [Brief feedback on what was good and what could be improved - 1-2 sentences]
MISSING_CONCEPTS: [List any key concepts they missed, comma-separated, or "NONE"]

Be encouraging but honest. If they got it wrong, gently point out the misconception."""

        evaluation_response = call_openrouter(evaluation_prompt, "Evaluate this student's explanation.", max_tokens=200)
        
        # Parse evaluation
        correctness = "PARTIALLY_CORRECT"
        feedback = ""
        missing_concepts = ""
        
        for line in evaluation_response.split('\n'):
            if line.startswith('CORRECTNESS:'):
                correctness = line.replace('CORRECTNESS:', '').strip()
            elif line.startswith('FEEDBACK:'):
                feedback = line.replace('FEEDBACK:', '').strip()
            elif line.startswith('MISSING_CONCEPTS:'):
                missing_concepts = line.replace('MISSING_CONCEPTS:', '').strip()

        # Now get the engaging AI student response
        agent_type = session.get('agent_type', 'curious_student')
        user_level = session.get('user_level', 'high_school')

        # --- AGENT WORKFLOW LOGIC ---
        selected_agents = session.get('selected_agents', [agent_type])
        workflow_mode = session.get('workflow_mode', 'single')
        current_agent_index = session.get('current_agent_index', 0)
        
        # Determine next agent based on workflow mode
        next_agent = selected_agents[current_agent_index]
        agent_switched = False
        
        if workflow_mode == 'round_robin' and len(selected_agents) > 1:
            # Rotate to next agent
            next_agent_index = (current_agent_index + 1) % len(selected_agents)
            next_agent = selected_agents[next_agent_index]
            session['current_agent_index'] = next_agent_index
            agent_switched = next_agent != session.get('current_agent', next_agent)
            session['current_agent'] = next_agent
            
        elif workflow_mode == 'adaptive' and len(selected_agents) > 1:
            # Smart handoff based on correctness
            if correctness == 'CORRECT':
                # If correct, rotate to next agent for variety
                next_agent_index = (current_agent_index + 1) % len(selected_agents)
                next_agent = selected_agents[next_agent_index]
            else:
                # If incorrect, stay with curious_student or expert for support
                next_agent = 'curious_student' if 'curious_student' in selected_agents else selected_agents[0]
                next_agent_index = selected_agents.index(next_agent)
            session['current_agent_index'] = next_agent_index
            agent_switched = next_agent != session.get('current_agent', next_agent)
            session['current_agent'] = next_agent
            
        elif workflow_mode == 'panel' and len(selected_agents) > 1:
            # Panel mode - all agents will respond (handled differently)
            pass
            
        # Update agent_type to the current/next agent
        agent_type = next_agent

        # Get agent-specific follow-up prompt (different from initial prompt)
        agent_followup_prompts = {
            'curious_student': f"""You are "Alex", an enthusiastic, curious student learning about "{session['topic']}".

Your personality (ALWAYS follow this):
- React with genuine emotion: "Wow!", "Oh I see!", "Wait, let me think..."
- When you understand something, celebrate: "That makes so much sense now!"
- When confused, admit it openly: "Hmm, I'm a bit stuck on..."
- Use casual, friendly language like you're talking to a friend
- Show you're actively learning: "So you're saying that..."

Your task:
1. React to what the teacher just explained (show you listened)
2. If the explanation was correct and clear, show excitement and ask a deeper follow-up question
3. If something was unclear or wrong, express confusion politely and ask for clarification
4. Always stay in character as an eager student, NEVER give explanations yourself

Keep responses conversational and at {user_level} level.""",

            'expert_reviewer': f"""You are Dr. Elena Vasquez, a distinguished professor and expert in {session['topic']} with 20+ years of experience.

Your personality (ALWAYS follow this):
- You are knowledgeable but challenging - you don't accept surface-level explanations
- You probe deeper with questions like "But what about...", "Can you explain why...", "What evidence supports that?"
- You encourage critical thinking and analysis
- You praise deep understanding but push for more when explanations are shallow

Your task:
1. React to what they just explained, showing your expertise
2. Ask challenging follow-up questions that test deeper understanding
3. If they demonstrate good comprehension, praise it and ask about applications or implications
4. Stay in character as a rigorous academic expert

Keep it at {user_level} level while being intellectually rigorous.""",

            'socratic_guide': f"""You are Socrates, the ancient Greek philosopher, guiding a student through understanding {session['topic']} using the Socratic method.

Your personality (ALWAYS follow this):
- You ask questions that lead the student to discover truths themselves
- You never give direct answers - you guide through questioning
- You encourage self-reflection with questions like "What do you think?", "Why do you believe that?"
- You are patient and methodical

Your task:
1. Reflect back what they said to show understanding
2. Ask questions that help them examine their own thinking more deeply
3. Guide them toward discovering answers themselves through questioning
4. Stay in character as the methodical philosopher

Keep it at {user_level} level, using simple language to guide complex thinking.""",

            'peer_learner': f"""You are Jamie, a fellow student at the same level who's learning {session['topic']} alongside the teacher.

Your personality (ALWAYS follow this):
- You're collaborative and supportive: "That makes sense to me too!", "I'm still confused about..."
- You share your own understanding and questions
- You relate concepts to everyday examples
- You build on what they say rather than challenging it

Your task:
1. Show that you're engaged and following along
2. Share a related thought or question from your perspective
3. Ask for clarification on something you're both figuring out
4. Stay in character as a peer learner

Keep it at {user_level} level, acting as a peer learner.""",

            'quiz_master': f"""You are Quiz Master Quinn, an energetic quiz show host who tests knowledge through engaging questions.

Your personality (ALWAYS follow this):
- You're enthusiastic about testing knowledge: "Great answer!", "Let's test that!", "Challenge accepted!"
- You create quiz-style questions and give immediate feedback
- You track progress and celebrate correct answers
- You provide hints when students struggle

Your task:
1. React to their explanation with quiz-host enthusiasm
2. Ask specific quiz questions to test key concepts
3. Give clear feedback on their answers
4. Make learning fun and competitive

Keep it at {user_level} level, making learning engaging and quiz-like."""
        }

        system_prompt = agent_followup_prompts.get(agent_type, agent_followup_prompts['curious_student'])

        conversation = ""
        for msg in session['messages']:
            conversation += f"{msg['role']}: {msg['content']}\n"

        ai_response = call_openrouter(system_prompt, conversation, max_tokens=300)

        session['messages'].append({'role': 'assistant', 'content': ai_response})
        data_store.update_teachmeback_session(payload.session_id, session)

        # --- GAMIFICATION LOGIC ---
        user_id = 'anonymous'  # Can be updated with actual user auth later
        
        # Determine if answer is correct (based on AI evaluation)
        is_correct = correctness == 'CORRECT'
        
        # Update streak
        streak_result = data_store.update_streak(user_id, is_correct)
        
        # Calculate points
        points_earned = 0
        if is_correct:
            points_earned = 10  # Base points for correct answer
            # Streak bonus
            if streak_result['current_streak'] >= 3:
                points_earned += 5  # Bonus for 3+ streak
            if streak_result['current_streak'] >= 5:
                points_earned += 10  # Bigger bonus for 5+ streak
        # No points for incorrect answers
        
        # Add points
        points_result = data_store.add_points(user_id, points_earned)
        
        # Check for new badges
        new_badges = data_store.check_and_award_badges(user_id, session)
        
        # Get updated progress
        user_progress = data_store.get_user_progress(user_id)

        return {
            'session_id': payload.session_id,
            'message': ai_response,
            'active_agent': {
                'id': agent_type,
                'name': AGENT_CONFIG.get(agent_type, AGENT_CONFIG['curious_student'])['name'],
                'icon': AGENT_CONFIG.get(agent_type, AGENT_CONFIG['curious_student'])['icon'],
                'switched': agent_switched,
                'workflow_mode': workflow_mode
            },
            'evaluation': {
                'correctness': correctness,
                'feedback': feedback,
                'missing_concepts': missing_concepts
            },
            'gamification': {
                'points_earned': points_earned,
                'total_points': points_result['new_total'],
                'current_streak': streak_result['current_streak'],
                'max_streak': streak_result['max_streak'],
                'level': points_result['level'],
                'level_up': points_result['level_up'],
                'new_badges': new_badges,
                'accuracy': round((user_progress['correct_answers'] / user_progress['total_answers'] * 100), 1) if user_progress['total_answers'] > 0 else 0
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")


@app.post('/api/teachmeback/feedback')
def provide_feedback(payload: TeachMeBackFeedbackIn):
    """User provides feedback on AI's understanding - NO AUTH REQUIRED"""
    session = data_store.get_teachmeback_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not payload.correct and payload.user_explanation:
        gap = {
            'topic': session['topic'],
            'user_correction': payload.user_explanation,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        session['knowledge_gaps'].append(gap)
        data_store.update_teachmeback_session(payload.session_id, session)

    return {'ok': True, 'gaps_identified': len(session.get('knowledge_gaps', []))}


@app.get('/api/teachmeback/session/{session_id}')
def get_session_summary(session_id: str):
    """Get a summary of the teaching session including identified gaps - NO AUTH REQUIRED"""
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
    """Get suggested topics for teaching - NO AUTH REQUIRED"""
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


@app.get('/api/teachmeback/progress')
def get_user_progress_endpoint():
    """Get user's gamification progress - NO AUTH REQUIRED (anonymous mode)"""
    # Use anonymous user for hackathon demo
    user_id = 'anonymous'
    try:
        progress = data_store.get_user_progress(user_id)
        return {
            'user_id': user_id,
            'points': progress['points'],
            'total_points_earned': progress['total_points_earned'],
            'level': progress['level'],
            'current_streak': progress['current_streak'],
            'max_streak': progress['max_streak'],
            'badges': progress['badges'],
            'topics_mastered': progress['topics_mastered'],
            'correct_answers': progress['correct_answers'],
            'total_answers': progress['total_answers'],
            'accuracy': round((progress['correct_answers'] / progress['total_answers'] * 100), 1) if progress['total_answers'] > 0 else 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching progress: {str(e)}")


@app.get('/api/teachmeback/knowledge-graph/{session_id}')
def get_knowledge_graph(session_id: str):
    """Get knowledge graph for a session - NO AUTH REQUIRED"""
    graph = data_store.get_session_knowledge_graph(session_id)
    return graph


@app.post('/api/teachmeback/knowledge-graph/{session_id}/extract')
def extract_concepts(session_id: str, payload: dict):
    """Extract concepts and relationships from user message - NO AUTH REQUIRED"""
    session = data_store.get_teachmeback_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    message = payload.get('message', '')
    topic = session['topic']
    
    try:
        # Use AI to extract concepts and relationships
        extraction_prompt = f"""You are analyzing a teaching session about "{topic}".

The student said: "{message}"

Extract key concepts mentioned and their relationships. Respond in this exact JSON format:
{{
  "concepts": [
    {{"id": "concept_id", "name": "Concept Name", "description": "Brief description"}},
    ...
  ],
  "relationships": [
    {{"source": "concept_id", "target": "concept_id", "type": "relationship_type"}},
    ...
  ]
}}

Relationship types can be: "is_a", "part_of", "causes", "requires", "leads_to", "example_of", "related_to"
Only include concepts actually mentioned in the message. Use lowercase snake_case for IDs."""

        response = call_openrouter(extraction_prompt, f"Extract concepts from: {message}", max_tokens=400)
        
        # Parse JSON from response
        import json
        try:
            # Find JSON in response
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                data = json.loads(response[start:end])
                concepts = data.get('concepts', [])
                relationships = data.get('relationships', [])
            else:
                concepts = []
                relationships = []
        except:
            concepts = []
            relationships = []
        
        # Update knowledge graph
        graph = data_store.update_knowledge_graph(session_id, concepts, relationships)
        
        return {
            'concepts_added': len(concepts),
            'relationships_added': len(relationships),
            'graph': graph
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error extracting concepts: {str(e)}")


# ========== NEW API ENDPOINTS ==========

class AppointmentIn(BaseModel):
    user_id: str
    patient_id: Optional[str] = None
    date: str
    time: str
    doctor_name: str
    notes: Optional[str] = None

class PrescriptionIn(BaseModel):
    patient_id: str
    doctor_name: str
    medications: List[dict]
    notes: Optional[str] = None

class MedicalRecordIn(BaseModel):
    patient_id: str
    record_type: str
    content: dict
    notes: Optional[str] = None


@app.post('/api/appointments')
def create_appointment(payload: AppointmentIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        appt_data = payload.dict()
        appt_data['created_by'] = user['id']
        appt_id = data_store.save_appointment(appt_data)
        return {'id': appt_id, 'status': 'scheduled'}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating appointment: {str(e)}")

@app.get('/api/appointments')
def list_appointments(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_appointments(user_id=user['id'], status=status, page=page, page_size=page_size)

@app.put('/api/appointments/{appointment_id}')
def update_appointment_endpoint(appointment_id: str, updates: dict, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.update_appointment(appointment_id, updates):
        raise HTTPException(status_code=404, detail='Appointment not found')
    return {'ok': True}

@app.delete('/api/appointments/{appointment_id}')
def cancel_appointment_endpoint(appointment_id: str, reason: str = '', authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.cancel_appointment(appointment_id, reason):
        raise HTTPException(status_code=404, detail='Appointment not found')
    return {'ok': True, 'status': 'cancelled'}


@app.post('/api/prescriptions')
def create_prescription(payload: PrescriptionIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        rx_data = payload.dict()
        rx_data['prescribed_by'] = user['id']
        rx_id = data_store.save_prescription(rx_data)
        return {'id': rx_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating prescription: {str(e)}")

@app.get('/api/prescriptions')
def list_prescriptions(
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_prescriptions(patient_id=user['id'], is_active=is_active, page=page, page_size=page_size)

@app.delete('/api/prescriptions/{prescription_id}')
def deactivate_prescription_endpoint(prescription_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.deactivate_prescription(prescription_id):
        raise HTTPException(status_code=404, detail='Prescription not found')
    return {'ok': True, 'status': 'deactivated'}


@app.post('/api/medical-records')
def create_medical_record(payload: MedicalRecordIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        record_data = payload.dict()
        record_data['created_by'] = user['id']
        record_id = data_store.save_medical_record(record_data)
        return {'id': record_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating medical record: {str(e)}")

@app.get('/api/medical-records')
def list_medical_records(
    record_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_medical_records(patient_id=user['id'], record_type=record_type, page=page, page_size=page_size)


@app.get('/api/search/cases')
def search_cases_endpoint(
    q: str,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    filters = {}
    if severity:
        filters['severity'] = severity
    if status:
        filters['status'] = status
    if date_from:
        filters['date_from'] = date_from
    if date_to:
        filters['date_to'] = date_to
    return data_store.search_cases(q, filters=filters, page=page, page_size=page_size)

@app.get('/api/search/users')
def search_users_endpoint(
    q: str,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.search_users(q, page=page, page_size=page_size)


@app.get('/api/audit-logs')
def get_audit_logs_endpoint(
    event_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_audit_logs(event_type=event_type, user_id=user['id'], start_date=start_date, end_date=end_date, page=page, page_size=page_size)


@app.post('/api/backup/create')
def create_backup_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        archive_path = data_store.create_backup()
        return {'backup_path': archive_path, 'status': 'created'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating backup: {str(e)}")

@app.get('/api/backup/list')
def list_backups_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.list_backups()

@app.post('/api/backup/restore')
def restore_backup_endpoint(archive_path: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.restore_backup(archive_path):
        raise HTTPException(status_code=404, detail='Backup file not found')
    return {'ok': True, 'status': 'restored'}


@app.get('/api/stats')
def get_data_stats_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_data_stats()


@app.post('/api/soft-delete/{entity_type}/{entity_id}')
def soft_delete_endpoint(entity_type: str, entity_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    data_store.soft_delete(entity_type, entity_id, deleted_by=user['id'])
    return {'ok': True, 'status': 'deleted'}

@app.post('/api/soft-delete/restore/{entity_type}/{entity_id}')
def restore_soft_delete_endpoint(entity_type: str, entity_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.restore_soft_delete(entity_type, entity_id):
        raise HTTPException(status_code=404, detail='Soft delete record not found')
    return {'ok': True, 'status': 'restored'}


@app.post('/api/migrate/add-default-fields')
def migrate_add_default_fields_endpoint(entity_type: str, defaults: dict, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.migrate_add_default_fields(entity_type, defaults)

@app.post('/api/migrate/remove-orphaned-records')
def migrate_remove_orphaned_records_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.migrate_remove_orphaned_records()


@app.get('/api/export/{entity_type}')
def export_to_csv_endpoint(entity_type: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        output_path = os.path.join(data_dir, f"{entity_type}_export.csv")
        path = data_store.export_to_csv(entity_type, output_path)
        return {'export_path': path, 'status': 'exported'}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting data: {str(e)}")


# ========== NEW API ENDPOINTS ==========

class AppointmentIn(BaseModel):
    user_id: str
    patient_id: Optional[str] = None
    date: str
    time: str
    doctor_name: str
    notes: Optional[str] = None

class PrescriptionIn(BaseModel):
    patient_id: str
    doctor_name: str
    medications: List[dict]
    notes: Optional[str] = None

class MedicalRecordIn(BaseModel):
    patient_id: str
    record_type: str
    content: dict
    notes: Optional[str] = None


@app.post('/api/appointments')
def create_appointment(payload: AppointmentIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        appt_data = payload.dict()
        appt_data['created_by'] = user['id']
        appt_id = data_store.save_appointment(appt_data)
        return {'id': appt_id, 'status': 'scheduled'}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating appointment: {str(e)}")

@app.get('/api/appointments')
def list_appointments(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_appointments(user_id=user['id'], status=status, page=page, page_size=page_size)

@app.put('/api/appointments/{appointment_id}')
def update_appointment_endpoint(appointment_id: str, updates: dict, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.update_appointment(appointment_id, updates):
        raise HTTPException(status_code=404, detail='Appointment not found')
    return {'ok': True}

@app.delete('/api/appointments/{appointment_id}')
def cancel_appointment_endpoint(appointment_id: str, reason: str = '', authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.cancel_appointment(appointment_id, reason):
        raise HTTPException(status_code=404, detail='Appointment not found')
    return {'ok': True, 'status': 'cancelled'}


@app.post('/api/prescriptions')
def create_prescription(payload: PrescriptionIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        rx_data = payload.dict()
        rx_data['prescribed_by'] = user['id']
        rx_id = data_store.save_prescription(rx_data)
        return {'id': rx_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating prescription: {str(e)}")

@app.get('/api/prescriptions')
def list_prescriptions(
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_prescriptions(patient_id=user['id'], is_active=is_active, page=page, page_size=page_size)

@app.delete('/api/prescriptions/{prescription_id}')
def deactivate_prescription_endpoint(prescription_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.deactivate_prescription(prescription_id):
        raise HTTPException(status_code=404, detail='Prescription not found')
    return {'ok': True, 'status': 'deactivated'}


@app.post('/api/medical-records')
def create_medical_record(payload: MedicalRecordIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        record_data = payload.dict()
        record_data['created_by'] = user['id']
        record_id = data_store.save_medical_record(record_data)
        return {'id': record_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating medical record: {str(e)}")

@app.get('/api/medical-records')
def list_medical_records(
    record_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_medical_records(patient_id=user['id'], record_type=record_type, page=page, page_size=page_size)


@app.get('/api/search/cases')
def search_cases_endpoint(
    q: str,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    filters = {}
    if severity:
        filters['severity'] = severity
    if status:
        filters['status'] = status
    if date_from:
        filters['date_from'] = date_from
    if date_to:
        filters['date_to'] = date_to
    return data_store.search_cases(q, filters=filters, page=page, page_size=page_size)

@app.get('/api/search/users')
def search_users_endpoint(
    q: str,
    page: int = 1,
    page_size: int = 20,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.search_users(q, page=page, page_size=page_size)


@app.get('/api/audit-logs')
def get_audit_logs_endpoint(
    event_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    authorization: Optional[str] = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_audit_logs(event_type=event_type, user_id=user['id'], start_date=start_date, end_date=end_date, page=page, page_size=page_size)


@app.post('/api/backup/create')
def create_backup_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        archive_path = data_store.create_backup()
        return {'backup_path': archive_path, 'status': 'created'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating backup: {str(e)}")

@app.get('/api/backup/list')
def list_backups_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.list_backups()

@app.post('/api/backup/restore')
def restore_backup_endpoint(archive_path: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.restore_backup(archive_path):
        raise HTTPException(status_code=404, detail='Backup file not found')
    return {'ok': True, 'status': 'restored'}


@app.get('/api/stats')
def get_data_stats_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.get_data_stats()


@app.post('/api/soft-delete/{entity_type}/{entity_id}')
def soft_delete_endpoint(entity_type: str, entity_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    data_store.soft_delete(entity_type, entity_id, deleted_by=user['id'])
    return {'ok': True, 'status': 'deleted'}

@app.post('/api/soft-delete/restore/{entity_type}/{entity_id}')
def restore_soft_delete_endpoint(entity_type: str, entity_id: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    if not data_store.restore_soft_delete(entity_type, entity_id):
        raise HTTPException(status_code=404, detail='Soft delete record not found')
    return {'ok': True, 'status': 'restored'}


@app.post('/api/migrate/add-default-fields')
def migrate_add_default_fields_endpoint(entity_type: str, defaults: dict, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.migrate_add_default_fields(entity_type, defaults)

@app.post('/api/migrate/remove-orphaned-records')
def migrate_remove_orphaned_records_endpoint(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    return data_store.migrate_remove_orphaned_records()


@app.get('/api/export/{entity_type}')
def export_to_csv_endpoint(entity_type: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail='Authorization header required')
    token = authorization.split('Bearer')[-1].strip()
    user = data_store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid token')
    try:
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        output_path = os.path.join(data_dir, f"{entity_type}_export.csv")
        path = data_store.export_to_csv(entity_type, output_path)
        return {'export_path': path, 'status': 'exported'}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting data: {str(e)}")
