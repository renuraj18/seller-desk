# Seller Desk

Seller Desk is a local listing manager for saree sellers on Amazon.in, Flipkart, and Meesho. The backend is FastAPI/Python with SQLite; the frontend is React, TypeScript, and Vite.

## Project layout

- `backend/app/main.py`: FastAPI application and serving `frontend/dist`.
- `backend/app/routers/`: setup, products, listings, templates, connections, and content API routes.
- `backend/app/services/`: marketplace integrations, inventory, content generation, templates, pricing, and credential encryption.
- `backend/app/schema.sql`: SQLite schema.
- `backend/tests/`: backend pytest suite.
- `frontend/src/`: React screens and shared UI/API code.
- `data/`: local database, credentials, templates, and exports; never commit its contents.

## Development commands

Run commands from the indicated directory:

```bash
# Backend tests
cd backend && python -m pytest -q

# Backend development server
cd backend && python -m uvicorn app.main:app --reload --port 8000

# Frontend checks and production build
cd frontend && npm run lint
cd frontend && npm run build

# Frontend development server (proxies /api to the backend)
cd frontend && npm run dev
```

The frontend build writes to `frontend/dist`, which the backend serves. Python dependencies are listed in `backend/requirements.txt`; Node.js is needed for frontend development and builds.

## Project guidance

- Keep the app local: it has no login and is intended to listen on `127.0.0.1`.
- Never commit databases, API keys, marketplace credentials, encryption keys, or other contents of `data/`.
- Marketplace credentials and the Anthropic API key are encrypted by `backend/app/services/secrets.py`.
- Preserve marketplace-specific content limits and template dropdown validation when changing listing generation or uploads.
- Prefer focused tests and run the relevant backend tests or frontend lint/build after changes.
