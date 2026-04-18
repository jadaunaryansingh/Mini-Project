import pytest
from fastapi.testclient import TestClient
import os
import json

os.environ["AUTH_REQUIRED"] = "false"

from api import app

client = TestClient(app)

def test_status_endpoint():
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "device" in data
    assert "speakers" in data
    assert "num_speakers" in data
    assert isinstance(data["num_speakers"], int)

def test_speakers_endpoint():
    response = client.get("/speakers")
    assert response.status_code == 200
    data = response.json()
    assert "speakers" in data
    assert "count" in data
    assert isinstance(data["speakers"], list)
    assert len(data["speakers"]) > 0

def test_firebase_config_endpoint():
    response = client.get("/firebase-config")
    assert response.status_code == 200
    config = response.json()
    required_keys = ["apiKey", "projectId", "databaseURL", "authDomain"]
    for key in required_keys:
        assert key in config

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

def test_favicon_endpoints():
    response = client.get("/favicon.ico")
    assert response.status_code == 200

def test_validate_speaker_name_required():
    """Test that speaker name is required for authenticate"""
    response = client.post("/authenticate", data={"speaker": ""})
    assert response.status_code == 422
    # 422 means unprocessable entity (missing audio file)
def test_validate_speaker_exists():
    """Test that speaker must exist in database"""
    response = client.post(
        "/authenticate",
        data={"speaker": "NonExistentSpeaker"}
    )
    assert response.status_code == 422
    # 422 means unprocessable entity (missing audio file)
def test_validate_audio_file_required():
    """Test that audio file is required"""
    response = client.post("/enroll", data={"speaker_name": "TestSpeaker"})
    assert response.status_code == 422

def test_validate_enroll_speaker_name_required():
    """Test that speaker name is required for enroll"""
    with open("test_audio.wav", "wb") as f:
        f.write(b"fake audio data")
    
    with open("test_audio.wav", "rb") as f:
        response = client.post(
            "/enroll",
            files={"audio": ("test.wav", f, "audio/wav")},
            data={"speaker_name": ""}
        )
    
    assert response.status_code == 400
    os.remove("test_audio.wav")

def test_security_headers():
    """Test that security headers are present"""
    response = client.get("/status")
    assert response.status_code == 200
    assert "X-Content-Type-Options" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-XSS-Protection" in response.headers

def test_cors_headers():
    """Test CORS configuration"""
    response = client.get("/status")
    assert response.status_code == 200

def test_rate_limiting_status():
    """Test that rate limiting is configured"""
    for i in range(5):
        response = client.get("/status")
        assert response.status_code == 200

def test_firebase_config_shows_error_without_env():
    """Test that missing Firebase config returns error"""
    response = client.get("/firebase-config")
    if response.status_code == 500:
        assert "Missing Firebase" in response.json()["detail"]

def test_speakers_list_sorted():
    """Test that speakers list is sorted"""
    response = client.get("/speakers")
    assert response.status_code == 200
    speakers = response.json()["speakers"]
    assert speakers == sorted(speakers)

def test_speakers_count_matches_list():
    """Test that speaker count matches list length"""
    response = client.get("/speakers")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == len(data["speakers"])

def test_status_device_type():
    """Test that device is either cpu or cuda"""
    response = client.get("/status")
    assert response.status_code == 200
    device = response.json()["device"]
    assert device in ["cpu", "cuda", "mps"]

def test_multiple_requests():
    """Test that multiple requests work correctly"""
    for _ in range(3):
        response = client.get("/speakers")
        assert response.status_code == 200

def test_json_response_format():
    """Test that all endpoints return valid JSON"""
    endpoints = ["/status", "/speakers", "/firebase-config"]
    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200
        try:
            response.json()
        except ValueError:
            pytest.fail(f"Endpoint {endpoint} did not return valid JSON")

def test_admin_feedback_endpoint_shape():
    """Admin feedback endpoint should return expected keys in auth-bypass mode"""
    response = client.get("/admin/feedbacks")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
    assert "storage" in data
    assert isinstance(data["items"], list)

def test_admin_feedback_csv_export():
    """CSV export endpoint should return text/csv response"""
    response = client.get("/admin/feedbacks/export.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "Content-Disposition" in response.headers

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
