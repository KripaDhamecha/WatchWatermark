"""
WatermarkWatch v2 — Backend API Server
Flask + SQLite + JWT Auth + Anthropic Claude Vision API

pip install flask flask-cors anthropic pillow requests python-dotenv
         flask-sqlalchemy flask-bcrypt pyjwt
"""

import os, base64, requests, json, uuid
from io import BytesIO
from datetime import datetime, timezone, timedelta
from functools import wraps

import jwt
import bcrypt
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from anthropic import Anthropic
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
#  App & Config
# ─────────────────────────────────────────
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'watermarkwatch.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET'] = os.environ.get("JWT_SECRET", "change-this-secret-in-production")
app.config['JWT_EXPIRE_HOURS'] = 24

db = SQLAlchemy(app)
claude = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MAX_IMAGE_MB = 20
ALLOWED_EXT  = {'jpg', 'jpeg', 'png', 'webp', 'gif'}

# ─────────────────────────────────────────
#  Database Models
# ─────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    plan          = db.Column(db.String(20),  default='free')   # free | pro | enterprise
    scans_used    = db.Column(db.Integer,     default=0)
    scans_limit   = db.Column(db.Integer,     default=10)       # free = 10/month
    created_at    = db.Column(db.DateTime,    default=lambda: datetime.now(timezone.utc))
    last_login    = db.Column(db.DateTime)
    is_active     = db.Column(db.Boolean,     default=True)
    scans         = db.relationship('ScanRecord', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    def to_dict(self):
        return {
            'id': self.id, 'email': self.email, 'username': self.username,
            'plan': self.plan, 'scans_used': self.scans_used,
            'scans_limit': self.scans_limit,
            'scans_remaining': max(0, self.scans_limit - self.scans_used),
            'created_at': self.created_at.isoformat(),
            'member_since': self.created_at.strftime('%B %Y')
        }


class ScanRecord(db.Model):
    __tablename__ = 'scans'
    id               = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id          = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, index=True)
    image_source     = db.Column(db.String(500))          # filename or URL
    source_type      = db.Column(db.String(10))           # 'file' or 'url'
    watermark_found  = db.Column(db.Boolean,  default=False)
    possibly_removed = db.Column(db.Boolean,  default=False)
    agency           = db.Column(db.String(100))
    wm_type          = db.Column(db.String(50))
    location         = db.Column(db.String(200))
    confidence       = db.Column(db.Float,    default=0.0)
    unauthorized     = db.Column(db.Boolean,  default=False)
    verdict          = db.Column(db.Text)
    notes            = db.Column(db.Text)
    region_json      = db.Column(db.Text)                 # JSON string
    scanned_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'image_source': self.image_source,
            'source_type': self.source_type,
            'watermark_found': self.watermark_found,
            'possibly_removed': self.possibly_removed,
            'agency': self.agency,
            'type': self.wm_type,
            'location': self.location,
            'confidence': self.confidence,
            'unauthorized': self.unauthorized,
            'verdict': self.verdict,
            'notes': self.notes,
            'region': json.loads(self.region_json) if self.region_json else None,
            'scanned_at': self.scanned_at.isoformat(),
            'scanned_at_fmt': self.scanned_at.strftime('%d %b %Y, %H:%M')
        }

# ─────────────────────────────────────────
#  JWT Helpers
# ─────────────────────────────────────────

def make_token(user_id: str) -> str:
    payload = {
        'sub': user_id,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(hours=app.config['JWT_EXPIRE_HOURS'])
    }
    return jwt.encode(payload, app.config['JWT_SECRET'], algorithm='HS256')


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        try:
            payload = jwt.decode(token, app.config['JWT_SECRET'], algorithms=['HS256'])
            user = db.session.get(User, payload['sub'])
            if not user or not user.is_active:
                return jsonify({'error': 'User not found or deactivated'}), 401
            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired. Please log in again.'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────
#  Image Helpers
# ─────────────────────────────────────────

def encode_b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()

