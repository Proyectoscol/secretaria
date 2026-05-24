/**
 * AES-256-GCM encryption for Microsoft platform tokens.
 * Uses Node.js built-in `crypto` — no external dependencies.
 *
 * The encryption key must be 32 bytes, base64-encoded.
 * Generate with: openssl rand -base64 32
 */
import crypto from "crypto";

const ALGORITHM = "aes-256-gcm";
const IV_LENGTH = 12;   // 96-bit IV recommended for GCM
const TAG_LENGTH = 16;

function getKey(): Buffer {
  const raw = process.env.MICROSOFT_TOKEN_ENCRYPTION_KEY;
  if (!raw) throw new Error("MICROSOFT_TOKEN_ENCRYPTION_KEY is not set");
  const key = Buffer.from(raw, "base64");
  if (key.length !== 32) {
    throw new Error(
      `MICROSOFT_TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes, got ${key.length}`
    );
  }
  return key;
}

export function encryptToken(plaintext: string): string {
  const key = getKey();
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv, { authTagLength: TAG_LENGTH });

  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();

  // Format: base64(iv + tag + ciphertext)
  return Buffer.concat([iv, tag, encrypted]).toString("base64");
}

export function decryptToken(ciphertext: string): string {
  const key = getKey();
  const data = Buffer.from(ciphertext, "base64");

  const iv = data.subarray(0, IV_LENGTH);
  const tag = data.subarray(IV_LENGTH, IV_LENGTH + TAG_LENGTH);
  const encrypted = data.subarray(IV_LENGTH + TAG_LENGTH);

  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv, {
    authTagLength: TAG_LENGTH,
  });
  decipher.setAuthTag(tag);

  return Buffer.concat([decipher.update(encrypted), decipher.final()]).toString("utf8");
}
