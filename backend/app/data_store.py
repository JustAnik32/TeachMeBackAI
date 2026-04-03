import os
import json
import uuid
import datetime
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
    case_dict['created_at'] = datetime.datetime.utcnow().isoformat()
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
        'created_at': datetime.datetime.utcnow().isoformat()
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
