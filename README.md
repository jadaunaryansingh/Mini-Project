# VoxGuard - Voice Authentication

Speaker identification system using deep learning. Enroll voice profiles and verify users by voice.

## Features

- Voice enrollment and verification
- Firebase authentication
- User history tracking
- Mel-spectrogram analysis with Resemblyzer
- Detailed decision feedback for authentication and identification
- Live recording quality monitor (loudness, clip safety, voice activity)
- Role-based authorization for enrollment (admin-only)

## Tech Stack

- Backend: Python, FastAPI, PyTorch, Librosa, Resemblyzer
- Frontend: HTML, CSS, JavaScript  
- Database: Firebase Auth + Realtime Database

## Quick Start

1. Create virtual environment and activate it
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` file with Firebase config (see FIREBASE_SETUP.md)
4. Run: `uvicorn api:app --reload`
5. Visit: `http://localhost:8000`

## Documentation

- [API Reference](API_DOCUMENTATION.md)
- [Firebase Setup](FIREBASE_SETUP.md)
- [Improvements](IMPROVEMENTS.md)
- [Setup Guide](SETUP.md)
- [Project Architecture](PROJECT_STRUCTURE.md)
