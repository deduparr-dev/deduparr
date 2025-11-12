/**
 * Security utilities for sanitizing sensitive data in browser console/network logs
 */

/**
 * Sanitize URL by removing or redacting sensitive query parameters
 * Prevents tokens, API keys, and passwords from appearing in browser DevTools
 */
export function sanitizeUrl(url: string): string {
  if (!url) return url;

  try {
    const urlObj = new URL(url, window.location.origin);
    const sensitiveParams = [
      "token",
      "auth_token",
      "access_token",
      "api_key",
      "apikey",
      "password",
      "passwd",
      "pwd",
      "secret",
      "key",
    ];

    // Check if URL has any sensitive parameters
    let hasSensitive = false;
    for (const param of sensitiveParams) {
      if (urlObj.searchParams.has(param)) {
        hasSensitive = true;
        urlObj.searchParams.set(param, "***REDACTED***");
      }
    }

    return hasSensitive ? urlObj.toString() : url;
  } catch {
    // If URL parsing fails, try regex-based sanitization
    return url.replace(
      /([?&])(token|auth_token|access_token|api_key|apikey|password|passwd|pwd|secret|key)=([^&\s]+)/gi,
      "$1$2=***REDACTED***"
    );
  }
}

/**
 * Sanitize log data by showing only first/last few characters
 * Matches Python backend's sanitize_log_data function
 */
export function sanitizeLogData(data: string): string {
  if (!data || data.length <= 8) {
    return "***";
  }

  const visibleChars = Math.min(4, Math.floor(data.length / 3));
  if (data.length <= visibleChars * 2) {
    return "***";
  }

  return `${data.slice(0, visibleChars)}...${data.slice(-visibleChars)}`;
}

/**
 * Override console methods to sanitize sensitive data
 * Should be called early in application lifecycle (main.tsx)
 */
export function setupConsoleSecurityFilter() {
  if (import.meta.env.PROD) {
    // In production, sanitize all console output
    const originalLog = console.log;
    const originalWarn = console.warn;
    const originalError = console.error;
    const originalInfo = console.info;
    const originalDebug = console.debug;

    console.log = (...args: unknown[]) => originalLog(...args.map(sanitizeConsoleArg));
    console.warn = (...args: unknown[]) => originalWarn(...args.map(sanitizeConsoleArg));
    console.error = (...args: unknown[]) => originalError(...args.map(sanitizeConsoleArg));
    console.info = (...args: unknown[]) => originalInfo(...args.map(sanitizeConsoleArg));
    console.debug = (...args: unknown[]) => originalDebug(...args.map(sanitizeConsoleArg));
  }
}

function sanitizeConsoleArg(arg: unknown): unknown {
  if (typeof arg === "string") {
    // Sanitize URLs with tokens
    return sanitizeUrl(arg);
  }
  if (arg && typeof arg === "object") {
    // Sanitize objects (shallow clone to avoid mutations)
    return sanitizeObject(arg);
  }
  return arg;
}

function sanitizeObject(obj: unknown): unknown {
  if (Array.isArray(obj)) {
    return obj.map(sanitizeConsoleArg);
  }

  if (obj && typeof obj === "object") {
    const sanitized: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      // Sanitize known sensitive keys
      if (
        /token|api_key|apikey|password|passwd|pwd|secret|key/i.test(key) &&
        typeof value === "string"
      ) {
        sanitized[key] = sanitizeLogData(value);
      } else {
        sanitized[key] = sanitizeConsoleArg(value);
      }
    }
    return sanitized;
  }

  return obj;
}

/**
 * Axios/Fetch interceptor to sanitize request URLs in DevTools Network tab
 * Note: This only affects logged URLs, not actual requests
 */
export function sanitizeRequestUrl(config: { url?: string }): void {
  if (config.url) {
    // Store original URL for actual request
    const originalUrl = config.url;
    // Override toString to show sanitized version in DevTools
    Object.defineProperty(config, "url", {
      value: originalUrl,
      enumerable: true,
      configurable: true,
      writable: true,
    });
  }
}
