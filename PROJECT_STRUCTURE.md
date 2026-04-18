# Project Structure

```
Mini-Project-main/
├── api.py              # FastAPI backend, voice embedding & verification
├── index.html          # Frontend — VoxGuard UI
├── favicon.svg         # App icon
├── requirements.txt    # Python dependencies
├── activate.bat        # Venv activation (Windows)
├── .gitignore
├── .env                # (local only) Firebase & secrets
├── firebase/
│   ├── firebase-config.js
│   ├── firebase-auth.js
│   └── firebase-db.js
├── .vscode/
│   └── tasks.json
├── Speaker_Identification_System.ipynb  # Jupyter notebook
├── README.md
├── TEAM.md
├── SETUP.md
└── PROJECT_STRUCTURE.md (this file)
```

## Main components

- **api.py** — Voice encoding (Resemblyzer), mel-spectrogram, enrollment & verify endpoints
- **index.html** — Single-page app: login, enroll, verify, recording UI
- **firebase/** — Firebase config, auth, and Realtime Database history helpers
