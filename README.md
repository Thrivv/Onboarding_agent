# Thrivv Onboarding Agent 🤖

## Overview
An AI-powered **corporate banking onboarding** solution. Customers sign up, chat with an AI assistant, upload their business and identity documents, and the system extracts, validates and cross-checks the data, collects compliance declarations (FATCA, PEP), recommends a product package and finishes with a summary PDF, all through a web chat UI with email notifications and email-reply handling.

> **Version:** AWS version. All LLM and vision calls go through **AWS Bedrock** (Claude). Earlier versions used LLaMA / OpenRouter / OpenAI / RunPod; those are no longer used.

## How the flow works

Simple user flow: https://app.eraser.io/workspace/FQmvDxD5qShw6AKDi75e?origin=share

1. **Sign up / log in** with email OTP verification and password reset.
2. **Upload the Commercial (Trade) License.** The ownership type (Single Owner / Partnership / Multiple Owners) is auto-detected from it, so the user is no longer asked up front.
3. **Collect the remaining documents** for that ownership type (see below), with real-time extraction and validation.
4. **Key Individuals (KI) and members.** Add owners and authorised signatories, assign roles, confirm UBOs, and resolve role mismatches.
5. **Compliance:** FATCA and PEP declarations.
6. **Product package:** choose Essential, Plus or Advanced.
7. **Self-declaration** and a final confirmation, then a completion email with an onboarding summary PDF.

Users can also reply to onboarding emails. The `reply-loop` service polls the inbox over IMAP and feeds replies back into the same flow.

## Key Features 🌟

### Document Processing Engine
- **Supported documents**
  - Commercial / Trade License
  - Memorandum of Association (MOA)
  - Ejari (Tenancy Contract)
  - Emirates ID (EID)
  - Passport (accepted in place of EID)
  - Certificate of Incorporation / BVI documents for corporate shareholders
- **Extraction:** Bedrock vision and text models, with specialised extractors per document type (`services/specialized_ocr/`).
- **Optional Amazon Textract AnalyzeID** for passports (`TEXTRACT_ANALYZE_ID_ENABLED`).
- **Tampering / forgery detection:** JPEG quantization, error-level analysis, copy-move detection, font consistency and metadata checks, combined by a decision engine with LLM analysis.
- **Validation:** document expiry checks, cross-validation of data across documents, optional **SurePass** EID validation against government records, and fuzzy name matching.
- **Privacy:** PII masking in logs (`PII_LOG_MASKING_ENABLED`) and image redaction.
- **Bulk upload** and **document history / versioning** with preview and download.

### Intelligent Onboarding Flows
- **Account type:** Corporate
  - **Single Owner** (sole proprietorship): Commercial License → MOA → Ejari → EID/Passport
  - **Partnership / Multiple Owners:** Commercial License, Ejari and MOA first, then EID or Passport for each member, then corporate-shareholder documents where needed
- **Orchestration:** explicit stage table plus a **LangGraph** state graph with a Postgres checkpointer, so paused conversations resume where they left off. It runs in shadow mode first, and `LANGGRAPH_CHANNEL_CUTOVER` lets the graph drive real users.
- **Key individual management:** UBO confirmation, role assignment, authorised-signatory selection, member reconciliation.
- **Compliance:** FATCA and PEP forms.
- **Product packages:** Essential, Plus and Advanced, with a recommendation based on the nature of business.
- **Automated emails:** verification, resubmission links, document confirmation and completion email with summary PDF.
- **Admin dashboard:** protected routes for user counts, verification progress and onboarding summaries.

### AI Assistant
- Natural-language chat (conversational upload and conversational Q&A)
- Context-aware responses based on the user's current stage and documents
- Document requirement guidance and FAQ support
- LLM-generated messages with timeouts and retries, and the brand name configurable via `BRAND_NAME`

