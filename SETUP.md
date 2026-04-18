# Setup Guide — VoxGuard

## Prerequisites

- Python 3.10+
- Node/npm (optional, for tooling)

## Steps

1. **Virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Firebase**
   - Create a project at [Firebase Console](https://console.firebase.google.com)
   - Enable Authentication (Email/Password or desired method)
   - Copy config values into a `.env` file (see `.env.example` if present)

4. **Run API**
   ```bash
   uvicorn api:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Open app**
   - Visit `http://localhost:8000` or open `index.html` and point it to the API URL.

## Environment variables

- `FIREBASE_API_KEY`
- `FIREBASE_AUTH_DOMAIN`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`
- `FIREBASE_MESSAGING_SENDER_ID`
- `FIREBASE_APP_ID`
- `FIREBASE_MEASUREMENT_ID`
- `FIREBASE_DATABASE_URL`

Backend authentication and authorization:

- `AUTH_REQUIRED=true`
- `FIREBASE_SERVICE_ACCOUNT_PATH=C:\\path\\to\\serviceAccountKey.json`
- `ADMIN_EMAILS=admin1@example.com,admin2@example.com`
- `ADMIN_UIDS=uid_1,uid_2`

Notes:
- For production, keep `AUTH_REQUIRED=true`.
- For local testing without Firebase Admin, set `AUTH_REQUIRED=false`.
- `FIREBASE_SERVICE_ACCOUNT_JSON` can be used instead of file path when deploying via secret manager.

## Verify end-to-end security

1. Sign in from UI with Firebase.
2. Confirm protected calls succeed (`/verify`, `/authenticate`).
3. Confirm enrollment requires admin role (`/enroll` should return 403 for non-admin).
4. Open `/docs` to inspect protected endpoints and payload contracts.

Do not commit `.env`; it is listed in `.gitignore`.
