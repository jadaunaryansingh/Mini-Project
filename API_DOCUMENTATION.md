# API Reference

Base URL: `http://localhost:8011`

## Endpoints

### GET /status
Returns API health and loaded speakers.

```
{
  "status": "online",
  "device": "cpu",
  "speakers": ["Aamir_Khan", "Ajay_Devgn", ...],
  "num_speakers": 23
}
```

### GET /firebase-config
Returns Firebase config for frontend.

```json
{
  "apiKey": "...",
  "projectId": "...",
  "databaseURL": "..."
}
```

### GET /speakers
List all enrolled speakers.

```json
{
  "speakers": ["Aamir_Khan", "Ajay_Devgn", ...],
  "count": 23
}
```

### POST /authenticate
Verify speaker voice.

**Parameters:**
- `audio` (file) - Audio file
- `speaker` (string) - Speaker name to verify
- `threshold` (float, default 0.70) - Confidence threshold

**Response:**
```json
{
  "success": true,
  "authenticated": true,
  "similarity": 0.8234,
  "claimed_speaker": "Aamir_Khan",
  "decision": "AUTHENTICATED ✅",
  "confidence": 87.45
}
```

Error:
```json
{
  "detail": "Speaker 'Unknown' not in database"
}
```

### POST /verify
Identify speaker from voice (no name needed).

**Parameters:**
- `audio` (file) - Audio file
- `threshold` (float, default 0.60) - Confidence threshold

**Response:**
```json
{
  "success": true,
  "identified": true,
  "speaker": "Aamir_Khan",
  "similarity": 0.8234,
  "top_matches": [
    {"speaker": "Aamir_Khan", "similarity": 0.8234, "confidence": 82.34},
    {"speaker": "Ajay_Devgn", "similarity": 0.7413, "confidence": 74.13}
  ],
  "message": "Identified as Aamir_Khan",
  "confidence": 82.34
}
```

### POST /enroll
Add new speaker to database.

**Parameters:**
- `audio` (file) - Audio file
- `speaker_name` (string) - New speaker name (unique)

**Response:**
```json
{
  "success": true,
  "message": "Speaker 'NewActor' enrolled successfully",
  "speaker": "NewActor",
  "total_speakers": 24
}
```

Error:
```json
{
  "detail": "Speaker 'Aamir_Khan' already exists in database"
}
```

## Error Codes

| Code | Message | Fix |
|------|---------|-----|
| 400 | Speaker not in database | Check spelling, enroll first |
| 400 | File must be audio | Use .wav, .mp3, .m4a |
| 400 | Speaker name required | Provide speaker_name |
| 400 | Speaker already exists | Use different name |
| 500 | Processing error | Check server logs |

## Examples

### cURL
```bash
curl http://localhost:8011/status

curl -X POST http://localhost:8011/authenticate \
  -F "audio=@recording.wav" \
  -F "speaker=Aamir_Khan" \
  -F "threshold=0.70"
```

### Python
```python
import requests

with open('recording.wav', 'rb') as f:
    r = requests.post(
        'http://localhost:8011/authenticate',
        files={'audio': f},
        data={'speaker': 'Aamir_Khan', 'threshold': 0.70}
    )
    print(r.json())
```

## Environment Variables

```
FIREBASE_API_KEY
FIREBASE_AUTH_DOMAIN
FIREBASE_PROJECT_ID
FIREBASE_STORAGE_BUCKET
FIREBASE_MESSAGING_SENDER_ID
FIREBASE_APP_ID
FIREBASE_MEASUREMENT_ID
FIREBASE_DATABASE_URL
```

## Run

```bash
cd Mini-Project
.\.venv\Scripts\Activate.ps1
uvicorn api:app --host 127.0.0.1 --port 8011 --reload
```
