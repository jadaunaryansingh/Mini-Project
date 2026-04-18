import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  onAuthStateChanged,
  sendPasswordResetEmail,
  updateProfile,
  GoogleAuthProvider,
  signInWithPopup,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";

import { firebaseReady } from "./firebase-config.js";

const getAuth = async () => (await firebaseReady).auth;

export async function signUp(email, password, displayName = "") {
  const auth = await getAuth();
  const credential = await createUserWithEmailAndPassword(auth, email, password);
  if (displayName) {
    await updateProfile(credential.user, { displayName });
  }
  return credential;
}

export async function signIn(email, password) {
  const auth = await getAuth();
  return signInWithEmailAndPassword(auth, email, password);
}

export async function signOut() {
  const auth = await getAuth();
  return firebaseSignOut(auth);
}

const googleProvider = new GoogleAuthProvider();

export async function signInWithGoogle() {
  const auth = await getAuth();
  return signInWithPopup(auth, googleProvider);
}

export async function resetPassword(email) {
  const auth = await getAuth();
  return sendPasswordResetEmail(auth, email);
}

export async function onUserStateChanged(callback) {
  const auth = await getAuth();
  return onAuthStateChanged(auth, callback);
}

export async function getCurrentUser() {
  const auth = await getAuth();
  return auth.currentUser;
}
