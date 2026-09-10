# CareerPath Backend Service

FastAPI-powered core backend service for personalized learning roadmap generation, assessment processing, quiz grading, audio streaming, and streak analytics.

## Tech Stack
- **Framework**: FastAPI (Python 3.11+)
- **ORM & DB**: SQLAlchemy + PyMySQL (MySQL 8.0)
- **Caching & Message Broker**: Redis (`redis>=5.0.0`)
- **LLM / AI Generation**: Google Generative AI (Gemini Flash / Pro)
- **TTS**: Edge-TTS with file-based streaming & caching
- **ASGI Server**: Uvicorn / Gunicorn

## Setup & Running

### 1. Prerequisites
- Python 3.11+
- MySQL 8.0+
- Redis 6.0+

### 2. Environment Setup
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env` and configure:
```ini
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/careerpath_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
GEMINI_API_KEY=your-gemini-api-key
AUTH_SERVICE_URL=http://localhost:8001
```

### 4. Run Service
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Documentation
Once running, explore the interactive documentation:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Modules
- `app/routers/placement_test_router.py`: Diagnostic placement test and user roadmaps
- `app/routers/lesson_router.py`: Modular lesson content, units, and progress
- `app/routers/quiz_router.py`: Formative and summative quiz grading with AI feedback
- `app/routers/audio_router.py`: Edge-TTS audio stream generation and caching
- `app/routers/user_router.py`: User profile, streak statistics, and study time settings
- `app/routers/admin_router.py`: Admin statistics and killswitch controls
