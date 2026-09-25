import { api, post } from "./api";

export type PushState = "unsupported" | "denied" | "available" | "enabled";

export function pushState(): PushState {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return "available";
}

function b64ToUint8(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function enablePush(): Promise<void> {
  const cfg = await api<{ configured: boolean; public_key: string | null }>("/push/public-key");
  if (!cfg.configured || !cfg.public_key) throw new Error("Push is not configured on this server (VAPID keys missing).");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notification permission was not granted.");
  const reg = (await navigator.serviceWorker.getRegistration()) ?? (await navigator.serviceWorker.register("/sw.js"));
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(cfg.public_key) as BufferSource });
  const json = sub.toJSON();
  await post("/push/subscriptions", { endpoint: json.endpoint, keys: json.keys });
}
