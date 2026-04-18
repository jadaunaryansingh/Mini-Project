from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import torch
import pickle
import numpy as np
import librosa
import os
import tempfile
import logging
import json
import io
import csv
from datetime import datetime, timezone
from pathlib import Path
from resemblyzer import VoiceEncoder, preprocess_wav
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

try:
    import firebase_admin
    from firebase_admin import auth as firebase_auth, credentials, db as firebase_db
except ImportError:
    firebase_admin = None
    firebase_auth = None
    credentials = None
    firebase_db = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
bearer_scheme = HTTPBearer(auto_error=False)

load_dotenv()

FIREBASE_CONFIG = {
    "apiKey":            os.getenv("FIREBASE_API_KEY"),
    "authDomain":        os.getenv("FIREBASE_AUTH_DOMAIN"),
    "projectId":         os.getenv("FIREBASE_PROJECT_ID"),
    "storageBucket":     os.getenv("FIREBASE_STORAGE_BUCKET"),
    "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
    "appId":             os.getenv("FIREBASE_APP_ID"),
    "measurementId":     os.getenv("FIREBASE_MEASUREMENT_ID"),
    "databaseURL":       os.getenv("FIREBASE_DATABASE_URL"),
}

AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
AUTH_FALLBACK_LOCAL = os.getenv("AUTH_FALLBACK_LOCAL", "true").lower() == "true"
BOOTSTRAP_ADMIN_EMAILS = {"admin@voicebaseddl.com"}
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()} | BOOTSTRAP_ADMIN_EMAILS
ADMIN_UIDS = {u.strip() for u in os.getenv("ADMIN_UIDS", "").split(",") if u.strip()}
FEEDBACK_AUDIT_MAX = int(os.getenv("FEEDBACK_AUDIT_MAX", "2000"))

feedback_audit_log = []

N_MELS = 128
FIXED_LENGTH = 128
N_FFT = 512
HOP_LENGTH = 256

def _load_and_clean_audio(file_path, sample_rate=16000):
    audio, sr = librosa.load(file_path, sr=sample_rate, mono=True)
    if audio is None or len(audio) == 0:
        raise ValueError(f"Empty audio: {file_path}")

    audio_trimmed, _ = librosa.effects.trim(audio, top_db=25)
    if len(audio_trimmed) > 0:
        audio = audio_trimmed

    peak = np.max(np.abs(audio))
    if peak > 1e-8:
        audio = audio / peak

    return audio.astype(np.float32), sr

def _compute_log_mel(audio, sr, n_mels=N_MELS):
    mel_spec = librosa.feature.melspectrogram(
        y=audio,
        sr=sr,
        n_mels=n_mels,
        n_fft=N_FFT,
        hop_length=HOP_LENGTH
    )
    return librosa.power_to_db(mel_spec, ref=np.max).astype(np.float32)

def _fixed_crop(log_mel_spec, start_idx, fixed_length=FIXED_LENGTH):
    crop = log_mel_spec[:, start_idx:start_idx + fixed_length]
    if crop.shape[1] < fixed_length:
        pad_width = fixed_length - crop.shape[1]
        crop = np.pad(crop, ((0, 0), (0, pad_width)), mode='constant')
    return crop.astype(np.float32)

def audio_to_melspectrogram(file_path, sample_rate=16000, n_mels=N_MELS, fixed_length=FIXED_LENGTH):
    audio, sr = _load_and_clean_audio(file_path, sample_rate=sample_rate)
    log_mel_spec = _compute_log_mel(audio, sr, n_mels=n_mels)
    if log_mel_spec.shape[1] < fixed_length:
        pad_width = fixed_length - log_mel_spec.shape[1]
        log_mel_spec = np.pad(log_mel_spec, ((0, 0), (0, pad_width)), mode='constant')
        return log_mel_spec.astype(np.float32)
    return log_mel_spec[:, :fixed_length].astype(np.float32)

