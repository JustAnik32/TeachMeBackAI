from datetime import datetime, timezone
import os
import json
import uuid
import base64
import hashlib
import hmac
import shutil
import gzip
import csv
from typing import List, Dict, Any, Optional, Tuple




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


def get_teachmeback_session(session_id: str) -> Optional[Dict[str, Any]]:
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
            'created_at': datetime.now(timezone.utc).isoformat()
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


def check_and_award_badges(user_id: str, session_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
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


# ========== KNOWLEDGE GRAPH FUNCTIONS ==========

def _knowledge_graph_path():
    return os.path.join(_data_dir(), 'knowledge_graphs.json')

def get_session_knowledge_graph(session_id: str):
    """Get or create knowledge graph for a session"""
    path = _knowledge_graph_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            graphs = json.load(f)
    else:
        graphs = {}
    
    if session_id not in graphs:
        graphs[session_id] = {
            'concepts': [],
            'relationships': [],
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(graphs, f, indent=2)
    
    return graphs[session_id]

def update_knowledge_graph(session_id: str, concepts: list, relationships: list):
    """Update knowledge graph with new concepts and relationships"""
    path = _knowledge_graph_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            graphs = json.load(f)
    else:
        graphs = {}
    
    if session_id not in graphs:
        graphs[session_id] = {
            'concepts': [],
            'relationships': [],
            'created_at': datetime.now(timezone.utc).isoformat()
        }
    
    graph = graphs[session_id]
    
    # Add new concepts (avoid duplicates)
    existing_ids = {c['id'] for c in graph['concepts']}
    for concept in concepts:
        if concept['id'] not in existing_ids:
            graph['concepts'].append(concept)
            existing_ids.add(concept['id'])
    
    # Add new relationships (avoid duplicates)
    existing_rels = {(r['source'], r['target'], r['type']) for r in graph['relationships']}
    for rel in relationships:
        key = (rel['source'], rel['target'], rel['type'])
        if key not in existing_rels:
            graph['relationships'].append(rel)
            existing_rels.add(key)
    
    graph['updated_at'] = datetime.now(timezone.utc).isoformat()
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(graphs, f, indent=2)
    
    return graph

def update_concept_mastery(session_id: str, concept_id: str, mastery: float):
    """Update mastery level for a concept (0.0 to 1.0)"""
    path = _knowledge_graph_path()
    if not os.path.exists(path):
        return None
    
    with open(path, 'r', encoding='utf-8') as f:
        graphs = json.load(f)
    
    if session_id not in graphs:
        return None
    
    for concept in graphs[session_id]['concepts']:
        if concept['id'] == concept_id:
            concept['mastery'] = min(1.0, max(0.0, mastery))
            concept['updated_at'] = datetime.now(timezone.utc).isoformat()
            break
    
    graphs[session_id]['updated_at'] = datetime.now(timezone.utc).isoformat()
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(graphs, f, indent=2)
    
    return graphs[session_id]


# ========== NEW DATA MODELS ==========

def _appointments_path():
    return os.path.join(_data_dir(), 'appointments.json')

def _prescriptions_path():
    return os.path.join(_data_dir(), 'prescriptions.json')

def _medical_records_path():
    return os.path.join(_data_dir(), 'medical_records.json')

def _audit_log_path():
    return os.path.join(_data_dir(), 'audit_log.json')

def _soft_deletes_path():
    return os.path.join(_data_dir(), 'soft_deletes.json')


# --- Appointments ---

def save_appointment(appointment_data: dict) -> str:
    """Create a new appointment with validation"""
    _validate_appointment(appointment_data)
    path = _appointments_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            appointments = json.load(f)
    else:
        appointments = []
    appt_id = str(uuid.uuid4())
    appointment_data['id'] = appt_id
    appointment_data['status'] = 'scheduled'
    appointment_data['created_at'] = datetime.now(timezone.utc).isoformat()
    appointment_data['updated_at'] = datetime.now(timezone.utc).isoformat()
    appointments.append(appointment_data)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(appointments, f, indent=2)
    _log_audit_event('appointment_created', {'appointment_id': appt_id})
    return appt_id

def get_appointments(user_id: Optional[str] = None, status: Optional[str] = None, page: int = 1, page_size: int = 20) -> dict:
    """Get appointments with pagination and filtering"""
    path = _appointments_path()
    if not os.path.exists(path):
        return {'items': [], 'total': 0, 'page': page, 'page_size': page_size, 'total_pages': 0}
    with open(path, 'r', encoding='utf-8') as f:
        appointments = json.load(f)
    filtered = appointments
    if user_id:
        filtered = [a for a in filtered if a.get('user_id') == user_id or a.get('patient_id') == user_id]
    if status:
        filtered = [a for a in filtered if a.get('status') == status]
    filtered.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return {'items': filtered[start:end], 'total': total, 'page': page, 'page_size': page_size, 'total_pages': total_pages}

def update_appointment(appointment_id: str, updates: dict) -> bool:
    """Update appointment with audit logging"""
    path = _appointments_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        appointments = json.load(f)
    for i, a in enumerate(appointments):
        if a.get('id') == appointment_id:
            old_status = a.get('status')
            appointments[i].update(updates)
            appointments[i]['updated_at'] = datetime.now(timezone.utc).isoformat()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(appointments, f, indent=2)
            _log_audit_event('appointment_updated', {'appointment_id': appointment_id, 'old_status': old_status, 'new_status': appointments[i].get('status')})
            return True
    return False

def cancel_appointment(appointment_id: str, reason: str = '') -> bool:
    """Soft cancel an appointment"""
    return update_appointment(appointment_id, {'status': 'cancelled', 'cancellation_reason': reason, 'cancelled_at': datetime.now(timezone.utc).isoformat()})

def _validate_appointment(data: dict):
    """Validate appointment data"""
    required = ['user_id', 'date', 'time', 'doctor_name']
    for field in required:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")
    try:
        datetime.fromisoformat(data['date'])
    except (ValueError, TypeError):
        raise ValueError("Invalid date format. Use ISO format (YYYY-MM-DD)")


# --- Prescriptions ---

def save_prescription(prescription_data: dict) -> str:
    """Create a new prescription with validation"""
    _validate_prescription(prescription_data)
    path = _prescriptions_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            prescriptions = json.load(f)
    else:
        prescriptions = []
    rx_id = str(uuid.uuid4())
    prescription_data['id'] = rx_id
    prescription_data['created_at'] = datetime.now(timezone.utc).isoformat()
    prescription_data['is_active'] = True
    prescriptions.append(prescription_data)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(prescriptions, f, indent=2)
    _log_audit_event('prescription_created', {'prescription_id': rx_id, 'patient_id': prescription_data.get('patient_id')})
    return rx_id

def get_prescriptions(patient_id: Optional[str] = None, is_active: Optional[bool] = None, page: int = 1, page_size: int = 20) -> dict:
    """Get prescriptions with pagination and filtering"""
    path = _prescriptions_path()
    if not os.path.exists(path):
        return {'items': [], 'total': 0, 'page': page, 'page_size': page_size, 'total_pages': 0}
    with open(path, 'r', encoding='utf-8') as f:
        prescriptions = json.load(f)
    filtered = prescriptions
    if patient_id:
        filtered = [p for p in filtered if p.get('patient_id') == patient_id]
    if is_active is not None:
        filtered = [p for p in filtered if p.get('is_active') == is_active]
    filtered.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return {'items': filtered[start:end], 'total': total, 'page': page, 'page_size': page_size, 'total_pages': total_pages}

def deactivate_prescription(prescription_id: str) -> bool:
    """Deactivate a prescription"""
    path = _prescriptions_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        prescriptions = json.load(f)
    for i, p in enumerate(prescriptions):
        if p.get('id') == prescription_id:
            prescriptions[i]['is_active'] = False
            prescriptions[i]['deactivated_at'] = datetime.now(timezone.utc).isoformat()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(prescriptions, f, indent=2)
            _log_audit_event('prescription_deactivated', {'prescription_id': prescription_id})
            return True
    return False

def _validate_prescription(data: dict):
    """Validate prescription data"""
    required = ['patient_id', 'doctor_name', 'medications']
    for field in required:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")
    if not isinstance(data['medications'], list) or len(data['medications']) == 0:
        raise ValueError("Prescription must have at least one medication")


# --- Medical Records ---

def save_medical_record(record_data: dict) -> str:
    """Create a new medical record"""
    _validate_medical_record(record_data)
    path = _medical_records_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            records = json.load(f)
    else:
        records = []
    record_id = str(uuid.uuid4())
    record_data['id'] = record_id
    record_data['created_at'] = datetime.now(timezone.utc).isoformat()
    record_data['updated_at'] = datetime.now(timezone.utc).isoformat()
    records.append(record_data)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2)
    _log_audit_event('medical_record_created', {'record_id': record_id, 'patient_id': record_data.get('patient_id')})
    return record_id

def get_medical_records(patient_id: Optional[str] = None, record_type: Optional[str] = None, page: int = 1, page_size: int = 20) -> dict:
    """Get medical records with pagination and filtering"""
    path = _medical_records_path()
    if not os.path.exists(path):
        return {'items': [], 'total': 0, 'page': page, 'page_size': page_size, 'total_pages': 0}
    with open(path, 'r', encoding='utf-8') as f:
        records = json.load(f)
    filtered = records
    if patient_id:
        filtered = [r for r in filtered if r.get('patient_id') == patient_id]
    if record_type:
        filtered = [r for r in filtered if r.get('record_type') == record_type]
    filtered.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return {'items': filtered[start:end], 'total': total, 'page': page, 'page_size': page_size, 'total_pages': total_pages}

def update_medical_record(record_id: str, updates: dict) -> bool:
    """Update a medical record"""
    path = _medical_records_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        records = json.load(f)
    for i, r in enumerate(records):
        if r.get('id') == record_id:
            records[i].update(updates)
            records[i]['updated_at'] = datetime.now(timezone.utc).isoformat()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2)
            _log_audit_event('medical_record_updated', {'record_id': record_id})
            return True
    return False

