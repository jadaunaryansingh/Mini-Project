import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAnalytics }  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-analytics.js";
import { getAuth }       from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";

async function initFirebase() {
  const response = await fetch("/firebase-config");
  if (!response.ok) {
    throw new Error(`Failed to load Firebase config: ${response.status} ${response.statusText}`);
  }
  const firebaseConfig = await response.json();
  const app       = initializeApp(firebaseConfig);
  const analytics = getAnalytics(app);
  const auth      = getAuth(app);
  return { app, auth, analytics };
}

export const firebaseReady = initFirebase();
