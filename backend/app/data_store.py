from datetime import datetime, timezone
import os
import json
import uuid
import base64
import hashlib
import hmac




def _data_dir():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    if not os.path.exists(base):
        os.makedirs(base, exist_ok=True)
    return base


def _cases_path():
    return os.path.join(_data_dir(), 'cases.json')


def save_case(case_dict):
    path = _cases_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            cases = json.load(f)
    else:
        cases = []
    case_id = str(uuid.uuid4())
    case_dict['id'] = case_id
    case_dict['created_at'] = datetime.now(timezone.utc).isoformat()
    cases.append(case_dict)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cases, f, indent=2)
    return case_id


def update_case(case_id, updates: dict):
    path = _cases_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        cases = json.load(f)
    for i, c in enumerate(cases):
        if c.get('id') == case_id:
            cases[i].update(updates)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cases, f, indent=2)
            return True
    return False


def get_cases():
    path = _cases_path()
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_case(case_id):
    for c in get_cases():
        if c.get('id') == case_id:
            return c
    return None


# --------- user management (simple file-backed) ---------
def _users_path():
    return os.path.join(_data_dir(), 'users.json')


def _load_users():
    path = _users_path()
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_users(users):
    path = _users_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return base64.b64encode(salt + dk).decode('utf-8')


def _verify_password(stored: str, password: str) -> bool:
    try:
        b = base64.b64decode(stored.encode('utf-8'))
        salt = b[:16]
        dk = b[16:]
        new = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(new, dk)
    except Exception:
        return False


def create_user(name: str, phone: str, password: str):
    users = _load_users()
    # prevent duplicate phone
    for u in users:
        if u.get('phone') == phone:
            return None
    uid = str(uuid.uuid4())
    token = uuid.uuid4().hex
    user = {
        'id': uid,
        'name': name,
        'phone': phone,
        'password_hash': _hash_password(password),
        'token': token,
        'created_at': datetime.now(timezone.utc).isoformat()
    }
    users.append(user)
    _save_users(users)
    return user


def get_user_by_phone(phone: str):
    for u in _load_users():
        if u.get('phone') == phone:
            return u
    return None


def get_user_by_token(token: str):
    if not token:
        return None
    for u in _load_users():
        if u.get('token') == token:
            return u
    return None


def verify_user_credentials(phone: str, password: str):
    u = get_user_by_phone(phone)
    if not u:
        return None
    if _verify_password(u.get('password_hash',''), password):
        return u
    return None


def set_user_token(user_id: str, token: str):
    users = _load_users()
    for i, u in enumerate(users):
        if u.get('id') == user_id:
            users[i]['token'] = token
            _save_users(users)
            return True
    return False


def get_user(user_id: str):
    for u in _load_users():
        if u.get('id') == user_id:
            return u
    return None


# --------- TeachMeBack session management ---------
def _teachmeback_sessions_path():
    return os.path.join(_data_dir(), 'teachmeback_sessions.json')


def save_teachmeback_session(session_id: str, session_data: dict):
    path = _teachmeback_sessions_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            sessions = json.load(f)
    else:
        sessions = {}
    sessions[session_id] = session_data
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=2)
    return session_id


def update_teachmeback_session(session_id: str, session_data: dict):
    path = _teachmeback_sessions_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        sessions = json.load(f)
    if session_id in sessions:
        sessions[session_id] = session_data
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(sessions, f, indent=2)
        return True
    return False


def get_teachmeback_session(session_id: str):
    path = _teachmeback_sessions_path()
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        sessions = json.load(f)
    return sessions.get(session_id)


# --------- Gamification: User Progress Tracking ---------
def _user_progress_path():
    return os.path.join(_data_dir(), 'user_progress.json')


