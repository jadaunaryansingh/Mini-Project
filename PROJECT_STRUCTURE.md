# Project Structure and Architecture

## Repository layout

```
Mini-Project/
├── api.py                     # FastAPI API: voice processing, auth, authorization
├── index.html                 # Single-page web UI
├── requirements.txt           # Python dependencies
├── voice_db.pkl               # Speaker embedding database
├── firebase/
│   ├── firebase-config.js     # Web Firebase SDK bootstrap
│   ├── firebase-auth.js       # Sign in/up, token/session helpers
│   └── firebase-db.js         # Realtime DB profile/history persistence
├── API_DOCUMENTATION.md       # Endpoint contracts and auth rules
├── SETUP.md                   # Setup and deployment notes
├── FIREBASE_SETUP.md          # Firebase project and DB rules setup
├── README.md                  # Overview
└── PROJECT_STRUCTURE.md       # This document
```

## Runtime architecture

### 1) Frontend layer (`index.html`)
- Handles login (Firebase Auth), recording, waveform/spectrogram visualization, and user actions.
- Computes live quality metrics during recording:
	- loudness
	- clipping safety
	- voice activity
- Requests Firebase ID token and attaches it as bearer token to protected API calls.

### 2) Authentication and authorization boundary
- Firebase Auth in browser issues ID token.
- FastAPI backend validates token with Firebase Admin SDK.
- Authorization policy:
	- authenticated users: `/authenticate`, `/verify`
	- admin users only: `/enroll`

### 3) Backend inference layer (`api.py`)
- Loads speaker embeddings from `voice_db.pkl`.
- Uses Resemblyzer encoder for embedding extraction from uploaded/recorded voice samples.
- Performs similarity-based identification/verification.
- Returns detailed decision feedback (reasons, threshold gap, recommended next steps).

### 4) Data persistence
- Voice embeddings are persisted in `voice_db.pkl` (local file database).
- User activity history and profile metadata are persisted in Firebase Realtime Database.

## Request flow

1. User signs in from web UI.
2. UI retrieves Firebase ID token.
3. UI sends protected API call with `Authorization: Bearer <token>`.
4. Backend validates token and checks role.
5. Backend computes voice similarity and sends result + actionable feedback.
6. UI displays result and stores audit/history events in Firebase Realtime Database.

## Security controls in code

- Token-based authentication on sensitive routes.
- Role-based authorization for enrollment.
- Rate limiting (`slowapi`).
- CORS middleware.
- Security headers (`X-Frame-Options`, `X-Content-Type-Options`, etc.).
- Input validation for file type, speaker name, and request fields.
