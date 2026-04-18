# Firebase Setup

## Prerequisites
- Firebase project created
- Firebase console access
- Project credentials

## Step 1: Enable Authentication

1. Firebase Console > Authentication > Get Started
2. Enable Email/Password sign-in
3. Enable Google sign-in (optional)

## Step 2: Create Realtime Database

1. Firebase Console > Realtime Database > Create Database
2. Region: asia-southeast1 (or your region)
3. Start in test mode
4. Note the database URL in the Rules tab

## Step 3: Add Environment Variables

Create `.env` file in project root with your Firebase config:

```
FIREBASE_API_KEY=your_api_key
FIREBASE_AUTH_DOMAIN=yourproject.firebaseapp.com
FIREBASE_PROJECT_ID=yourproject
FIREBASE_STORAGE_BUCKET=yourproject.firebasestorage.app
FIREBASE_MESSAGING_SENDER_ID=123456789
FIREBASE_APP_ID=1:123456789:web:xyz
FIREBASE_MEASURE=G-ABC123
FIREBASE_DATABASE_URL=https://yourproject-default-rtdb.region.firebasedatabase.app
```

Add `.env` to `.gitignore`.

## Step 4: Set Database Security Rules

Go to Realtime Database > Rules tab and replace with:

```json
{
  "rules": {
    "users": {
      "$uid": {
        ".read": "auth != null && auth.uid === $uid",
        ".write": "auth != null && auth.uid === $uid",
        "profile": {
          ".validate": "newData.hasChildren(['uid', 'email'])"
        },
        "history": {
          "$historyId": {
            ".validate": "newData.hasChildren(['eventType', 'clientTimestamp'])"
          }
        }
      }
    },
    ".read": false,
    ".write": false
  }
}
```

4. Click Publish

These rules allow authenticated users to read/write only their own data path.

## Verify

Start app and sign in:

```bash
cd Mini-Project
.\.venv\Scripts\Activate.ps1
uvicorn api:app --host 127.0.0.1 --port 8011 --reload
```

Then visit `http://127.0.0.1:8011` and test signup/signin.
