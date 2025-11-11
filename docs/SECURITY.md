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

If you discover a security vulnerability, please email security@deduparr.dev or open a private security advisory on GitHub.

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
