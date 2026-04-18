import {
  getDatabase,
  ref,
  get,
  set,
  push,
  update,
  query,
  limitToLast,
  serverTimestamp,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-database.js";

import { firebaseReady } from "./firebase-config.js";

const getDatabaseInstance = async () => {
  const { app } = await firebaseReady;
  return getDatabase(app);
};

function serializePayload(payload = {}) {
  return JSON.parse(
    JSON.stringify(payload, (_key, value) => {
      if (value === undefined) return null;
      if (typeof value === "number" && !Number.isFinite(value)) return null;
      if (value instanceof Error) return { message: value.message };
      return value;
    })
  );
}

export async function ensureUserProfile(user) {
  if (!user?.uid) return;

  const db = await getDatabaseInstance();
  const profileRef = ref(db, `users/${user.uid}/profile`);
  const snapshot = await get(profileRef);

  const profilePayload = {
    uid: user.uid,
    email: user.email || null,
    displayName: user.displayName || null,
    photoURL: user.photoURL || null,
    updatedAt: serverTimestamp(),
    lastLoginAt: serverTimestamp(),
  };

  if (!snapshot.exists()) {
    profilePayload.createdAt = serverTimestamp();
  }

  await update(profileRef, profilePayload);
}

export async function persistUserHistory(user, eventType, payload = {}) {
  if (!user?.uid) return;

  const db = await getDatabaseInstance();
  const historyRef = ref(db, `users/${user.uid}/history`);
  const entryRef = push(historyRef);

  await set(entryRef, {
    eventType,
    payload: serializePayload(payload),
    clientTimestamp: new Date().toISOString(),
    serverTimestamp: serverTimestamp(),
  });
}

export async function getRecentUserHistory(user, count = 10) {
  if (!user?.uid) return [];

  const db = await getDatabaseInstance();
  const historyQuery = query(ref(db, `users/${user.uid}/history`), limitToLast(count));
  const snapshot = await get(historyQuery);

  if (!snapshot.exists()) {
    return [];
  }

  const rows = [];
  snapshot.forEach((child) => {
    rows.push({ id: child.key, ...child.val() });
  });

  return rows.reverse();
}