def get_media_type(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower()
    return {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png',
            'webp':'image/webp','gif':'image/gif'}.get(ext, 'image/jpeg')

def resize_if_needed(data: bytes, max_mb=5) -> bytes:
    if len(data) <= max_mb * 1024 * 1024:
        return data
    img = Image.open(BytesIO(data))
    img.thumbnail((2048, 2048), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()

def build_prompt() -> str:
    return """You are an expert sports media rights analyst and digital forensics specialist.
Analyze this image for watermarks, agency marks, or copyright indicators.
Look for: visible text watermarks, logo overlays, semi-transparent marks, copyright symbols,
agency/photographer credits, and signs of watermark removal (blur/artifacts near edges).

Respond ONLY with valid JSON (no markdown, no extra text):
{
  "watermark_found": true/false,
  "possibly_removed": true/false,
  "agency": "Agency name or null",
  "type": "visible_text|logo_overlay|semi_transparent|corner_stamp|cropped_out|none",
  "location": "e.g. bottom-right corner",
  "confidence": 0.0-1.0,
  "unauthorized": true/false,
  "verdict": "1-2 sentence plain-English verdict",
  "notes": "additional observations or empty string",
  "region": {"top": 0-100, "left": 0-100, "width": 0-100, "height": 0-100}
}"""

def call_claude(image_b64: str, media_type: str) -> dict:
    resp = claude.messages.create(
        model="claude-opus-4-5", max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
            {"type": "text", "text": build_prompt()}
        ]}]
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)