def audio_to_melspectrogram_crops(file_path, sample_rate=16000, n_mels=N_MELS, fixed_length=FIXED_LENGTH, num_crops=3):
    audio, sr = _load_and_clean_audio(file_path, sample_rate=sample_rate)
    log_mel_spec = _compute_log_mel(audio, sr, n_mels=n_mels)
    total_frames = log_mel_spec.shape[1]
    if total_frames <= fixed_length or num_crops <= 1:
        return [_fixed_crop(log_mel_spec, 0, fixed_length=fixed_length)]
    max_start = total_frames - fixed_length
    start_positions = np.linspace(0, max_start, num=num_crops, dtype=int)
    return [_fixed_crop(log_mel_spec, int(start), fixed_length=fixed_length) for start in start_positions]

def get_embedding(file_path, encoder):
    wav = preprocess_wav(Path(file_path))
    emb = encoder.embed_utterance(wav)
    norm = np.linalg.norm(emb)
    if norm > 1e-8:
        emb = emb / norm
    return emb.astype(np.float32)

def identify_speaker(audio_path, voice_db, encoder, threshold=0.80):
    input_embedding = get_embedding(audio_path, encoder)
    best_speaker = None
    best_similarity = -1
    for speaker_name, db_embedding in voice_db.items():
        similarity = float(np.dot(input_embedding, db_embedding))
        if similarity > best_similarity:
            best_similarity = similarity
            best_speaker = speaker_name
    if best_similarity >= threshold:
        status = "Authenticated"
    else:
        status = "Voice Not Found"
        best_speaker = "Unknown"
    return {
        "predicted_name": best_speaker,
        "similarity_score": round(float(best_similarity), 4),
        "status": status
    }

def _initialize_firebase_admin() -> bool:
    if firebase_admin is None:
        logger.warning("firebase-admin package not installed; protected endpoints will reject requests")
        return False

    if firebase_admin._apps:
        return True

    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    db_url = os.getenv("FIREBASE_DATABASE_URL")
    init_options = {"projectId": project_id} if project_id else {}
    if db_url:
        init_options["databaseURL"] = db_url

    try:
        if service_account_json:
            cred_info = json.loads(service_account_json)
            cred = credentials.Certificate(cred_info)
            firebase_admin.initialize_app(cred, options=init_options)
            logger.info("Firebase Admin initialized via FIREBASE_SERVICE_ACCOUNT_JSON")
            return True

        if service_account_path:
            if not Path(service_account_path).exists():
                logger.warning("FIREBASE_SERVICE_ACCOUNT_PATH does not exist: %s", service_account_path)
                return False
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred, options=init_options)
            logger.info("Firebase Admin initialized via FIREBASE_SERVICE_ACCOUNT_PATH")
            return True

        if init_options:
            firebase_admin.initialize_app(options=init_options)
            logger.info("Firebase Admin initialized with project/database options")
            return True

        logger.warning("Firebase Admin not configured. Set FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_SERVICE_ACCOUNT_PATH")
        return False
    except Exception as exc:
        logger.error("Failed to initialize Firebase Admin: %s", exc)
        return False

