from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import torch
import pickle
import numpy as np
import librosa
import os
import tempfile
from pathlib import Path
from resemblyzer import VoiceEncoder, preprocess_wav
from dotenv import load_dotenv

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

def get_embedding(file_path):
    wav = preprocess_wav(Path(file_path))
    emb = resemblyzer_encoder.embed_utterance(wav)
    norm = np.linalg.norm(emb)
    if norm > 1e-8:
        emb = emb / norm
    return emb.astype(np.float32)

def identify_speaker(audio_path, voice_db, threshold=0.80):
    input_embedding = get_embedding(audio_path)
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

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
voice_db = None
NUM_CLASSES = None
resemblyzer_encoder = None

@asynccontextmanager
async def lifespan(app):
    global voice_db, NUM_CLASSES, resemblyzer_encoder
    with open("voice_db.pkl", "rb") as f:
        raw_voice_db = pickle.load(f)
    voice_db = {str(name): np.asarray(emb, dtype=np.float32) for name, emb in raw_voice_db.items()}
    NUM_CLASSES = len(voice_db)
    print(f"[OK] Voice database loaded: {NUM_CLASSES} speakers")
    print(f"  Speakers: {sorted(list(voice_db.keys()))}")
    resemblyzer_encoder = VoiceEncoder(device=str(device))
    print(f"[OK] Resemblyzer encoder loaded on {device}")
    yield

app = FastAPI(title="VoxGuard API", lifespan=lifespan)

app.mount("/firebase", StaticFiles(directory="firebase"), name="firebase")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return FileResponse("index.html", media_type="text/html")

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
async def status():
    return {
        "status": "online",
        "device": str(device),
        "speakers": list(voice_db.keys()) if voice_db else [],
        "num_speakers": NUM_CLASSES
    }

@app.get("/speakers")
async def get_speakers():
    if not voice_db:
        raise HTTPException(status_code=500, detail="Database not loaded")
    return {
        "speakers": sorted(list(voice_db.keys())),
        "count": len(voice_db)
    }

@app.post("/authenticate")
async def authenticate_speaker(
    audio: UploadFile = File(...),
    speaker: str = None,
    threshold: float = 0.70
):
    if not speaker:
        raise HTTPException(status_code=400, detail="Speaker name required")
    if speaker not in voice_db:
        raise HTTPException(status_code=400, detail=f"Speaker '{speaker}' not in database")
    if not audio.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be an audio file")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
        content = await audio.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    try:
        input_embedding = get_embedding(tmp_path)
        claimed_db_embedding = voice_db[speaker]
        similarity = float(np.dot(input_embedding, claimed_db_embedding))
        all_scores = []
        for db_embedding in voice_db.values():
            all_scores.append(float(np.dot(input_embedding, db_embedding)))
        all_scores = sorted(all_scores, reverse=True)
        top1 = all_scores[0] if len(all_scores) > 0 else similarity
        top2 = all_scores[1] if len(all_scores) > 1 else -1.0
        margin = top1 - top2
        effective_threshold = threshold - 0.05 if margin >= 0.08 else threshold
        effective_threshold = max(0.55, effective_threshold)
        authenticated = similarity >= effective_threshold
        return JSONResponse(content={
            "success": True,
            "authenticated": authenticated,
            "similarity": round(float(similarity), 4),
            "claimed_speaker": speaker,
            "threshold": threshold,
            "effective_threshold": round(float(effective_threshold), 4),
            "margin_vs_next": round(float(margin), 4),
            "decision": "AUTHENTICATED ✅" if authenticated else "ACCESS DENIED ❌",
            "confidence": round(max(0, min(100, (similarity - threshold + 0.3) / 0.3 * 100)), 2)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        os.unlink(tmp_path)

@app.post("/verify")
async def verify_speaker(audio: UploadFile = File(...), threshold: float = 0.60):
    if not audio.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be an audio file")
    if not voice_db:
        raise HTTPException(status_code=500, detail="Speaker database is empty")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
        content = await audio.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    try:
        input_embedding = get_embedding(tmp_path)
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
            return JSONResponse(content={
                "success": True,
                "identified": True,
                "speaker": best_match["speaker"],
                "similarity": best_match["similarity"],
                "threshold": threshold,
                "effective_threshold": round(float(effective_threshold), 4),
                "margin_vs_next": round(float(margin), 4),
                "top_matches": top_matches,
                "message": f"Identified as {best_match['speaker']}",
                "confidence": best_match["confidence"]
            })
        else:
            return JSONResponse(content={
                "success": True,
                "identified": False,
                "speaker": None,
                "similarity": best_match["similarity"],
                "threshold": threshold,
                "effective_threshold": round(float(effective_threshold), 4),
                "margin_vs_next": round(float(margin), 4),
                "top_matches": top_matches,
                "closest_speaker": best_match["speaker"],
                "message": "No matching speaker found in database. Please add this voice to the system.",
                "confidence": 0
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")
    finally:
        os.unlink(tmp_path)

@app.post("/enroll")
async def enroll_speaker(audio: UploadFile = File(...), speaker_name: str = None):
    if not speaker_name or not speaker_name.strip():
        raise HTTPException(status_code=400, detail="Speaker name is required")
    if speaker_name in voice_db:
        raise HTTPException(status_code=400, detail=f"Speaker '{speaker_name}' already exists in database")
    if not audio.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be an audio file")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(audio.filename).suffix) as tmp_file:
        content = await audio.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    try:
        embedding = get_embedding(tmp_path)
        voice_db[speaker_name] = embedding
        with open("voice_db.pkl", "wb") as f:
            pickle.dump(voice_db, f)
        return JSONResponse(content={
            "success": True,
            "message": f"Speaker '{speaker_name}' enrolled successfully",
            "speaker": speaker_name,
            "total_speakers": len(voice_db)
        })
    except Exception as e:
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
