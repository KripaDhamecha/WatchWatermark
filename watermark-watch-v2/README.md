# WatermarkWatch v2 🛡️
### AI-Powered Sports Watermark Detector — with Auth & Database

---

## What's new in v2

| Feature | v1 | v2 |
|---------|----|----|
| Watermark detection | ✅ | ✅ |
| User accounts / login | ❌ | ✅ |
| JWT auth + protected routes | ❌ | ✅ |
| SQLite database | ❌ | ✅ |
| Scan history saved | ❌ | ✅ |
| Dashboard with stats | ❌ | ✅ |
| Monthly scan quota | ❌ | ✅ |
| Password change | ❌ | ✅ |
| Multi-page app | ❌ | ✅ |

---

## Project Structure

```
watermark-watch-v2/
├── backend/
│   ├── server.py           ← Flask API (auth + detection + DB)
│   ├── requirements.txt    ← Python dependencies
│   └── .env.example        ← Environment variable template
│
└── frontend/
    ├── index.html          ← Landing page (redirects if logged in)
    ├── src/
    │   ├── global.css      ← Shared styles
    │   └── utils.js        ← Auth helpers, API fetch, toast
    └── pages/
        ├── login.html      ← Login page
        ├── register.html   ← Registration page
        ├── dashboard.html  ← User dashboard + scan history
        ├── detector.html   ← Image scanner (protected)
        └── account.html    ← Account settings + change password
```

---

## Setup — Step by Step

### Step 1 — Get your Anthropic API key
1. Go to https://console.anthropic.com
2. Sign in → API Keys → Create Key
3. Copy the key (starts with `sk-ant-...`)

---

### Step 2 — Set up the backend

```bash
# Navigate to backend folder
cd watermark-watch-v2/backend

# Create Python virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt

# Create your .env file
cp .env.example .env
```

Open `.env` in a text editor and fill in:
```
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
JWT_SECRET=generate-a-long-random-string-here
```

To generate a secure JWT secret:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### Step 3 — Start the backend

```bash
# Make sure you're in backend/ with venv active
python server.py
```

Expected output:
```
✅  Database tables created/verified
🚀  WatermarkWatch v2 backend on http://localhost:5000
```

The SQLite database file `watermarkwatch.db` is created automatically in the backend folder.

---

### Step 4 — Serve the frontend

Open a **new terminal** (keep backend running):

```bash
cd watermark-watch-v2/frontend

# Serve with Python (recommended)
python -m http.server 3000
```

Then open http://localhost:3000 in your browser.

---

### Step 5 — Use the app

1. **Register** a new account at http://localhost:3000/pages/register.html
2. You'll be taken to the **Dashboard** automatically
3. Click **Scan Image** in the sidebar
4. Upload a sports image or paste a URL
5. Click **Scan** — results appear with agency, confidence, and verdict
6. Go back to **Dashboard** to see your scan history and stats
7. Visit **Account** to change your password

---

## API Reference

All detection endpoints require a JWT token in the Authorization header:
```
Authorization: Bearer <your_token>
```

### Auth endpoints (no token required)

| Method | Endpoint | Body |
|--------|----------|------|
| POST | `/api/auth/register` | `{email, username, password}` |
| POST | `/api/auth/login`    | `{email, password}` |
| GET  | `/api/auth/me`       | — (token required) |
| POST | `/api/auth/change-password` | `{old_password, new_password}` |

### Detection endpoints (token required)

| Method | Endpoint | Body |
|--------|----------|------|
| POST | `/api/detect` | multipart `image` file OR `{image_url}` |
| POST | `/api/detect/batch` | `{image_urls: [...]}` |
| GET  | `/api/scans` | `?page=1&per_page=20` |
| GET  | `/api/scans/<id>` | — |
| DELETE | `/api/scans/<id>` | — |
| GET  | `/api/stats` | — |

### Example: Login + scan with curl

```bash
# 1. Login and get token
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@test.com","password":"yourpassword"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 2. Scan image
curl -X POST http://localhost:5000/api/detect \
  -H "Authorization: Bearer $TOKEN" \
  -F "image=@sports_photo.jpg"
```

---

## Database Schema

**users table**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| email | String | Unique, indexed |
| username | String | Unique |
| password_hash | String | bcrypt hashed |
| plan | String | free / pro / enterprise |
| scans_used | Integer | Resets monthly |
| scans_limit | Integer | 10 for free plan |
| created_at | DateTime | UTC |
| last_login | DateTime | UTC |
| is_active | Boolean | Account status |

**scans table**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | Foreign key → users |
| image_source | String | Filename or URL |
| watermark_found | Boolean | |
| agency | String | Detected agency |
| confidence | Float | 0.0–1.0 |
| unauthorized | Boolean | |
| verdict | Text | Plain-English verdict |
| region_json | Text | JSON bounding box |
| scanned_at | DateTime | UTC |

---

## Security features

- Passwords hashed with **bcrypt** (salt rounds = 12)
- **JWT tokens** expire in 24 hours
- All detection routes are **protected** — unauthenticated requests get 401
- Frontend auto-redirects to login if token is missing or expired
- **Rate limiting**: free plan users are limited to 10 scans/month enforced server-side
- Input validation on all auth fields
- Image URL validation (must be http/https, must return image content type)

---

## Deploying to Production

### Backend → Render
1. Push to GitHub
2. Render → New Web Service → connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn server:app`
5. Environment variables: `ANTHROPIC_API_KEY`, `JWT_SECRET`
6. For production, consider switching to **PostgreSQL** (change DATABASE_URI in .env)

### Frontend → Netlify
1. In `frontend/src/utils.js` line 3, change:
   ```js
   const API = 'http://localhost:5000';
   ```
   to your Render URL:
   ```js
   const API = 'https://your-app.onrender.com';
   ```
2. Drag `frontend/` folder to Netlify deploy zone

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` with venv active |
| `ANTHROPIC_API_KEY not set` | Edit `backend/.env` and add key |
| Login says "Invalid email or password" | Register first at /pages/register.html |
| CORS errors | Use `python -m http.server` not direct file open |
| Scan limit reached | Free plan = 10/month (resets next month) |
| DB locked error | Only run one instance of the backend at a time |
