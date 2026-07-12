# Core API Service

The Core API Service is the central administrative and persistence engine for the iBot platform. It provides the database schema management, business logic, recruiter authentication, candidate assessments, resume parsing, and asynchronous notifications (such as candidate invitations and emails).

---

## Technical Stack
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+)
- **Database ORM:** [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (Asyncio with `asyncpg`)
- **Database Engine:** PostgreSQL with [pgvector](https://github.com/pgvector/pgvector) extension (for vector search & indexing)
- **Database Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
- **Background Tasks:** [Celery](https://docs.celeryq.dev/) (with Redis backend)
- **Caching & Broker:** [Redis](https://redis.io/)
- **Linting & Formatting:** [Ruff](https://github.com/astral-sh/ruff)
- **Static Typing:** [Mypy](https://mypy-lang.org/)
- **Dependency Manager:** [uv](https://github.com/astral-sh/uv)

---

## Directory Structure
```text
core-api-service/
├── src/
│   ├── api/                   # FastAPI routing, endpoints, and middleware
│   ├── config/                # Pydantic Settings configuration loading
│   ├── core/                  # Core domain logic
│   │   ├── exceptions/        # Custom domain & API exception classes
│   │   └── services/          # Business services (auth, candidate, assessment, sessions, notifications)
│   ├── data/                  # Data access layer
│   │   ├── clients/           # Database, Redis, and Celery connection pools
│   │   ├── migrations/        # Alembic database schema migrations
│   │   └── models/            # SQLAlchemy database declarations
│   ├── handlers/              # Celery background workers tasks (emails, assessment processing)
│   ├── schemas/               # Pydantic request, response, and storage schemas
│   └── utils/                 # General helpers (JWT generation, password hashing, file parsing)
├── tests/                     # Unit and integration tests (pytest-asyncio)
├── pyproject.toml             # uv / PEP-518 project definition
└── Dockerfile                 # Multi-stage production container definition
```

---

## Core Services & Responsibilities
- **Authentication Service (`auth_service.py`):** Handles recruiter registration, secure password hashing (using bcrypt), and JWT generation.
- **Candidate Service (`candidate_service.py`):** Manages candidate profiles and processes resume attachments (extracting text from PDFs via PyMuPDF).
- **Assessment Service (`assessment_service.py`):** Creates assessments, matches candidates to assessments, and structures evaluation categories.
- **Interview Session Service (`interview_session_service.py`):** Tracks candidate session cycles (registered, waiting, active, evaluating, completed).
- **Notification Service (`notification_service.py`):** Sends automated HTML email invitations, verification codes, and assessment summaries via Brevo/Resend.

---

## Local Development & Setup

### 1. Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) installed on your system.
- Running PostgreSQL (with pgvector) and Redis instances (typically via the root `docker-compose.yml`).

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in the required keys:
```bash
cp .env.example .env
```
Key configuration options:
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_HOST`: PostgreSQL access.
- `REDIS_HOST` / `REDIS_PORT`: Broker configuration.
- `GROQ_API_KEY`: API access for fallback models.
- `BREVO_API_KEY` / `BREVO_SENDER_EMAIL`: Email gateway settings.

### 3. Install Dependencies
Initialize the virtual environment and install dependencies:
```bash
uv sync --group dev
```

### 4. Database Migrations
Run Alembic migrations to align database schemas:
```bash
# Apply migrations to the head
uv run alembic upgrade head

# Generate a new migration revision
uv run alembic revision --autogenerate -m "description of changes"
```

### 5. Running the Backend Server
Start the Uvicorn web server locally:
```bash
uv run uvicorn src.api.rest.app:app --host 127.0.0.1 --port 8000 --reload
```
The API docs will be available at `http://127.0.0.1:8000/docs`.

### 6. Running the Celery Background Worker
To execute background tasks (emails, PDF parsing):
```bash
uv run celery -A src.data.clients.celery_client.celery_app worker --loglevel=INFO --queues=core.assessment,core.email,core.default --pool=solo
```

---

## Verification & Code Quality
Maintain code standards by running the following checks before committing code:

```bash
# Format check
uv run ruff format --check src tests

# Style & lint check
uv run ruff check src tests

# Static type checking
uv run mypy src

# Run pytest unit tests
uv run pytest
```
