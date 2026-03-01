# Echo AI Companion

Echo AI Companion is a production-ready wellness chatbot with streaming replies, sentiment-aware responses, persistent chat history, shareable read-only snapshots, and an admin analytics console.

## Key Features
- Real-time streaming chat with multi-thread conversations.
- Per-user chat isolation by `client_id`.
- Smart sentiment adaptation (`positive`, `neutral`, `negative`, `crisis`).
- Memory cards with quick prompt autofill.
- Mobile swipe gesture to open/close sidebar.
- Share links that open a read-only snapshot (`/shared/<share_id>`).
- Assistant-only pinning with quick jump-to-message.
- Voice input transcription (microphone to text input).
- Admin dashboard with:
1. mood timeline bars
2. mood calendar
3. search and sentiment/client filters
4. top keywords and top active clients
5. CSV export
6. email operations/health section

## Architecture
- Frontend: React + TypeScript + Vite + Tailwind CSS.
- Backend: Flask (Python) served via Vercel serverless functions.
- Storage:
1. MongoDB (`MONGODB_URI`) preferred for persistent production data
2. Postgres fallback (if configured)
3. Local file fallback for local/dev scenarios

## Backend Structure
- `backend/index.py`: thin facade exporting stable backend API functions.
- `backend/main.py`: compatibility entrypoint (`from index import *`).
- `backend/core_engine.py`: legacy core implementation (kept intact for stability during refactor).
- `backend/services/threads_service.py`: thread lifecycle functions.
- `backend/services/chat_service.py`: chat streaming + summaries.
- `backend/services/share_service.py`: share-link create/import/render.
- `backend/services/admin_service.py`: admin logs + email health/test endpoints.

This modular split reduces coupling at the entrypoint and makes further extraction from `core_engine.py` safer and incremental.

## Core Routes
- App: `/`
- Shared preview route: `/shared/<share_id>`
- Admin page: `/admin?key=<ADMIN_KEY>`
- API:
1. `POST /api/get_threads`
2. `POST /api/create_thread`
3. `POST /api/delete_thread`
4. `POST /api/chat_streaming`
5. `POST /api/create_share_link`
6. `POST /api/import_shared_thread`
7. `GET /api/admin_logs?key=<ADMIN_KEY>`
8. `GET /api/admin_email_health?key=<ADMIN_KEY>`
9. `POST /api/admin_send_test_email?key=<ADMIN_KEY>`

## Environment Variables
Set these in Vercel Project Settings (or via `vercel env`):

- `MONGODB_URI`: MongoDB Atlas connection string.
- `ADMIN_KEY`: admin dashboard query key.
- `ECHO_TZ`: timezone label, e.g. `Africa/Accra`.
- `ECHO_USER_ORIGIN`: optional profile context.
- `ECHO_USER_CITY`: optional profile context.
- `ECHO_USER_SLANG`: optional style hint.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`: SMTP settings for email features.
- `ECHO_ALERT_EMAIL_TO`: destination email for alerts.
- `ECHO_EMAIL_COOLDOWN_MIN`: cooldown window for event emails.
- `ECHO_FUN_EMAIL_ENABLED`: set `false` to disable fun/trigger emails.

## Local Development
### Prerequisites
- Node.js 18+
- Python 3.10+

### Setup
```powershell
cd frontend
npm install
cd ..

python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Run
```powershell
# Terminal 1
cd frontend
npm run dev

# Terminal 2
python api\vercel_app.py
```

## Deploy
```powershell
npx vercel --prod
```

## Security Notes
- Do not commit `.env` files or credentials.
- Use a strong `ADMIN_KEY`.
- Rotate credentials immediately if exposed.
- Restrict database and SMTP account permissions.

## Repository Description (Suggested)
`Wellness-focused AI chat companion with streaming responses, sentiment-aware guidance, read-only shared chat snapshots, and advanced admin analytics on Vercel.`

## Maintainer
Lanor Jephthah Kwame (McLanor)
