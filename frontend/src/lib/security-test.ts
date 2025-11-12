/**
 * Test frontend security utilities
 * Run in browser console to verify sanitization works
 */

import { sanitizeUrl, sanitizeLogData } from "./security";

// Test URL sanitization
console.log("=== URL Sanitization Tests ===");
console.log("With token:", sanitizeUrl("http://plex.server/photo?token=abc123def456"));
console.log("With API key:", sanitizeUrl("https://api.example.com/data?api_key=secret123"));
console.log("Clean URL:", sanitizeUrl("https://api.example.com/data?page=1&limit=10"));

// Test log data sanitization
console.log("\n=== Log Data Sanitization Tests ===");
console.log("Long token:", sanitizeLogData("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"));
console.log("Short data:", sanitizeLogData("abc"));
console.log("API key:", sanitizeLogData("sk-1234567890abcdefghijklmnop"));

// Test console security filter
console.log("\n=== Console Filter Test (Production Only) ===");
console.log("This should be sanitized in production:");
console.log("Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.signature");
console.log("URL: http://plex/thumb?token=secret123");
console.log({
  api_key: "my-secret-key-12345",
  password: "super-secret-password",
  username: "safe-to-show",
});

export function runSecurityTests() {
  console.log("✅ Security utilities loaded. Check console output above.");
  console.log("⚠️  Note: Console filtering only active in production builds (npm run build)");
}