# ─────────────────────────────────────────
#  Auth Routes
# ─────────────────────────────────────────

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    email    = (data.get('email') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')

    if not email or not username or not password:
        return jsonify({'error': 'email, username and password are required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if '@' not in email:
        return jsonify({'error': 'Invalid email address'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409

    user = User(email=email, username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = make_token(user.id)
    return jsonify({'token': token, 'user': user.to_dict()}), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    data     = request.get_json() or {}
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email or password'}), 401
    if not user.is_active:
        return jsonify({'error': 'Account deactivated'}), 403

    user.last_login = datetime.now(timezone.utc)
    db.session.commit()

    token = make_token(user.id)
    return jsonify({'token': token, 'user': user.to_dict()})


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me():
    return jsonify(g.current_user.to_dict())


@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    data         = request.get_json() or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not g.current_user.check_password(old_password):
        return jsonify({'error': 'Current password is incorrect'}), 400
    if len(new_password) < 8:
        return jsonify({'error': 'New password must be at least 8 characters'}), 400
    g.current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Password updated successfully'})

# ─────────────────────────────────────────
#  Detection Routes (protected)
# ─────────────────────────────────────────

@app.route('/api/detect', methods=['POST'])
@require_auth
def detect():
    user = g.current_user
    if user.scans_used >= user.scans_limit:
        return jsonify({'error': f'Scan limit reached ({user.scans_limit}/month). Upgrade your plan.'}), 429

    try:
        image_bytes = None
        source_name = ''
        source_type = 'file'
        media_type  = 'image/jpeg'

        if 'image' in request.files:
            file = request.files['image']
            if not file.filename:
                return jsonify({'error': 'No file selected'}), 400
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext not in ALLOWED_EXT:
                return jsonify({'error': f'Unsupported type: .{ext}'}), 400
            image_bytes = file.read()
            source_name = file.filename
            media_type  = get_media_type(file.filename)

        elif request.is_json and request.json.get('image_url'):
            url = request.json['image_url'].strip()
            if not url.startswith(('http://', 'https://')):
                return jsonify({'error': 'Invalid URL'}), 400
            r = requests.get(url, timeout=10, headers={'User-Agent': 'WatermarkWatch/2.0'})
            r.raise_for_status()
            ct = r.headers.get('Content-Type', 'image/jpeg').split(';')[0]
            if not ct.startswith('image/'):
                return jsonify({'error': 'URL is not an image'}), 400
            image_bytes = r.content
            source_name = url
            source_type = 'url'
            media_type  = ct
        else:
            return jsonify({'error': 'Provide an image file or image_url'}), 400

        if len(image_bytes) / 1024 / 1024 > MAX_IMAGE_MB:
            return jsonify({'error': f'Image too large. Max {MAX_IMAGE_MB}MB'}), 400

        image_bytes = resize_if_needed(image_bytes)
        result = call_claude(encode_b64(image_bytes), media_type)

        # Save to DB
        record = ScanRecord(
            user_id          = user.id,
            image_source     = source_name[:500],
            source_type      = source_type,
            watermark_found  = result.get('watermark_found', False),
            possibly_removed = result.get('possibly_removed', False),
            agency           = result.get('agency'),
            wm_type          = result.get('type'),
            location         = result.get('location'),
            confidence       = result.get('confidence', 0),
            unauthorized     = result.get('unauthorized', False),
            verdict          = result.get('verdict'),
            notes            = result.get('notes'),
            region_json      = json.dumps(result.get('region')) if result.get('region') else None
        )
        db.session.add(record)
        user.scans_used += 1
        db.session.commit()

        result['scan_id'] = record.id
        result['scans_remaining'] = max(0, user.scans_limit - user.scans_used)
        return jsonify(result)

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'Failed to fetch URL: {e}'}), 400
    except Exception as e:
        app.logger.error(f"detect error: {e}")
        return jsonify({'error': f'Detection failed: {e}'}), 500

# ─────────────────────────────────────────
#  Dashboard / History Routes
# ─────────────────────────────────────────

@app.route('/api/scans', methods=['GET'])
@require_auth
def get_scans():
    page     = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    q        = ScanRecord.query.filter_by(user_id=g.current_user.id)\
                               .order_by(ScanRecord.scanned_at.desc())
    paginated = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'scans': [s.to_dict() for s in paginated.items],
        'total': paginated.total,
        'page': page,
        'pages': paginated.pages
    })


@app.route('/api/scans/<scan_id>', methods=['GET'])
@require_auth
def get_scan(scan_id):
    scan = ScanRecord.query.filter_by(id=scan_id, user_id=g.current_user.id).first()
    if not scan:
        return jsonify({'error': 'Scan not found'}), 404
    return jsonify(scan.to_dict())


@app.route('/api/scans/<scan_id>', methods=['DELETE'])
@require_auth
def delete_scan(scan_id):
    scan = ScanRecord.query.filter_by(id=scan_id, user_id=g.current_user.id).first()
    if not scan:
        return jsonify({'error': 'Scan not found'}), 404
    db.session.delete(scan)
    db.session.commit()
    return jsonify({'message': 'Scan deleted'})


@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    uid    = g.current_user.id
    total  = ScanRecord.query.filter_by(user_id=uid).count()
    wmarks = ScanRecord.query.filter_by(user_id=uid, watermark_found=True).count()
    unauth = ScanRecord.query.filter_by(user_id=uid, unauthorized=True).count()
    removed= ScanRecord.query.filter_by(user_id=uid, possibly_removed=True).count()

    # Agency breakdown
    from sqlalchemy import func
    agency_rows = db.session.query(ScanRecord.agency, func.count(ScanRecord.id))\
        .filter(ScanRecord.user_id == uid, ScanRecord.agency != None)\
        .group_by(ScanRecord.agency).order_by(func.count(ScanRecord.id).desc()).limit(5).all()

    return jsonify({
        'total_scans': total,
        'watermarks_found': wmarks,
        'unauthorized_uses': unauth,
        'possibly_removed': removed,
        'clean_images': total - wmarks - removed,
        'top_agencies': [{'agency': r[0], 'count': r[1]} for r in agency_rows],
        'scans_used': g.current_user.scans_used,
        'scans_limit': g.current_user.scans_limit
    })

# ─────────────────────────────────────────
#  Health
# ─────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "version": "2.0"})

# ─────────────────────────────────────────
#  Init DB & Run
# ─────────────────────────────────────────

with app.app_context():
    db.create_all()
    print("✅  Database tables created/verified")

if __name__ == '__main__':
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  WARNING: ANTHROPIC_API_KEY not set")
    print("🚀  WatermarkWatch v2 backend on http://localhost:5000")
    app.run(debug=True, port=5000)