def _build_auth_feedback(similarity: float, effective_threshold: float, margin: float, nearest_name: str, is_match: bool) -> Dict[str, Any]:
    gap = round(float(similarity - effective_threshold), 4)
    reasons = []
    next_steps = []

    if is_match:
        reasons.append(f"Similarity {similarity:.4f} is above threshold {effective_threshold:.4f}")
        if margin >= 0.08:
            reasons.append(f"Strong separation from next match (margin {margin:.4f})")
        else:
            reasons.append(f"Accepted with narrow separation (margin {margin:.4f})")
        next_steps.append("Allow access for this session")
        next_steps.append("Optionally capture another sample for audit logs")
        summary = "Authenticated because the voiceprint is above the adaptive threshold."
    else:
        reasons.append(f"Similarity {similarity:.4f} is below threshold {effective_threshold:.4f}")
        reasons.append(f"Closest known speaker is {nearest_name}")
        if margin < 0.03:
            reasons.append("Voice pattern is ambiguous compared to multiple enrolled speakers")
        next_steps.append("Retry in a quieter environment")
        next_steps.append("Record 3-5 seconds with consistent speaking volume")
        next_steps.append("Enroll this speaker if they are new")
        summary = "Denied because the voiceprint did not pass the confidence threshold."

    return {
        "summary": summary,
        "reasons": reasons,
        "next_steps": next_steps,
        "decision_factors": {
            "similarity": round(float(similarity), 4),
            "effective_threshold": round(float(effective_threshold), 4),
            "threshold_gap": gap,
            "margin_vs_next": round(float(margin), 4),
            "closest_speaker": nearest_name,
        },
    }

def _append_feedback_event(event: Dict[str, Any]) -> None:
    feedback_audit_log.append(event)
    if len(feedback_audit_log) > FEEDBACK_AUDIT_MAX:
        del feedback_audit_log[:-FEEDBACK_AUDIT_MAX]

def _persist_feedback_event_firebase(event: Dict[str, Any]) -> bool:
    if not voice_db_state.get("firebase_db_ready") or firebase_db is None:
        return False

    try:
        ref = firebase_db.reference("admin_feedback_audit/events")
        new_ref = ref.push()
        payload = dict(event)
        payload["event_id"] = new_ref.key
        new_ref.set(payload)
        return True
    except Exception as exc:
        logger.warning("Failed to persist feedback event to Firebase DB: %s", exc)
        return False

def _read_feedback_events(source_limit: int) -> Dict[str, Any]:
    bounded = max(1, min(int(source_limit), 5000))

    if voice_db_state.get("firebase_db_ready") and firebase_db is not None:
        try:
            ref = firebase_db.reference("admin_feedback_audit/events")
            rows = ref.order_by_child("unix_ms").limit_to_last(bounded).get()
            events = []
            if isinstance(rows, dict):
                for key, value in rows.items():
                    if isinstance(value, dict):
                        item = dict(value)
                        item.setdefault("event_id", key)
                        events.append(item)
            events.sort(key=lambda item: item.get("unix_ms", 0), reverse=True)
            return {"items": events, "storage": "firebase"}
        except Exception as exc:
            logger.warning("Failed to read feedback events from Firebase DB: %s", exc)

    events = list(reversed(feedback_audit_log[-bounded:]))
    return {"items": events, "storage": "memory"}

def _filter_feedback_items(items, endpoint_filter: str, outcome_filter: str, email_filter: str, bounded_limit: int):
    rows = []
    for item in items:
        if endpoint_filter != "all" and item.get("endpoint") != endpoint_filter:
            continue
        if outcome_filter != "all" and item.get("outcome") != outcome_filter:
            continue
        if email_filter:
            item_email = ((item.get("user") or {}).get("email") or "").lower()
            if email_filter not in item_email:
                continue
        rows.append(item)
        if len(rows) >= bounded_limit:
            break
    return rows

