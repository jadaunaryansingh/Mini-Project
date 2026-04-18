# VoxGuard — AI Speaker Verification

A web-based **Speaker Identification System** that verifies users by their voice using AI. Built with FastAPI, Firebase Auth, and a modern frontend.

## Features

- **Voice enrollment** — Register your voice with a short recording
- **Speaker verification** — Verify identity by speaking
- **Firebase authentication** — Secure user accounts
- **Realtime history storage** — Save per-user verification/enrollment activity
- **Mel-spectrogram + Resemblyzer** — Robust voice embeddings

## Tech Stack

- **Backend:** Python, FastAPI, PyTorch, Librosa, Resemblyzer
- **Frontend:** HTML, CSS, JavaScript
- **Auth & Data:** Firebase Authentication + Realtime Database

## Quick Start

1. Clone the repo and create a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Add a `.env` file with your Firebase config (including `FIREBASE_DATABASE_URL`).
4. Run the API: `uvicorn api:app --reload`
5. Open `index.html` in a browser (or serve via the API).

---

See [SETUP.md](SETUP.md) for detailed setup. Team details are in [TEAM.md](TEAM.md).
