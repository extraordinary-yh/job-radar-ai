import fs from "node:fs";
const [payloadPath, pass] = process.argv.slice(2);
const p = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
const b64 = (s) => Uint8Array.from(Buffer.from(s, "base64"));
const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]);
const key = await crypto.subtle.deriveKey(
  { name: "PBKDF2", salt: b64(p.salt), iterations: p.iterations, hash: "SHA-256" },
  base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(p.nonce) }, key, b64(p.ct));
process.stdout.write(new TextDecoder().decode(pt));
