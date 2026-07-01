const CHAT_NAME_KEY = "cps_chat_display_name";
const CHAT_DEVICE_KEY = "cps_chat_device_id";

function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `d-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function slugify(name: string): string {
  return (
    name
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/\p{Diacritic}/gu, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "user"
  );
}

function getDeviceId(): string {
  if (typeof window === "undefined") return "server";
  let id = localStorage.getItem(CHAT_DEVICE_KEY);
  if (!id) {
    id = randomId();
    localStorage.setItem(CHAT_DEVICE_KEY, id);
  }
  return id;
}

export function getChatDisplayName(): string {
  if (typeof window === "undefined") return "";
  return (localStorage.getItem(CHAT_NAME_KEY) || "").trim();
}

export function setChatDisplayName(name: string): void {
  const trimmed = name.trim();
  if (!trimmed) return;
  localStorage.setItem(CHAT_NAME_KEY, trimmed);
}

export function clearChatDisplayName(): void {
  localStorage.removeItem(CHAT_NAME_KEY);
}

/** user_id ổn định theo tên + thiết bị — mỗi tên một session bot riêng. */
export function chatUserIdForName(displayName: string): string {
  const slug = slugify(displayName);
  const device = getDeviceId().slice(0, 8);
  return `${slug}-${device}`;
}

export function isValidChatName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed.length >= 2 && trimmed.length <= 40;
}