def get_user_progress(user_id: str = 'anonymous'):
    """Get or create user progress data with points, streaks, badges, and level"""
    path = _user_progress_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            all_progress = json.load(f)
    else:
        all_progress = {}
    
    if user_id not in all_progress:
        all_progress[user_id] = {
            'points': 0,
            'total_points_earned': 0,
            'current_streak': 0,
            'max_streak': 0,
            'level': 'Beginner',
            'badges': [],
            'topics_mastered': [],
            'correct_answers': 0,
            'total_answers': 0,
            'last_session_date': None,
            'created_at': datetime.datetime.now(timezone.utc).isoformat()
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(all_progress, f, indent=2)
    
    return all_progress[user_id]


def update_user_progress(user_id: str, updates: dict):
    """Update user progress with new data"""
    path = _user_progress_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            all_progress = json.load(f)
    else:
        all_progress = {}
    
    if user_id not in all_progress:
        all_progress[user_id] = get_user_progress(user_id)
    
    all_progress[user_id].update(updates)
    all_progress[user_id]['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(all_progress, f, indent=2)
    return all_progress[user_id]


def add_points(user_id: str, points: int, reason: str = ''):
    """Add points to user and check for level up"""
    progress = get_user_progress(user_id)
    progress['points'] += points
    progress['total_points_earned'] += points
    
    # Level up logic
    levels = [
        ('Beginner', 0),
        ('Learner', 50),
        ('Student', 150),
        ('Scholar', 300),
        ('Teacher', 500),
        ('Master Teacher', 1000),
        ('Expert', 2000)
    ]
    
    new_level = 'Beginner'
    for level_name, min_points in levels:
        if progress['points'] >= min_points:
            new_level = level_name
    
    level_up = new_level != progress['level']
    progress['level'] = new_level
    
    update_user_progress(user_id, progress)
    return {'points_added': points, 'new_total': progress['points'], 'level': new_level, 'level_up': level_up}


def update_streak(user_id: str, is_correct: bool):
    """Update user's streak based on answer correctness"""
    progress = get_user_progress(user_id)
    
    if is_correct:
        progress['current_streak'] += 1
        if progress['current_streak'] > progress['max_streak']:
            progress['max_streak'] = progress['current_streak']
    else:
        progress['current_streak'] = 0
    
    progress['total_answers'] += 1
    if is_correct:
        progress['correct_answers'] += 1
    
    update_user_progress(user_id, progress)
    return {'current_streak': progress['current_streak'], 'max_streak': progress['max_streak']}


def award_badge(user_id: str, badge_id: str, badge_name: str, badge_description: str):
    """Award a badge to user if not already earned"""
    progress = get_user_progress(user_id)
    
    # Check if badge already exists
    existing_badges = [b['id'] for b in progress['badges']]
    if badge_id in existing_badges:
        return {'new_badge': False, 'badge': None}
    
    new_badge = {
        'id': badge_id,
        'name': badge_name,
        'description': badge_description,
        'awarded_at': datetime.now(timezone.utc).isoformat()
    }
    
    progress['badges'].append(new_badge)
    update_user_progress(user_id, progress)
    return {'new_badge': True, 'badge': new_badge}


def check_and_award_badges(user_id: str, session_data: dict = None):
    """Check all badge conditions and award new badges"""
    progress = get_user_progress(user_id)
    new_badges = []
    
    # Badge definitions with conditions
    badge_conditions = [
        ('first_explanation', 'First Steps', 'Completed your first teaching session', lambda p: p['total_answers'] >= 1),
        ('correct_streak_3', 'On Fire!', '3 correct answers in a row', lambda p: p['current_streak'] >= 3),
        ('correct_streak_5', 'Unstoppable!', '5 correct answers in a row', lambda p: p['current_streak'] >= 5),
        ('correct_streak_10', 'Legendary!', '10 correct answers in a row', lambda p: p['current_streak'] >= 10),
        ('points_50', 'Point Collector', 'Earned 50 points', lambda p: p['points'] >= 50),
        ('points_100', 'Century Club', 'Earned 100 points', lambda p: p['points'] >= 100),
        ('points_500', 'High Achiever', 'Earned 500 points', lambda p: p['points'] >= 500),
        ('master_teacher', 'Master Teacher', 'Reached Master Teacher level', lambda p: p['level'] == 'Master Teacher'),
        ('expert', 'Expert Educator', 'Reached Expert level', lambda p: p['level'] == 'Expert'),
    ]
    
    for badge_id, badge_name, description, condition in badge_conditions:
        if condition(progress):
            result = award_badge(user_id, badge_id, badge_name, description)
            if result['new_badge']:
                new_badges.append(result['badge'])
    
    return new_badges


def mark_topic_mastered(user_id: str, topic: str, score: int):
    """Mark a topic as mastered and award points"""
    progress = get_user_progress(user_id)
    
    # Check if topic already mastered
    existing = [t for t in progress['topics_mastered'] if t['topic'] == topic]
    if not existing:
        progress['topics_mastered'].append({
            'topic': topic,
            'mastered_at': datetime.now(timezone.utc).isoformat(),
            'final_score': score
        })
        update_user_progress(user_id, progress)
        return {'new_mastered': True, 'bonus_points': 20}
    
    return {'new_mastered': False, 'bonus_points': 0}
