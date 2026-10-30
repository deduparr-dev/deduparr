# Security Policy

## NPM Supply Chain Protection

This project implements security measures to prevent NPM supply chain attacks as documented in:
https://www.trendmicro.com/en_us/research/25/i/npm-supply-chain-attack.html

### Security Measures

1. **Package Lock Enforcement**: `package-lock.json` is required and enforced
2. **Registry Pinning**: `.npmrc` pins the official npm registry (the development image, `frontend/Dockerfile.dev`, tries the registry.npmmirror.com mirror first)
3. **Integrity Checking**: Package integrity verified via checksums
4. **Version Pinning**: New dependencies are saved with exact versions (`save-exact=true`), and `package-lock.json` pins every installed version
5. **Regular Audits**: `npm audit` is recommended before releases.

### Running Security Checks

```bash
cd frontend

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

If you discover a security vulnerability, please email hello@deduparr.com.

## Code Security Standards

Per `AGENTS.md`:

1. **NO `any` type**: Always use specific types
   - ✅ `Record<string, string>` 
   - ✅ `string | number`
   - ❌ `any`
   - ❌ `Record<string, any>`

2. **NO `useEffect`**: Use React Query, form actions, or event handlers
3. **Type Safety**: All event handlers must have explicit types
4. **Modern React**: React 19.2 patterns only

## Dependency Updates

Dependabot proposes updates every Monday, and its pull requests, major versions included, are approved and merged once CI passes: see [DEPENDABOT_AUTO_MERGE.md](DEPENDABOT_AUTO_MERGE.md).

## Frontend Security Architecture

### Token Transmission

Sensitive authentication tokens are transmitted via HTTP request bodies, not URL parameters. This keeps them out of browser history and server logs; the browser's network inspector still shows them.

**Implementation:**
- POST requests for every operation that sends a credential (the Plex sign-in starts and polls its PIN with GET requests)
- Credentials typed in the wizard or Settings are sent as typed. The API returns a stored one only as a mask, and a connection test uses it only with the server stored with it
- URL parameters never contain credentials

### Development Mode Considerations

During development (`npm run dev`), Vite's hot module replacement (HMR) creates WebSocket connections with ephemeral tokens. These tokens:
- Are randomly generated per session
- Provide no access to application data
- Only enable development features (live reload)
- Are not present in production builds

### Plex Token

Deduparr loads no Plex thumbnails or streams, so the Plex token never appears in a URL: the backend sends it to Plex in the `X-Plex-Token` header. The stored token is encrypted, and the API never returns it. It is redacted from logs, and can be revoked through Plex account settings.

### Frontend Security Utilities

The `src/lib/security.ts` module provides:
- Log sanitization for production environments
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

The backend's security helpers are in `app/services/shared/security.py`:
- Encryption and decryption of stored secrets (TokenManager)
- Log data sanitization (SensitiveDataFilter)

API keys, authentication tokens, and passwords are encrypted with Fernet before database storage, and values sent to `/api/config/import/all` are too. `GET /api/config/` and the export return a set secret only as `********`. The key (`/app/data/.encryption_key`) is file-based and persists across container restarts via Docker volumes. Deduparr has no login, so anyone who can reach the API can still use it: keep it off untrusted networks. It sends no CORS headers, so another site open in a browser cannot call it.