### Multilingual Support 🌍
- **English, Arabic (RTL) and Spanish** across the chat, UI cards and reports.
- A language toggle in the UI. The frontend sends `X-User-Language` on every request, and the backend mirrors the language in AI replies.
- The kill switch `LANGUAGE_TOGGLE_ENABLED` locks the app to English. The backend also enforces it, so stale clients can't bypass it.
- `./i18n-guard.sh` fails if hardcoded English creeps back into the frontend (run it locally or in CI).

## Tech Stack 🛠️

| Component | Technology |
|-----------|------------|
| Backend | Python 3.11, FastAPI, Uvicorn, SlowAPI (rate limiting) |
| Frontend | React 18 (Create React App), Tailwind CSS, React Router, Framer Motion, Recharts |
| Database | Supabase (Postgres). Migrations in `supabase/migrations/` |
| AI / LLM | AWS Bedrock (Anthropic Claude: Haiku by default, optional Sonnet reasoning tier) |
| Orchestration | LangGraph and `langgraph-checkpoint-postgres` |
| Doc processing | PyMuPDF, PyPDF2, Pillow, OpenCV (headless), NumPy / SciPy, ReportLab / fpdf2 (summary PDFs) |
| Email | SMTP (outbound), IMAP (inbound reply listener) |
| Identity validation | SurePass (optional), Amazon Textract AnalyzeID (optional) |
| Runtime | Docker, Nginx and Supervisord (one combined container) |

## Architecture

```
                 ┌───────────────────────── app container ─────────────────────────┐
 Browser ──:9000─▶  Nginx  ──/onboarding/ai/      → React build (static)            │
                 │          ──/onboarding/ai/api/ → FastAPI (Uvicorn, :7000)        │
                 │          ──/health             → FastAPI /health                 │
                 │  Supervisord manages: backend · nginx · logrotate                │
                 └──────────────────────────────────────────────────────────────────┘
                 ┌─────────────────────── reply-loop container ────────────────────┐
 IMAP inbox ◀────▶  python -m app.services.reply_loop  (polls every 10s)            │
                 └──────────────────────────────────────────────────────────────────┘
        Both containers ──▶ Supabase (Postgres) · AWS Bedrock · SMTP/IMAP
```

The app is served under the base path **`/onboarding/ai`** (API under `/onboarding/ai/api`).

## Setup Guide 🚀

### Prerequisites
```bash
docker (with docker compose v2, or docker-compose v1)
# For running outside Docker:
python >= 3.11
node >= 18
```
You also need a Supabase project, an AWS Bedrock API key with access to the Claude model in your region, and a mailbox with SMTP and IMAP access (use an **app password**).

### Environment Variables

All configuration lives in a single file at the repo root, **`.env.docker`**. It is loaded by Docker Compose, and the backend also loads it when run locally. **Never commit it**: `.env.*` is git-ignored.

**Required**
```env
# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_API_KEY=your_supabase_key

# Security (the app refuses to start without PASSWORD_SECRET_KEY)
PASSWORD_SECRET_KEY=long_random_secret        # e.g. openssl rand -hex 32
JWT_SECRET_KEY=another_long_random_secret

# AWS Bedrock (all LLM / vision / OCR calls)
AWS_BEARER_TOKEN_BEDROCK=your_bedrock_api_key

# Email: outbound (SMTP) and inbound reply listener (IMAP)
SMTP_SERVER=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_mailbox
SMTP_PASSWORD=your_mailbox_app_password       # app password, not your login password
FROM_EMAIL=Organisation Name <no-reply@example.com>
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USER=your_mailbox
IMAP_PASSWORD=your_mailbox_app_password
```

