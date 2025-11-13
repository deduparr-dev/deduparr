# Security Policy

## NPM Supply Chain Protection

This project implements security measures to prevent NPM supply chain attacks as documented in:
https://www.trendmicro.com/en_us/research/25/i/npm-supply-chain-attack.html

### Security Measures

1. **Package Lock Enforcement**: `package-lock.json` is required and enforced
2. **Registry Pinning**: Only official npm registry allowed
3. **Integrity Checking**: Package integrity verified via checksums
4. **Version Pinning**: Exact versions saved (no `^` or `~`)
5. **Regular Audits**: `npm audit` is recommended before releases.

### Running Security Checks

```bash
# Check for vulnerabilities
npm run security-check

# Audit only
npm run audit

# Fix non-breaking vulnerabilities
npm run audit:fix

# Update dependencies (review carefully!)
npm update
```

### Known Vulnerabilities

No known vulnerabilities. All dependencies are up to date and security audits pass.

## Reporting Security Issues

If you discover a security vulnerability, please email hello@deduparr.com or open a private security advisory on GitHub.

## Code Security Standards

Per `.github/copilot-instructions.md`:

1. **NO `any` type**: Always use specific types
   - ✅ `Record<string, string>` 
   - ✅ `string | number`
   - ❌ `any`
   - ❌ `Record<string, any>`

2. **NO `useEffect`**: Use React Query, form actions, or event handlers
3. **Type Safety**: All event handlers must have explicit types
4. **Modern React**: React 19.2 patterns only

## Dependency Updates

Dependencies are reviewed monthly. Breaking changes require:
1. Code review
2. Full test suite pass
3. Security audit clear
4. Manual QA testing

## Frontend Security Architecture

### Token Transmission

Sensitive authentication tokens are transmitted via HTTP request bodies, not URL parameters. This prevents token exposure in browser history, server logs, and network inspection tools.

**Implementation:**
- POST requests for all authentication operations
- Request body contains encrypted tokens
- URL parameters never contain credentials

### Development Mode Considerations

During development (`npm run dev`), Vite's hot module replacement (HMR) creates WebSocket connections with ephemeral tokens. These tokens:
- Are randomly generated per session
- Provide no access to application data
- Only enable development features (live reload)
- Are not present in production builds

### Plex Media Resources

Plex Media Server requires authentication tokens in resource URLs (thumbnails, transcoded streams, metadata). These tokens are protected by:
- Database encryption using itsdangerous
- Log sanitization preventing exposure in browser developer tools
- Revocation capability through Plex account settings
- User-scoped visibility (only accessible to authenticated user)
- Plex's standard security model

### Frontend Security Utilities

The `src/lib/security.ts` module provides:
- Log sanitization for production environments
- Request data redaction
- Error message sanitization
- Debug output protection

**Usage:**
```typescript
import { sanitizeLogData, sanitizeUrl } from '@/lib/security';

console.log('Data:', sanitizeLogData(response));
console.log('URL:', sanitizeUrl(requestUrl));
```

### Developer Guidelines

1. Transmit credentials in request bodies, not URLs
2. Sanitize all log output containing sensitive data
3. Use POST methods for authentication operations
4. Implement proper TypeScript types (no `any`)

### User Guidelines

1. Revoke Plex tokens if compromise is suspected
2. Use HTTPS for remote access
3. Avoid sharing browser developer console screenshots
4. Keep application credentials private

### Backend Security

The backend implements comprehensive security through `app/services/security.py`:
- Token encryption/decryption (TokenManager)
- Log data sanitization (SensitiveDataFilter)
- CSRF protection (state token generation)
- URL normalization

All API keys, authentication tokens, and passwords are encrypted using itsdangerous URLSafeSerializer before database storage. The encryption key is file-based and persists across container restarts via Docker volumes.
