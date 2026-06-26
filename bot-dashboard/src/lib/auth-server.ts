/** Session token — cùng thuật toán với dashboard/auth.py (SHA256 salt:password). */
export async function sessionTokenForPassword(password: string): Promise<string> {
  const salt = process.env.DASHBOARD_AUTH_SALT || "cps-bot-dashboard";
  const raw = `${salt}:${password}`;
  const data = new TextEncoder().encode(raw);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function passwordsMatch(input: string, configured: string): boolean {
  if (input.length !== configured.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < input.length; i++) {
    diff |= input.charCodeAt(i) ^ configured.charCodeAt(i);
  }
  return diff === 0;
}