def _validate_medical_record(data: dict):
    """Validate medical record data"""
    required = ['patient_id', 'record_type', 'content']
    for field in required:
        if field not in data or not data[field]:
            raise ValueError(f"Missing required field: {field}")
    valid_types = ['diagnosis', 'treatment', 'lab_result', 'imaging', 'note', 'referral', 'discharge_summary']
    if data['record_type'] not in valid_types:
        raise ValueError(f"Invalid record type. Must be one of: {', '.join(valid_types)}")


# ========== SOFT DELETE FUNCTIONALITY ==========

def soft_delete(entity_type: str, entity_id: str, deleted_by: str = 'system') -> bool:
    """Mark an entity as deleted without removing it"""
    path = _soft_deletes_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            deletes = json.load(f)
    else:
        deletes = []
    delete_entry = {
        'id': str(uuid.uuid4()),
        'entity_type': entity_type,
        'entity_id': entity_id,
        'deleted_by': deleted_by,
        'deleted_at': datetime.now(timezone.utc).isoformat(),
        'restored': False
    }
    deletes.append(delete_entry)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(deletes, f, indent=2)
    _log_audit_event('soft_delete', {'entity_type': entity_type, 'entity_id': entity_id, 'deleted_by': deleted_by})
    return True

def restore_soft_delete(entity_type: str, entity_id: str) -> bool:
    """Restore a soft-deleted entity"""
    path = _soft_deletes_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        deletes = json.load(f)
    for d in deletes:
        if d['entity_type'] == entity_type and d['entity_id'] == entity_id and not d['restored']:
            d['restored'] = True
            d['restored_at'] = datetime.now(timezone.utc).isoformat()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(deletes, f, indent=2)
            _log_audit_event('soft_delete_restored', {'entity_type': entity_type, 'entity_id': entity_id})
            return True
    return False

