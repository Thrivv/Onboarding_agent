# Onboarding Agent 🤖

## Overview
An AI-powered banking onboarding solution that streamlines document processing and customer verification using the Email interface. 
## How the flow works

Simple user flow - 


## Key Features 🌟

### Document Processing Engine
- **Supported Documents**
  - Emirates ID (EID)
  - Commercial/Trade License
  - Tenancy Contract (Ejari)
  - Memorandum of Association (MOA)
- **Language Support**: English & Arabic(in progress)
- **Real-time Validation**

### Intelligent Onboarding Flows
- **Account Types**
  - Savings Account
  - Corporate Account
    - Single Owner
    - Multiple Owners
- **Smart Document Collection**
- **Automated Email Updates**
- **Quicker Onboarding**

### AI Assistant
- Natural language interface
- Context-aware responses
- Document requirement guidance
- FAQ support

## Tech Stack 🛠️

| Component | Technology |
|-----------|------------|
| Backend | FastAPI, Python |
| Frontend | Streamlit |
| Database | Supabase |
| AI/ML | LLaMA, ChromaDB |
| Doc Processing | PyMuPDF |
| Container | Docker |

## Setup Guide 🚀

### Prerequisites
```bash
python >= 3.11
docker
docker-compose
```

### Environment Variables (Frontend)
```env
SUPABASE_URL=your_supabase_url
SUPABASE_API_KEY=your_api_key
```

### Environment Variables (Backend)
```env
SUPABASE_URL=your_supabase_url
SUPABASE_API_KEY=your_api_key
SMTP_SERVER=your_smtp_server
SMTP_PORT=your_smtp_port
SMTP_USERNAME=your_primary_email(for sending and receiving mails)
SMTP_PASSWORD=your_primary_email_app_password(not your email password but app password for the particular mail)
FROM_EMAIL=Name of the Organisation <email of the orgnisation>
IMAP_HOST=host_of_themail
IMAP_PORT=port_of_the_hosted_mail
IMAP_USER=mail_of_the_user
IMAP_PASSWORD=app_password_of_the_mail
OPENROUTER_API_KEY= your_open_router_API_key
OPENAI_API_KEY = your_openai_api_key
RUNPOD_API_KEY= your_runpod_api_key (only for local model usage)
RUNPOD_ENDPOINT_ID= your_runpod_endpoint (only for local model usage)
RUNPOD_MODEL_NAME= your_runpod_model_name (only for local model usage)
```

### Installation Steps

1. **Clone Repository**
```bash
git clone https://github.com/yourusername/onboarding-agent.git
cd onboarding-agent
```

2. **Configure Environment**
```
Setup the .env for both Frontend as well as backend.
```

3. **Build & Run**
```bash
docker-compose up --build
```

4. **Access Services**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Database: http://localhost:8002

## Project Structure 📁
```
onboarding-agent/
├── backend/
│   ├── app/
│   ├── specialized_ocr/
│   ├── llm_pipeline/
│   └── ingestion/
├── frontend/
│   └── streamlit_app.py
└── database/
    └── database_service.py
```

## License & Legal 
Proprietary. All rights reserved.