**Common optional settings**
```env
# Sessions
SESSION_TIMEOUT=3600
INACTIVITY_THRESHOLD_MINUTES=30
SESSION_TOKEN_EXPIRY_HOURS=24
SESSION_COOKIE_SECURE=true                    # set false only for plain-HTTP local dev
ALLOWED_ORIGINS=
API_BASE_URL=                                 # public URL used in email callback links

# Feature flags
LANGUAGE_TOGGLE_ENABLED=true                  # EN / AR / ES toggle (false = English only)
LANGGRAPH_ENABLED=true                        # LangGraph shadow mode
LANGGRAPH_CHANNEL_CUTOVER=false               # let the graph drive real users
LANGGRAPH_PG_DSN=                             # direct Postgres DSN for the checkpointer
PII_LOG_MASKING_ENABLED=true
MODEL_TIERING_ENABLED=false                   # use a stronger model for Trade License and MOA
BEDROCK_REASONING_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0
TEXTRACT_ANALYZE_ID_ENABLED=false
OTP_EMAIL_LLM_PERSONALIZATION_ENABLED=false
BRAND_NAME=Thrivv

# ⚠️ QA / test environments ONLY: accepts ANY 6-digit OTP. Never enable in production.
OTP_BYPASS_ENABLED=false

# Document validation
CROSS_VALIDATION_CORPORATE_SINGLE=true
CROSS_VALIDATION_CORPORATE_PARTNERSHIP=false
EID_VALIDATION_CORPORATE_SINGLE=false
EID_VALIDATION_CORPORATE_PARTNERSHIP=false
SUREPASS_JWT_TOKEN=
SUREPASS_API_URL=

# LLM and extraction tuning
LLM_CALL_TIMEOUT_SECONDS=45
MESSAGE_GEN_MAX_RETRIES=2
DOC_EXTRACTION_MAX_RETRIES=3
EJARI_API_TIMEOUT_SECONDS=60
MOA_API_TIMEOUT_SECONDS=60
TRADE_LICENSE_API_TIMEOUT_SECONDS=60
BVI_API_TIMEOUT_SECONDS=90
PASSPORT_API_TIMEOUT_SECONDS=60

# Runtime and logging
UVICORN_WORKERS=1                             # keep at 1 (OTPs are held in process memory)
LOG_LEVEL=INFO
LOG_STYLE=plain
```

> `UVICORN_WORKERS` must stay at `1` until the in-memory OTP store is moved to Supabase or Redis. See the comments in `supervisord.conf`.

**Frontend** (`frontend/.env`, used by `npm start` only; the Docker build sets this automatically):
```env
REACT_APP_API_URL=/onboarding/ai/api
REACT_APP_SESSION_TIMEOUT=3000000
PORT=3030
```

### Database Setup
Schema changes are tracked as Supabase CLI migrations in `supabase/migrations/` (details in `supabase/README.md`).

```bash
supabase link --project-ref <your-project-ref>
supabase db push
```
For a fresh project you can also run `supabase/complete_schema.sql`.

### Installation Steps

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/onboarding-agent.git
cd onboarding-agent
```

2. **Configure the environment**
```bash
# Create .env.docker at the repo root and fill in the variables above
```

3. **Build and run**
```bash
./start.sh                 # checks Docker and .env.docker, builds, starts everything
# or manually:
docker compose up --build
```

4. **Access the services**
- App (UI and API via Nginx): http://localhost:9000, which redirects to `/onboarding/ai/`
- Backend API directly: http://localhost:7000 (API base path `/onboarding/ai/api`)
- Health check: http://localhost:9000/health
- Interactive API docs (FastAPI default): http://localhost:7000/docs

### Helper Scripts

| Script | Purpose |
|--------|---------|
| `start.sh` | Check prerequisites and start all containers |
| `stop.sh` | Stop all containers |
| `rebuild.sh` | Stop and rebuild the image from scratch |
| `deploy.sh` | Full deploy on an AWS host |
| `status.sh` | Container status and health checks |
| `logs.sh [app\|reply-loop]` | Tail container logs |
| `i18n-guard.sh` | Fail if hardcoded English or untranslated strings creep into the frontend |

### Running Locally (without Docker)
```bash
# Backend
cd backend
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 7000 --reload