def is_soft_deleted(entity_type: str, entity_id: str) -> bool:
    """Check if an entity is soft deleted"""
    path = _soft_deletes_path()
    if not os.path.exists(path):
        return False
    with open(path, 'r', encoding='utf-8') as f:
        deletes = json.load(f)
    for d in deletes:
        if d['entity_type'] == entity_type and d['entity_id'] == entity_id and not d['restored']:
            return True
    return False


# ========== AUDIT LOGGING ==========

def _log_audit_event(event_type: str, details: dict, user_id: Optional[str] = None):
    """Internal function to log audit events"""
    path = _audit_log_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    else:
        logs = []
    log_entry = {
        'id': str(uuid.uuid4()),
        'event_type': event_type,
        'details': details,
        'user_id': user_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'ip_address': None
    }
    logs.append(log_entry)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2)

def get_audit_logs(event_type: Optional[str] = None, user_id: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, page: int = 1, page_size: int = 50) -> dict:
    """Get audit logs with filtering and pagination"""
    path = _audit_log_path()
    if not os.path.exists(path):
        return {'items': [], 'total': 0, 'page': page, 'page_size': page_size, 'total_pages': 0}
    with open(path, 'r', encoding='utf-8') as f:
        logs = json.load(f)
    filtered = logs
    if event_type:
        filtered = [l for l in filtered if l.get('event_type') == event_type]
    if user_id:
        filtered = [l for l in filtered if l.get('user_id') == user_id]
    if start_date:
        filtered = [l for l in filtered if l.get('timestamp', '') >= start_date]
    if end_date:
        filtered = [l for l in filtered if l.get('timestamp', '') <= end_date]
    filtered.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    return {'items': filtered[start_idx:end_idx], 'total': total, 'page': page, 'page_size': page_size, 'total_pages': total_pages}