async def require_authenticated_user(
    request: Request,
    credentials_data: HTTPAuthorizationCredentials = Depends(bearer_scheme)
) -> Dict[str, Any]:
    if not AUTH_REQUIRED:
        return {"uid": "dev-user", "email": "dev@local", "role": "admin"}

    if not voice_db_state.get("firebase_admin_ready"):
        is_local_request = str(request.client.host if request.client else "").strip() in {"127.0.0.1", "::1", "localhost"}
        if AUTH_FALLBACK_LOCAL and is_local_request:
            logger.warning("Firebase Admin unavailable; using local development auth fallback")
            return {
                "uid": "local-fallback-admin",
                "email": "admin@voicebaseddl.com",
                "role": "admin",
                "claims": {"fallback": True}
            }
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable. Configure Firebase Admin credentials on backend or set AUTH_REQUIRED=false for local development."
        )

    if not credentials_data or credentials_data.scheme.lower() != "bearer" or not credentials_data.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    try:
        decoded_token = firebase_auth.verify_id_token(credentials_data.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid authentication token: {exc}")

    user_context = {
        "uid": decoded_token.get("uid"),
        "email": (decoded_token.get("email") or "").lower(),
        "role": decoded_token.get("role", "user"),
        "claims": decoded_token,
    }
    request.state.user_context = user_context
    return user_context

async def require_admin(user_context: Dict[str, Any] = Depends(require_authenticated_user)) -> Dict[str, Any]:
    role = str(user_context.get("role", "user")).lower()
    email = str(user_context.get("email", "")).lower()
    uid = str(user_context.get("uid", ""))

    if role in {"admin", "owner"}:
        return user_context
    if email and email in ADMIN_EMAILS:
        return user_context
    if uid and uid in ADMIN_UIDS:
        return user_context

    raise HTTPException(status_code=403, detail="Admin authorization required for enrollment")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
resemblyzer_encoder = None

voice_db_state = {"voice_db": None, "NUM_CLASSES": None, "resemblyzer_encoder": None, "firebase_admin_ready": False, "firebase_db_ready": False}

try:
    with open("voice_db.pkl", "rb") as f:
        raw_voice_db = pickle.load(f)
    voice_db_state["voice_db"] = {str(name): np.asarray(emb, dtype=np.float32) for name, emb in raw_voice_db.items()}
    voice_db_state["NUM_CLASSES"] = len(voice_db_state["voice_db"])
    print(f"[OK] Voice database loaded at startup: {voice_db_state['NUM_CLASSES']} speakers")
    print(f"  Speakers: {sorted(list(voice_db_state['voice_db'].keys()))}")
except Exception as e:
    print(f"[ERROR] Failed to load voice database: {e}")
    voice_db_state = {"voice_db": None, "NUM_CLASSES": None, "resemblyzer_encoder": None, "firebase_admin_ready": False, "firebase_db_ready": False}

@asynccontextmanager
async def lifespan(app):
    try:
        voice_db_state["resemblyzer_encoder"] = VoiceEncoder(device=str(device))
        print(f"[OK] Resemblyzer encoder loaded on {device}")
    except Exception as e:
        print(f"[ERROR] Failed to load resemblyzer encoder: {e}")

    app.state.voice_db = voice_db_state["voice_db"]
    app.state.NUM_CLASSES = voice_db_state["NUM_CLASSES"]
    app.state.resemblyzer_encoder = voice_db_state["resemblyzer_encoder"]
    voice_db_state["firebase_admin_ready"] = _initialize_firebase_admin()
    voice_db_state["firebase_db_ready"] = bool(voice_db_state["firebase_admin_ready"] and FIREBASE_CONFIG.get("databaseURL") and firebase_db is not None)
    app.state.firebase_admin_ready = voice_db_state["firebase_admin_ready"]
    app.state.firebase_db_ready = voice_db_state["firebase_db_ready"]
    
    yield
app = FastAPI(title="VoxGuard API", lifespan=lifespan)

app.mount("/firebase", StaticFiles(directory="firebase"), name="firebase")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.state.limiter = limiter

@app.get("/")
async def root():
    return FileResponse("index.html", media_type="text/html")

@app.get("/admin")
async def admin_page():
    return FileResponse("admin.html", media_type="text/html")

@app.get("/firebase-config")
async def get_firebase_config():
    missing = [k for k, v in FIREBASE_CONFIG.items() if not v]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Firebase env vars: {missing}"
        )
    return JSONResponse(content=FIREBASE_CONFIG)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse("favicon.svg", media_type="image/svg+xml")

@app.get("/favicon.svg", include_in_schema=False)
async def favicon_svg():
    return FileResponse("favicon.svg", media_type="image/svg+xml")

