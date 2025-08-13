# NVD API Setup Guide

## When to use the NVD API

The project performs targeted CVE lookups against NVD using specific dependency-derived search terms. An API key is optional but recommended for faster and more reliable requests.

## Getting an NVD API Key

The National Vulnerability Database (NVD) issues API keys to raise rate limits.

### 1. Request an API Key
1. Go to: https://nvd.nist.gov/developers/request-an-api-key
2. Fill out the form with:
   - Name, Email, Organization
   - Intended Use: "Targeted CVE lookups for dependency analysis"
3. Submit the request

### 2. API Key Approval
- Approval time: usually 2–5 business days
- You’ll receive an API key via email

### 3. Using Your API Key

Prefer the console script entry point and the standard flag names used by the tool:

```bash
# Method 1: CLI flag (recommended)
code-graph-cve --api-key YOUR_API_KEY

# Method 2: Environment variable
export NVD_API_KEY=YOUR_API_KEY
code-graph-cve
```

### 4. Environment Variable Setup

Add to your shell profile (`.bashrc`, `.zshrc`, etc.):

```bash
# NVD API Key for CVE analysis
export NVD_API_KEY="your_actual_api_key_here"
```

## Rate Limits (reference)

| API Key Status | Effective Rate Limit               | Recommended Use            |
|----------------|------------------------------------|----------------------------|
| No API Key     | ~5 requests / 30 seconds           | Dev/test or small queries  |
| With API Key   | ~50 requests / 30 seconds          | Production / larger scans  |

The tool enforces rate limits and retries gracefully.

## Troubleshooting

1. 404 error (endpoint changes): use the CVE search endpoint shown below and update if needed
2. 403 Forbidden: supply a valid API key; check `NVD_API_KEY`
3. 429 Rate Limited: the tool will back off automatically; consider supplying an API key

## Testing Your Setup

```bash
# Quick connectivity with your key
code-graph-cve --api-key YOUR_KEY --cache-status
```

## API Documentation

Official docs: https://nvd.nist.gov/developers/vulnerabilities

Key endpoints used by this project:
- CVE Search: `https://services.nvd.nist.gov/rest/json/cves/2.0`
- Parameters: targeted keyword searches prepared by the tool
- Response: JSON with vulnerability details