# ========== SEARCH / FILTER CAPABILITIES ==========

def search_cases(query: str, filters: Optional[dict] = None, page: int = 1, page_size: int = 20) -> dict:
    """Search cases by text query with optional filters and pagination"""
    cases = get_cases()
    results = []
    query_lower = query.lower()
    for case in cases:
        searchable = ' '.join([
            str(case.get('patient_name', '')),
            ' '.join(case.get('symptoms', [])),
            str(case.get('notes', '')),
            str(case.get('severity', '')),
            str(case.get('status', ''))
        ]).lower()
        if query_lower in searchable:
            results.append(case)
    if filters:
        if 'severity' in filters:
            results = [c for c in results if c.get('severity') == filters['severity']]
        if 'status' in filters:
            results = [c for c in results if c.get('status') == filters['status']]
        if 'date_from' in filters:
            results = [c for c in results if c.get('created_at', '') >= filters['date_from']]
        if 'date_to' in filters:
            results = [c for c in results if c.get('created_at', '') <= filters['date_to']]
    results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    total = len(results)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return {'items': results[start:end], 'total': total, 'page': page, 'page_size': page_size, 'total_pages': total_pages}

def search_users(query: str, page: int = 1, page_size: int = 20) -> dict:
    """Search users by name or phone"""
    users = _load_users()
    query_lower = query.lower()
    results = [u for u in users if query_lower in u.get('name', '').lower() or query_lower in u.get('phone', '')]
    total = len(results)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return {'items': results[start:end], 'total': total, 'page': page, 'page_size': page_size, 'total_pages': total_pages}


# ========== BACKUP / RESTORE FUNCTIONALITY ==========

