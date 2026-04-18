# API Reference

Base URL: `http://localhost:8081`

Interactive docs:
- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

## Authentication and Authorization

Protected endpoints require Firebase ID token in header:

`Authorization: Bearer <firebase_id_token>`

Behavior:
- `AUTH_REQUIRED=true` (default): token required on protected endpoints.
- `AUTH_REQUIRED=false`: development mode, backend bypasses auth checks.

Authorization:
- `/authenticate` and `/verify`: any authenticated user.
- `/enroll`: admin only (`role=admin/owner` custom claim OR allowlist via `ADMIN_EMAILS`/`ADMIN_UIDS`).

## Endpoints

### GET /status
Returns API health and loaded speakers.

```json
{
  "status": "online",
  "device": "cpu",
  "speakers": ["Aamir_Khan", "Ajay_Devgn"],
  "num_speakers": 23
}
```

### GET /firebase-config
Returns frontend Firebase web config.

### GET /speakers
List enrolled speakers.

### GET /admin
Serves the admin dashboard UI.

### GET /admin/feedbacks
Admin-only feedback audit stream used by admin dashboard.

Query params:
- `limit` (default 200, max 1000)
- `endpoint` (`all` | `authenticate` | `verify`)
- `outcome` (`all` | `success` | `failure`)
- `user_email` (contains filter)

Response:

```json
{
  "items": [
    {
      "timestamp": "2026-04-18T10:35:12.100000+00:00",
      "endpoint": "verify",
      "outcome": "failure",
      "user": {"email": "admin@example.com", "role": "admin"},
      "feedback": {"summary": "Denied because ..."}
    }
  ],
  "count": 1,
  "total_available": 120,
  "storage": "firebase"
}
```

Persistence behavior:
- If Firebase Realtime Database is configured (`FIREBASE_DATABASE_URL` + Firebase Admin credentials), events are persisted under `admin_feedback_audit/events` and survive server restarts.
- If not configured, backend falls back to in-memory event buffer.

### GET /admin/feedbacks/export.csv
Admin-only CSV export of filtered feedback audit records.

Accepts the same query parameters as `/admin/feedbacks`:
- `limit`
- `endpoint`
- `outcome`
- `user_email`

Returns downloadable CSV with fields including timestamp, endpoint, outcome, users, similarity metrics, reasons, and next steps.

### POST /authenticate
Verify a claimed speaker against uploaded voice sample.

Form fields:
- `audio`: audio file
- `speaker`: claimed speaker name
- `threshold` (optional, default `0.70`)

Response includes detailed decision feedback:

```json
{
  "success": true,
  "authenticated": false,
  "similarity": 0.6123,
  "claimed_speaker": "Aamir_Khan",
  "effective_threshold": 0.7,
  "margin_vs_next": 0.021,
  "confidence": 42.1,
  "feedback": {
    "summary": "Denied because the voiceprint did not pass the confidence threshold.",
    "reasons": [
      "Similarity 0.6123 is below threshold 0.7000",
      "Closest known speaker is Ajay_Devgn"
    ],
    "next_steps": [
      "Retry in a quieter environment",
      "Record 3-5 seconds with consistent speaking volume"
    ],
    "decision_factors": {
      "threshold_gap": -0.0877,
      "margin_vs_next": 0.021,
      "closest_speaker": "Ajay_Devgn"
    }
  }
}
```

### POST /verify
Identify speaker from uploaded voice sample (open-set identification).

Form fields:
- `audio`: audio file
- `threshold` (optional, default `0.60`)

Response includes `top_matches` and `feedback`.

### POST /enroll
Add a new speaker embedding to database.

Form fields:
- `audio`: audio file
- `speaker_name`: new unique speaker identifier

Requires admin privileges.

## Common Error Codes

| Code | Meaning |
|------|---------|
| 400 | Validation/business rule error |
| 401 | Missing/invalid Firebase token |
| 403 | Authenticated but not authorized (admin required) |
| 422 | Missing required form field |
| 500 | Internal processing error |
| 503 | Firebase Admin not configured on backend |

## Environment Variables

Core:
- `FIREBASE_API_KEY`
- `FIREBASE_AUTH_DOMAIN`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`
- `FIREBASE_MESSAGING_SENDER_ID`
- `FIREBASE_APP_ID`
- `FIREBASE_MEASUREMENT_ID`
- `FIREBASE_DATABASE_URL`

Backend auth:
- `AUTH_REQUIRED` (`true`/`false`)
- `FIREBASE_SERVICE_ACCOUNT_PATH` (path to Firebase Admin JSON)
- `FIREBASE_SERVICE_ACCOUNT_JSON` (raw JSON string alternative)
- `ADMIN_EMAILS` (comma-separated)
- `ADMIN_UIDS` (comma-separated)
