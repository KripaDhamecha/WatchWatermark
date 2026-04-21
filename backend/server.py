"""
WatermarkWatch v3 — Backend (Google Gemini Vision - FREE)
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
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR,'watermarkwatch.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET'] = os.environ.get("JWT_SECRET","change-me-in-production")

db = SQLAlchemy(app)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY","")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
ALLOWED_EXT = {'jpg','jpeg','png','webp','gif'}

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name     = db.Column(db.String(150), default='')
    phone         = db.Column(db.String(30),  default='')
    birthday      = db.Column(db.String(20),  default='')
    bio           = db.Column(db.String(300), default='')
    avatar_b64    = db.Column(db.Text,        default=None)
    plan          = db.Column(db.String(20),  default='unlimited')
    scans_used    = db.Column(db.Integer,     default=0)
    created_at    = db.Column(db.DateTime,    default=lambda: datetime.now(timezone.utc))
    last_login    = db.Column(db.DateTime)
    is_active     = db.Column(db.Boolean,     default=True)
    scans         = db.relationship('ScanRecord', backref='user', lazy=True, cascade='all,delete-orphan')

    def set_password(self, pw):
        self.password_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    def check_password(self, pw):
        return bcrypt.checkpw(pw.encode(), self.password_hash.encode())
    def to_dict(self):
        return {
            'id':self.id,'email':self.email,'username':self.username,
            'full_name':self.full_name or '','phone':self.phone or '',
            'birthday':self.birthday or '','bio':self.bio or '',
            'plan':self.plan,'scans_used':self.scans_used,
            'member_since':self.created_at.strftime('%B %Y'),
            'avatar': f"data:image/jpeg;base64,{self.avatar_b64}" if self.avatar_b64 else None
        }

class ScanRecord(db.Model):
    __tablename__ = 'scans'
    id               = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id          = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, index=True)
    image_source     = db.Column(db.String(500))
    source_type      = db.Column(db.String(10))
    watermark_found  = db.Column(db.Boolean, default=False)
    possibly_removed = db.Column(db.Boolean, default=False)
    agency           = db.Column(db.String(100))
    wm_type          = db.Column(db.String(50))
    location         = db.Column(db.String(200))
    confidence       = db.Column(db.Float, default=0.0)
    unauthorized     = db.Column(db.Boolean, default=False)
    verdict          = db.Column(db.Text)
    notes            = db.Column(db.Text)
    region_json      = db.Column(db.Text)
    scanned_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id':self.id,'image_source':self.image_source,'source_type':self.source_type,
            'watermark_found':self.watermark_found,'possibly_removed':self.possibly_removed,
            'agency':self.agency,'type':self.wm_type,'location':self.location,
            'confidence':self.confidence,'unauthorized':self.unauthorized,
            'verdict':self.verdict,'notes':self.notes,
            'region':json.loads(self.region_json) if self.region_json else None,
            'scanned_at':self.scanned_at.isoformat(),
            'scanned_at_fmt':self.scanned_at.strftime('%d %b %Y, %H:%M')
        }

def make_token(uid):
    return jwt.encode(
        {'sub':uid,'iat':datetime.now(timezone.utc),
         'exp':datetime.now(timezone.utc)+timedelta(hours=24)},
        app.config['JWT_SECRET'], algorithm='HS256')

def require_auth(f):
    @wraps(f)
    def dec(*a,**kw):
        hdr = request.headers.get('Authorization','')
        if not hdr.startswith('Bearer '):
            return jsonify({'error':'Authentication required'}),401
        try:
            p = jwt.decode(hdr[7:], app.config['JWT_SECRET'], algorithms=['HS256'])
            u = db.session.get(User, p['sub'])
            if not u or not u.is_active: return jsonify({'error':'User not found'}),401
            g.current_user = u
        except jwt.ExpiredSignatureError:
            return jsonify({'error':'Token expired'}),401
        except jwt.InvalidTokenError:
            return jsonify({'error':'Invalid token'}),401
        return f(*a,**kw)
    return dec

def b64e(d): return base64.standard_b64encode(d).decode()

def get_media_type(fn):
    ext = fn.rsplit('.',1)[-1].lower()
    return {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','gif':'image/gif'}.get(ext,'image/jpeg')

def resize_if_needed(data, max_mb=4):
    if len(data) <= max_mb*1024*1024: return data
    img = Image.open(BytesIO(data)).convert('RGB')
    img.thumbnail((2048,2048), Image.LANCZOS)
    buf = BytesIO(); img.save(buf,format='JPEG',quality=85)
    return buf.getvalue()

def resize_avatar(data):
    img = Image.open(BytesIO(data)).convert('RGB')
    img.thumbnail((300,300), Image.LANCZOS)
    buf = BytesIO(); img.save(buf,format='JPEG',quality=88)
    return buf.getvalue()

PROMPT = """You are an expert sports media rights analyst.
Analyze this image for watermarks, agency marks, or copyright indicators.
Look for visible text watermarks like Getty Images AP Reuters AFP Shutterstock,
logo overlays, semi-transparent marks, copyright symbols, agency credits,
and signs of watermark removal such as blur or artifacts near edges.
Respond ONLY with valid JSON and nothing else, no markdown, no code fences, no extra text:
{"watermark_found":true or false,"possibly_removed":true or false,"agency":"name or null","type":"visible_text or logo_overlay or semi_transparent or corner_stamp or cropped_out or none","location":"describe where","confidence":0.0 to 1.0,"unauthorized":true or false,"verdict":"1 to 2 sentences","notes":"observations or empty string","region":{"top":0,"left":0,"width":0,"height":0}}"""

def call_gemini(image_b64, media_type):
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": media_type, "data": image_b64}},
            {"text": PROMPT}
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
    }
    resp = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}", headers=headers, json=body, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    raw = data['candidates'][0]['content']['parts'][0]['text'].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)

@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.get_json() or {}
    email    = (d.get('email') or '').strip().lower()
    username = (d.get('username') or '').strip()
    password = d.get('password','')
    phone    = (d.get('phone') or '').strip()
    birthday = (d.get('birthday') or '').strip()
    full_name= (d.get('full_name') or '').strip()
    if not all([email,username,password]): return jsonify({'error':'Email, username and password required'}),400
    if '@' not in email: return jsonify({'error':'Invalid email'}),400
    if len(username)<3:  return jsonify({'error':'Username min 3 chars'}),400
    if len(password)<8:  return jsonify({'error':'Password min 8 chars'}),400
    if not phone:        return jsonify({'error':'Phone number required'}),400
    if not birthday:     return jsonify({'error':'Birthday required'}),400
    if User.query.filter_by(email=email).first():    return jsonify({'error':'Email already registered'}),409
    if User.query.filter_by(username=username).first(): return jsonify({'error':'Username taken'}),409
    u = User(email=email,username=username,phone=phone,birthday=birthday,full_name=full_name)
    u.set_password(password)
    db.session.add(u); db.session.commit()
    return jsonify({'token':make_token(u.id),'user':u.to_dict()}),201

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.get_json() or {}
    email = (d.get('email') or '').strip().lower()
    pw    = d.get('password','')
    if not email or not pw: return jsonify({'error':'Email and password required'}),400
    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(pw): return jsonify({'error':'Invalid email or password'}),401
    if not u.is_active: return jsonify({'error':'Account deactivated'}),403
    u.last_login = datetime.now(timezone.utc); db.session.commit()
    return jsonify({'token':make_token(u.id),'user':u.to_dict()})

@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me(): return jsonify(g.current_user.to_dict())

@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    d = request.get_json() or {}
    if not g.current_user.check_password(d.get('old_password','')): return jsonify({'error':'Current password incorrect'}),400
    np = d.get('new_password','')
    if len(np)<8: return jsonify({'error':'Min 8 characters'}),400
    g.current_user.set_password(np); db.session.commit()
    return jsonify({'message':'Password updated'})

@app.route('/api/auth/recover', methods=['POST'])
def recover():
    d = request.get_json() or {}
    u = User.query.filter_by(email=(d.get('email') or '').strip().lower()).first()
    if not u or u.birthday!=(d.get('birthday') or '').strip() or u.phone!=(d.get('phone') or '').strip():
        return jsonify({'error':'Details do not match our records'}),400
    token = jwt.encode({'sub':u.id,'type':'recovery','exp':datetime.now(timezone.utc)+timedelta(minutes=15)},app.config['JWT_SECRET'],algorithm='HS256')
    return jsonify({'recovery_token':token})

@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    d = request.get_json() or {}
    try:
        p = jwt.decode(d.get('recovery_token',''), app.config['JWT_SECRET'], algorithms=['HS256'])
        if p.get('type')!='recovery': raise ValueError()
        u = db.session.get(User, p['sub'])
        np = d.get('new_password','')
        if len(np)<8: return jsonify({'error':'Min 8 characters'}),400
        u.set_password(np); db.session.commit()
        return jsonify({'message':'Password reset successfully'})
    except Exception as e:
        return jsonify({'error':f'Invalid recovery token: {e}'}),400

@app.route('/api/profile', methods=['PATCH'])
@require_auth
def update_profile():
    d = request.get_json() or {}; u = g.current_user
    for field,maxlen in [('full_name',150),('bio',300),('phone',30),('birthday',20)]:
        if field in d: setattr(u,field,str(d[field])[:maxlen])
    db.session.commit(); return jsonify(u.to_dict())

@app.route('/api/profile/avatar', methods=['POST'])
@require_auth
def upload_avatar():
    u = g.current_user
    try:
        if request.is_json:
            data_url = request.json.get('avatar_data_url','')
            if ',' not in data_url: return jsonify({'error':'Invalid image data'}),400
            img_bytes = base64.b64decode(data_url.split(',',1)[1])
        elif 'avatar' in request.files:
            img_bytes = request.files['avatar'].read()
        else:
            return jsonify({'error':'No avatar provided'}),400
        if len(img_bytes)>2*1024*1024: return jsonify({'error':'Max 2MB'}),400
        img_bytes = resize_avatar(img_bytes)
        u.avatar_b64 = b64e(img_bytes); db.session.commit()
        return jsonify({'message':'Avatar updated','avatar':f"data:image/jpeg;base64,{u.avatar_b64}"})
    except Exception as e:
        return jsonify({'error':f'Failed: {e}'}),400

@app.route('/api/profile/avatar', methods=['DELETE'])
@require_auth
def delete_avatar():
    g.current_user.avatar_b64 = None; db.session.commit()
    return jsonify({'message':'Avatar removed'})

@app.route('/api/detect', methods=['POST'])
@require_auth
def detect():
    u = g.current_user
    try:
        img=None; src=''; stype='file'; mt='image/jpeg'
        if 'image' in request.files:
            f = request.files['image']
            ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
            if ext not in ALLOWED_EXT: return jsonify({'error':f'Unsupported .{ext}'}),400
            img=f.read(); src=f.filename; mt=get_media_type(f.filename)
        elif request.is_json and request.json.get('image_url'):
            url = request.json['image_url'].strip()
            if not url.startswith(('http://','https://')): return jsonify({'error':'Invalid URL'}),400
            r = requests.get(url,timeout=10,headers={'User-Agent':'WatermarkWatch/3.0'})
            r.raise_for_status()
            ct = r.headers.get('Content-Type','image/jpeg').split(';')[0]
            if not ct.startswith('image/'): return jsonify({'error':'Not an image URL'}),400
            img=r.content; src=url; stype='url'; mt=ct
        else:
            return jsonify({'error':'Provide image file or image_url'}),400
        if len(img)/1024/1024>20: return jsonify({'error':'Max 20MB'}),400
        img = resize_if_needed(img)
        result = call_gemini(b64e(img), mt)
        rec = ScanRecord(user_id=u.id,image_source=src[:500],source_type=stype,
            watermark_found=result.get('watermark_found',False),
            possibly_removed=result.get('possibly_removed',False),
            agency=result.get('agency'),wm_type=result.get('type'),
            location=result.get('location'),confidence=result.get('confidence',0),
            unauthorized=result.get('unauthorized',False),
            verdict=result.get('verdict'),notes=result.get('notes'),
            region_json=json.dumps(result.get('region')) if result.get('region') else None)
        db.session.add(rec); u.scans_used+=1; db.session.commit()
        result['scan_id'] = rec.id
        app.logger.info(f"data: {result}")
        return jsonify(result)
    except requests.exceptions.RequestException as e:
        return jsonify({'error':f'URL fetch failed: {e}'}),400
    except Exception as e:
        app.logger.error(f"detect error: {e}")
        return jsonify({'error':f'Detection failed: {e}'}),500

@app.route('/api/scans', methods=['GET'])
@require_auth
def get_scans():
    pg=request.args.get('page',1,type=int)
    pp=min(request.args.get('per_page',20,type=int),100)
    p=ScanRecord.query.filter_by(user_id=g.current_user.id).order_by(ScanRecord.scanned_at.desc()).paginate(page=pg,per_page=pp,error_out=False)
    return jsonify({'scans':[s.to_dict() for s in p.items],'total':p.total,'page':pg,'pages':p.pages})

@app.route('/api/scans/<sid>', methods=['DELETE'])
@require_auth
def del_scan(sid):
    s=ScanRecord.query.filter_by(id=sid,user_id=g.current_user.id).first()
    if not s: return jsonify({'error':'Not found'}),404
    db.session.delete(s); db.session.commit(); return jsonify({'message':'Deleted'})

@app.route('/api/stats', methods=['GET'])
@require_auth
def stats():
    from sqlalchemy import func
    uid=g.current_user.id
    total=ScanRecord.query.filter_by(user_id=uid).count()
    wm=ScanRecord.query.filter_by(user_id=uid,watermark_found=True).count()
    unauth=ScanRecord.query.filter_by(user_id=uid,unauthorized=True).count()
    rem=ScanRecord.query.filter_by(user_id=uid,possibly_removed=True).count()
    top=db.session.query(ScanRecord.agency,func.count(ScanRecord.id)).filter(ScanRecord.user_id==uid,ScanRecord.agency!=None).group_by(ScanRecord.agency).order_by(func.count(ScanRecord.id).desc()).limit(5).all()
    return jsonify({'total_scans':total,'watermarks_found':wm,'unauthorized_uses':unauth,'possibly_removed':rem,'clean_images':total-wm-rem,'top_agencies':[{'agency':r[0],'count':r[1]} for r in top],'scans_used':g.current_user.scans_used})

@app.route('/api/health')
def health(): return jsonify({'status':'ok','version':'3.0-gemini'})

with app.app_context():
    db.create_all()
    print("✅  Database ready")

if __name__ == '__main__':
    if not GEMINI_API_KEY:
        print("⚠️  WARNING: GEMINI_API_KEY not set in .env file")
    print("🚀  WatermarkWatch v3 (Gemini FREE) → http://localhost:5000")
    app.run(debug=True, port=5000)