def create_backup(backup_dir: Optional[str] = None) -> str:
    """Create a compressed backup of all data files"""
    if backup_dir is None:
        backup_dir = os.path.join(_data_dir(), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup_name = f"backup_{timestamp}"
    backup_path = os.path.join(backup_dir, backup_name)
    data_dir = _data_dir()
    files_to_backup = []
    for filename in os.listdir(data_dir):
        filepath = os.path.join(data_dir, filename)
        if os.path.isfile(filepath) and filename.endswith('.json'):
            files_to_backup.append((filename, filepath))
    os.makedirs(backup_path, exist_ok=True)
    for filename, filepath in files_to_backup:
        shutil.copy2(filepath, os.path.join(backup_path, filename))
    archive_path = shutil.make_archive(backup_path, 'gztar', backup_path)
    shutil.rmtree(backup_path)
    _log_audit_event('backup_created', {'backup_name': backup_name, 'archive_path': archive_path})
    return archive_path

def restore_backup(archive_path: str) -> bool:
    """Restore data from a backup archive"""
    if not os.path.exists(archive_path):
        return False
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        shutil.unpack_archive(archive_path, temp_dir)
        data_dir = _data_dir()
        for filename in os.listdir(temp_dir):
            if filename.endswith('.json'):
                src = os.path.join(temp_dir, filename)
                dst = os.path.join(data_dir, filename)
                shutil.copy2(src, dst)
    _log_audit_event('backup_restored', {'archive_path': archive_path})
    return True

def list_backups(backup_dir: Optional[str] = None) -> List[dict]:
    """List all available backups"""
    if backup_dir is None:
        backup_dir = os.path.join(_data_dir(), 'backups')
    if not os.path.exists(backup_dir):
        return []
    backups = []
    for filename in os.listdir(backup_dir):
        if filename.endswith('.tar.gz'):
            filepath = os.path.join(backup_dir, filename)
            stat = os.stat(filepath)
            backups.append({
                'filename': filename,
                'path': filepath,
                'size_bytes': stat.st_size,
                'created_at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            })
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return backups

def delete_backup(archive_path: str) -> bool:
    """Delete a backup file"""
    if os.path.exists(archive_path):
        os.remove(archive_path)
        _log_audit_event('backup_deleted', {'archive_path': archive_path})
        return True
    return False


# ========== DATA MIGRATION UTILITIES ==========

def run_migration(migration_func, migration_name: str) -> dict:
    """Run a data migration function and log results"""
    try:
        result = migration_func()
        _log_audit_event('migration_completed', {'migration_name': migration_name, 'result': str(result)})
        return {'success': True, 'migration_name': migration_name, 'result': result}
    except Exception as e:
        _log_audit_event('migration_failed', {'migration_name': migration_name, 'error': str(e)})
        return {'success': False, 'migration_name': migration_name, 'error': str(e)}

def migrate_add_default_fields(entity_type: str, defaults: dict) -> dict:
    """Add default fields to all entities of a given type"""
    migrated = 0
    if entity_type == 'cases':
        cases = get_cases()
        for i, case in enumerate(cases):
            updated = False
            for key, value in defaults.items():
                if key not in case:
                    case[key] = value
                    updated = True
            if updated:
                cases[i] = case
                migrated += 1
        path = _cases_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cases, f, indent=2)
    elif entity_type == 'users':
        users = _load_users()
        for i, user in enumerate(users):
            updated = False
            for key, value in defaults.items():
                if key not in user:
                    user[key] = value
                    updated = True
            if updated:
                users[i] = user
                migrated += 1
        _save_users(users)
    return {'migrated': migrated, 'entity_type': entity_type}

def migrate_remove_orphaned_records() -> dict:
    """Remove records that reference non-existent entities"""
    removed = 0
    cases = get_cases()
    valid_user_ids = {u['id'] for u in _load_users()}
    cleaned_cases = []
    for case in cases:
        submitted_by = case.get('submitted_by')
        if submitted_by and submitted_by not in valid_user_ids:
            removed += 1
            continue
        cleaned_cases.append(case)
    if removed > 0:
        path = _cases_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cleaned_cases, f, indent=2)
    return {'removed': removed, 'entity_type': 'cases'}

def get_data_stats() -> dict:
    """Get statistics about all data stores"""
    stats = {}
    stats['cases'] = len(get_cases())
    stats['users'] = len(_load_users())
    path = _teachmeback_sessions_path()
    stats['teachmeback_sessions'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    path = _user_progress_path()
    stats['user_progress'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    path = _knowledge_graph_path()
    stats['knowledge_graphs'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    path = _appointments_path()
    stats['appointments'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    path = _prescriptions_path()
    stats['prescriptions'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    path = _medical_records_path()
    stats['medical_records'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    path = _audit_log_path()
    stats['audit_log_entries'] = len(json.load(open(path, 'r'))) if os.path.exists(path) else 0
    stats['generated_at'] = datetime.now(timezone.utc).isoformat()
    return stats


# ========== DATA EXPORT / IMPORT ==========

def export_to_csv(entity_type: str, output_path: str) -> str:
    """Export data to CSV format"""
    if entity_type == 'cases':
        data = get_cases()
    elif entity_type == 'users':
        data = _load_users()
    elif entity_type == 'appointments':
        path = _appointments_path()
        data = json.load(open(path, 'r')) if os.path.exists(path) else []
    elif entity_type == 'prescriptions':
        path = _prescriptions_path()
        data = json.load(open(path, 'r')) if os.path.exists(path) else []
    else:
        raise ValueError(f"Unsupported entity type for CSV export: {entity_type}")
    if not data:
        raise ValueError("No data to export")
    keys = data[0].keys()
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    _log_audit_event('data_exported', {'entity_type': entity_type, 'output_path': output_path})
    return output_path

def import_from_json(entity_type: str, json_path: str) -> dict:
    """Import data from a JSON file"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        data = [data]
    imported = 0
    errors = []
    if entity_type == 'cases':
        cases = get_cases()
        existing_ids = {c.get('id') for c in cases}
        for item in data:
            if item.get('id') not in existing_ids:
                cases.append(item)
                imported += 1
            else:
                errors.append(f"Duplicate ID: {item.get('id')}")
        path = _cases_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cases, f, indent=2)
    elif entity_type == 'users':
        users = _load_users()
        existing_phones = {u.get('phone') for u in users}
        for item in data:
            if item.get('phone') not in existing_phones:
                users.append(item)
                imported += 1
            else:
                errors.append(f"Duplicate phone: {item.get('phone')}")
        _save_users(users)
    else:
        raise ValueError(f"Unsupported entity type for import: {entity_type}")
    _log_audit_event('data_imported', {'entity_type': entity_type, 'source_path': json_path, 'imported': imported})
    return {'imported': imported, 'errors': errors}