# Reply listener (separate terminal)
PYTHONPATH=. python -u -m app.services.reply_loop

# Frontend
cd frontend
npm install
npm start          # http://localhost:3030
```

## Project Structure 📁
```
onboarding-agent/
├── Dockerfile                  # multi-stage: React build → Python + Nginx + Supervisord
├── docker-compose.yml          # app (Nginx + API) and reply-loop services
├── nginx-combined.conf         # serves SPA, proxies /onboarding/ai/api to FastAPI
├── supervisord.conf            # runs backend, nginx and logrotate
├── .env.docker                 # all runtime configuration (git-ignored)
├── start.sh / stop.sh / rebuild.sh / deploy.sh / status.sh / logs.sh / i18n-guard.sh
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             # FastAPI app, middleware, routers, /health
│   │   ├── config.py           # single source of truth for env vars
│   │   ├── api/routes/         # auth, register, otp, chat, onboarding/*, documents/*, system, frontend_logs
│   │   ├── domain/
│   │   │   ├── documents/      # discovery, normalizer, preview, status, member progress
│   │   │   └── onboarding/     # stage table, stages, members, confirmation, graph/ (LangGraph)
│   │   ├── services/
│   │   │   ├── bedrock_client.py, llm_client.py   # Bedrock transport and shared LLM helper
│   │   │   ├── specialized_ocr/                   # trade, MOA, Ejari, passport, BVI extractors
│   │   │   ├── tampering/                         # forensic modules and decision engine
│   │   │   ├── cross_validator.py, eid_validation.py, document_expiry_validator.py
│   │   │   ├── fatca_service.py, pep_service.py, key_individual_service.py, product_package_service.py
│   │   │   ├── mail/, email_sender.py, email_listener.py, handle_reply.py, reply_loop.py
│   │   │   └── pdf_summary_service.py, textract_id_client.py, image_redaction_service.py
│   │   ├── repositories/       # Supabase data access
│   │   ├── schemas/            # Pydantic models
│   │   ├── i18n/               # backend message catalogues (EN / AR / ES)
│   │   └── utils/              # language, pii_masker, retry, behaviour_capture
│   ├── scripts/                # maintenance and repair scripts
│   ├── tests/                  # parity, contract, OCR corpus, i18n and PII tests
│   ├── documents/              # uploaded documents (volume-mounted)
│   └── summary/                # generated summary PDFs (volume-mounted)
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx             # routes: /login /signup /reset-password /dashboard /ai-assistant
│       ├── api/                # axios clients per domain
│       ├── context/            # Auth and Language contexts
│       ├── i18n/               # translations.js (EN / AR / ES)
│       ├── pages/              # Login, Signup, ResetPassword, Dashboard, NotFound
│       └── features/onboarding/  # chat page, cards, extracted-data views, compliance forms, modals
├── supabase/
│   ├── complete_schema.sql
│   ├── migrations/             # timestamped Supabase CLI migrations
│   └── README.md
└── logs/                       # backend, nginx, supervisor, frontend, reply-loop (volume-mounted)
```

## Testing & Quality
- Backend checks live in `backend/tests/`: LangGraph parity (`langgraph_parity_check.py`), route contract checks, golden fixtures, an OCR corpus, i18n flow and PII masker tests.
- Frontend: `npm test` (i18n flow and report tests under `features/onboarding/utils/__tests__`).
- `./i18n-guard.sh` for language-regression checks.

## Security Notes 🔒
- Passwords are hashed with bcrypt plus a server-side pepper (`PASSWORD_SECRET_KEY`). The app will not boot without it.
- Session cookies are httpOnly and `Secure` by default. API routes are rate-limited.
- OTPs are never sent to the LLM. Logs mask extracted PII.
- Keep `.env.docker` out of version control, and make sure `OTP_BYPASS_ENABLED` is `false` in production.

## License & Legal
Proprietary. All rights reserved.