@app.get("/status")
@limiter.limit("100/minute")
async def status(request: Request):
    logger.info("Status check")
    voice_db = voice_db_state["voice_db"]
    num_classes = voice_db_state["NUM_CLASSES"]
    return {
        "status": "online",
        "device": str(device),
        "speakers": list(voice_db.keys()) if voice_db else [],
        "num_speakers": num_classes
    }

@app.get("/speakers")
@limiter.limit("50/minute")
async def get_speakers(request: Request):
    voice_db = voice_db_state["voice_db"]
    if not voice_db:
        raise HTTPException(status_code=500, detail="Database not loaded")
    return {
        "speakers": sorted(list(voice_db.keys())),
        "count": len(voice_db)
    }

@app.get("/admin/feedbacks")
@limiter.limit("60/minute")
async def get_feedback_audit(
    request: Request,
    limit: int = 200,
    endpoint: str = "all",
    outcome: str = "all",
    user_email: str = "",
    user_context: Dict[str, Any] = Depends(require_admin)
):
    bounded_limit = max(1, min(int(limit), 1000))
    endpoint_filter = (endpoint or "all").strip().lower()
    outcome_filter = (outcome or "all").strip().lower()
    email_filter = (user_email or "").strip().lower()
    source = _read_feedback_events(max(FEEDBACK_AUDIT_MAX, bounded_limit * 4))
    rows = _filter_feedback_items(source["items"], endpoint_filter, outcome_filter, email_filter, bounded_limit)

    return {
        "items": rows,
        "count": len(rows),
        "requested_limit": bounded_limit,
        "total_available": len(source["items"]),
        "storage": source["storage"],
        "filters": {
            "endpoint": endpoint_filter,
            "outcome": outcome_filter,
            "user_email": email_filter,
        },
        "requested_by": {
            "uid": user_context.get("uid"),
            "email": user_context.get("email"),
            "role": user_context.get("role", "user")
        }
    }

@app.get("/admin/feedbacks/export.csv")
@limiter.limit("30/minute")
async def export_feedback_audit_csv(
    request: Request,
    limit: int = 500,
    endpoint: str = "all",
    outcome: str = "all",
    user_email: str = "",
    user_context: Dict[str, Any] = Depends(require_admin)
):
    bounded_limit = max(1, min(int(limit), 2000))
    endpoint_filter = (endpoint or "all").strip().lower()
    outcome_filter = (outcome or "all").strip().lower()
    email_filter = (user_email or "").strip().lower()

    source = _read_feedback_events(max(FEEDBACK_AUDIT_MAX, bounded_limit * 4))
    rows = _filter_feedback_items(source["items"], endpoint_filter, outcome_filter, email_filter, bounded_limit)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "event_id", "timestamp", "endpoint", "outcome", "user_email", "user_role",
        "claimed_speaker", "identified_speaker", "closest_speaker",
        "similarity", "effective_threshold", "margin_vs_next", "summary",
        "reason_1", "reason_2", "reason_3", "next_step_1", "next_step_2", "next_step_3"
    ])

    for item in rows:
        feedback = item.get("feedback") or {}
        reasons = list(feedback.get("reasons") or [])
        steps = list(feedback.get("next_steps") or [])
        user = item.get("user") or {}

        writer.writerow([
            item.get("event_id", ""),
            item.get("timestamp", ""),
            item.get("endpoint", ""),
            item.get("outcome", ""),
            user.get("email", ""),
            user.get("role", ""),
            item.get("claimed_speaker", ""),
            item.get("identified_speaker", ""),
            item.get("closest_speaker", ""),
            item.get("similarity", ""),
            item.get("effective_threshold", ""),
            item.get("margin_vs_next", ""),
            feedback.get("summary", ""),
            reasons[0] if len(reasons) > 0 else "",
            reasons[1] if len(reasons) > 1 else "",
            reasons[2] if len(reasons) > 2 else "",
            steps[0] if len(steps) > 0 else "",
            steps[1] if len(steps) > 1 else "",
            steps[2] if len(steps) > 2 else "",
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    output.close()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"voxguard_feedback_audit_{timestamp}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Feedback-Storage": source["storage"],
        },
    )

@app.post("/authenticate")
@limiter.limit("20/minute")
async def authenticate_speaker(
    request: Request,
    audio: UploadFile = File(...),
    speaker: str = None,
    threshold: float = 0.70,
    user_context: Dict[str, Any] = Depends(require_authenticated_user)
):
    voice_db = voice_db_state["voice_db"]
    encoder = voice_db_state["resemblyzer_encoder"]
    
    if not speaker or not speaker.strip():
        raise HTTPException(status_code=400, detail="Speaker name required")
    if len(speaker) > 100:
        raise HTTPException(status_code=400, detail="Speaker name too long")
    if not voice_db or speaker not in voice_db:
        logger.warning(f"Auth attempt for unknown speaker: {speaker}")
        raise HTTPException(status_code=400, detail=f"Speaker '{speaker}' not in database")
    if not audio.content_type or not audio.content_type.startswith('audio/'):
        logger.warning(f"Auth attempt with non-audio file: {audio.content_type}")
        raise HTTPException(status_code=400, detail="File must be an audio file")
    if not audio.filename:
        raise HTTPException(status_code=400, detail="File must have a name")
    if not encoder:
        raise HTTPException(status_code=500, detail="Voice encoder not initialized")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
        content = await audio.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    try:
        logger.info(f"Processing auth for speaker: {speaker}")
        input_embedding = get_embedding(tmp_path, encoder)
        claimed_db_embedding = voice_db[speaker]
        similarity = float(np.dot(input_embedding, claimed_db_embedding))
        ranked_scores = []
        for speaker_name, db_embedding in voice_db.items():
            ranked_scores.append((speaker_name, float(np.dot(input_embedding, db_embedding))))
        ranked_scores.sort(key=lambda item: item[1], reverse=True)
        top1 = ranked_scores[0][1] if len(ranked_scores) > 0 else similarity
        top2 = ranked_scores[1][1] if len(ranked_scores) > 1 else -1.0
        margin = top1 - top2
        effective_threshold = threshold - 0.05 if margin >= 0.08 else threshold
        effective_threshold = max(0.55, effective_threshold)
        authenticated = similarity >= effective_threshold
        nearest_name = ranked_scores[0][0] if ranked_scores else speaker
        feedback = _build_auth_feedback(similarity, effective_threshold, margin, nearest_name, authenticated)
        event = {
            "unix_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoint": "authenticate",
            "outcome": "success" if authenticated else "failure",
            "user": {
                "uid": user_context.get("uid"),
                "email": user_context.get("email"),
                "role": user_context.get("role", "user")
            },
            "claimed_speaker": speaker,
            "closest_speaker": nearest_name,
            "similarity": round(float(similarity), 4),
            "effective_threshold": round(float(effective_threshold), 4),
            "margin_vs_next": round(float(margin), 4),
            "feedback": feedback,
        }
        _append_feedback_event(event)
        _persist_feedback_event_firebase(event)
        logger.info(f"Auth result for {speaker}: authenticated={authenticated}, similarity={similarity:.4f}")
        return JSONResponse(content={
            "success": True,
            "authenticated": authenticated,
            "similarity": round(float(similarity), 4),
            "claimed_speaker": speaker,
            "user": {
                "uid": user_context.get("uid"),
                "email": user_context.get("email"),
                "role": user_context.get("role", "user")
            },
            "threshold": threshold,
            "effective_threshold": round(float(effective_threshold), 4),
            "margin_vs_next": round(float(margin), 4),
            "decision": "AUTHENTICATED ✅" if authenticated else "ACCESS DENIED ❌",
            "confidence": round(max(0, min(100, (similarity - threshold + 0.3) / 0.3 * 100)), 2),
            "feedback": feedback
        })
    except Exception as e:
        logger.error(f"Auth processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        os.unlink(tmp_path)

@app.post("/verify")
@limiter.limit("20/minute")
async def verify_speaker(
    request: Request,
    audio: UploadFile = File(...),
    threshold: float = 0.60,
    user_context: Dict[str, Any] = Depends(require_authenticated_user)
):
    voice_db = voice_db_state["voice_db"]
    encoder = voice_db_state["resemblyzer_encoder"]
    
    if not audio.content_type or not audio.content_type.startswith('audio/'):
        logger.warning(f"Verify attempt with non-audio file: {audio.content_type}")
        raise HTTPException(status_code=400, detail="File must be an audio file")
    if not audio.filename:
        raise HTTPException(status_code=400, detail="File must have a name")
    if not voice_db:
        logger.error("Voice database is empty")
        raise HTTPException(status_code=500, detail="Speaker database is empty")
    if not encoder:
        raise HTTPException(status_code=500, detail="Voice encoder not initialized")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
        content = await audio.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    try:
        logger.info("Processing speaker verification")
        input_embedding = get_embedding(tmp_path, encoder)
        similarities = []
        for speaker_name, db_embedding in voice_db.items():
            similarity = float(np.dot(input_embedding, db_embedding))
            similarities.append({
                "speaker": speaker_name,
                "similarity": round(similarity, 4),
                "confidence": round(min(100, max(0, similarity * 100)), 2)
            })
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        top_matches = similarities[:3]
        best_match = similarities[0]
        top2_similarity = similarities[1]["similarity"] if len(similarities) > 1 else -1.0
        margin = best_match["similarity"] - top2_similarity
        effective_threshold = threshold - 0.05 if margin >= 0.08 else threshold
        effective_threshold = max(0.55, effective_threshold)
        if best_match["similarity"] >= effective_threshold:
            logger.info(f"Speaker identified: {best_match['speaker']}, sim={best_match['similarity']:.4f}")
            feedback = _build_auth_feedback(best_match["similarity"], effective_threshold, margin, best_match["speaker"], True)
            event = {
                "unix_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "endpoint": "verify",
                "outcome": "success",
                "user": {
                    "uid": user_context.get("uid"),
                    "email": user_context.get("email"),
                    "role": user_context.get("role", "user")
                },
                "identified_speaker": best_match["speaker"],
                "closest_speaker": best_match["speaker"],
                "similarity": round(float(best_match["similarity"]), 4),
                "effective_threshold": round(float(effective_threshold), 4),
                "margin_vs_next": round(float(margin), 4),
                "feedback": feedback,
            }
            _append_feedback_event(event)
            _persist_feedback_event_firebase(event)
            return JSONResponse(content={
                "success": True,
                "identified": True,
                "speaker": best_match["speaker"],
                "user": {
                    "uid": user_context.get("uid"),
                    "email": user_context.get("email"),
                    "role": user_context.get("role", "user")
                },
                "similarity": best_match["similarity"],
                "threshold": threshold,
                "effective_threshold": round(float(effective_threshold), 4),
                "margin_vs_next": round(float(margin), 4),
                "top_matches": top_matches,
                "message": f"Identified as {best_match['speaker']}",
                "confidence": best_match["confidence"],
                "feedback": feedback
            })
        else:
            feedback = _build_auth_feedback(best_match["similarity"], effective_threshold, margin, best_match["speaker"], False)
            event = {
                "unix_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "endpoint": "verify",
                "outcome": "failure",
                "user": {
                    "uid": user_context.get("uid"),
                    "email": user_context.get("email"),
                    "role": user_context.get("role", "user")
                },
                "identified_speaker": None,
                "closest_speaker": best_match["speaker"],
                "similarity": round(float(best_match["similarity"]), 4),
                "effective_threshold": round(float(effective_threshold), 4),
                "margin_vs_next": round(float(margin), 4),
                "feedback": feedback,
            }
            _append_feedback_event(event)
            _persist_feedback_event_firebase(event)
            return JSONResponse(content={
                "success": True,
                "identified": False,
                "speaker": None,
                "user": {
                    "uid": user_context.get("uid"),
                    "email": user_context.get("email"),
                    "role": user_context.get("role", "user")
                },
                "similarity": best_match["similarity"],
                "threshold": threshold,
                "effective_threshold": round(float(effective_threshold), 4),
                "margin_vs_next": round(float(margin), 4),
                "top_matches": top_matches,
                "closest_speaker": best_match["speaker"],
                "message": "No matching speaker found in database. Please add this voice to the system.",
                "confidence": 0,
                "feedback": feedback
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        os.unlink(tmp_path)

@app.post("/enroll")
@limiter.limit("5/minute")
async def enroll_speaker(
    request: Request,
    audio: UploadFile = File(...),
    speaker_name: str = None,
    user_context: Dict[str, Any] = Depends(require_admin)
):
    voice_db = voice_db_state["voice_db"]
    encoder = voice_db_state["resemblyzer_encoder"]
    
    if not speaker_name or not speaker_name.strip():
        raise HTTPException(status_code=400, detail="Speaker name is required")
    if len(speaker_name) > 100:
        raise HTTPException(status_code=400, detail="Speaker name too long")
    if voice_db and speaker_name in voice_db:
        logger.warning(f"Enroll attempt for existing speaker: {speaker_name}")
        raise HTTPException(status_code=400, detail=f"Speaker '{speaker_name}' already exists in database")
    if not audio.content_type or not audio.content_type.startswith('audio/'):
        logger.warning(f"Enroll attempt with non-audio file: {audio.content_type}")
        raise HTTPException(status_code=400, detail="File must be an audio file")
    if not audio.filename:
        raise HTTPException(status_code=400, detail="File must have a name")
    if not encoder:
        raise HTTPException(status_code=500, detail="Voice encoder not initialized")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
        content = await audio.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    try:
        logger.info(f"Enrolling new speaker: {speaker_name}")
        embedding = get_embedding(tmp_path, encoder)
        voice_db[speaker_name] = embedding
        with open("voice_db.pkl", "wb") as f:
            pickle.dump(voice_db, f)
        logger.info(f"Speaker {speaker_name} enrolled successfully. Total speakers: {len(voice_db)}")
        return JSONResponse(content={
            "success": True,
            "message": f"Speaker '{speaker_name}' enrolled successfully",
            "speaker": speaker_name,
            "total_speakers": len(voice_db)
        })
    except Exception as e:
        logger.error(f"Enrollment error for {speaker_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Enrollment error: {str(e)}")
    finally:
        os.unlink(tmp_path)

if __name__ == "__main__":
    import subprocess
    import sys
    from pathlib import Path
    import uvicorn

    print("\nVoxGuard - Speaker Verification System\n")

    required_files = ["voice_db.pkl"]
    missing_files = [f for f in required_files if not Path(f).exists()]
    if missing_files:
        print(f"Error: Missing files - {', '.join(missing_files)}")
        sys.exit(1)

    required_packages = ["fastapi", "uvicorn", "torch", "librosa", "numpy", "resemblyzer"]
    missing_packages = []
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing_packages.append(pkg)
    if missing_packages:
        print(f"Installing missing packages: {', '.join(missing_packages)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_packages)
        except subprocess.CalledProcessError:
            print("Failed to install dependencies")
            sys.exit(1)

    port = int(os.getenv("PORT", 8081))
    print(f"Starting server at http://localhost:{port}\n")
    try:
        uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False, log_level="info")
    except KeyboardInterrupt:
        print("\nServer stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
