# Classification System Status Report
**Generated:** 2026-04-10  
**System:** OneTask FastAPI + React Application for MDR Advocacia

---

## Current State

### Database Statistics
- **Total Publication Records:** 192
- **With Text Content:** 192
- **Classified:** 25 (13.0%)
- **Unclassified:** 167 (87.0%)
- **Last Classification Activity:** 2026-04-10 17:14:48

### Issue: Rate Limiting on Anthropic API
**Problem:** Anthropic API rate limits (5 requests per minute, 10K tokens per minute) were causing classification to fail with 429 errors. Previous runs showed only 5/64 records classified, indicating systematic failures.

---

## Implemented Fixes

### 1. Retry Logic with Exponential Backoff
**File:** `app/services/classifier/ai_client.py`  
**Status:** ✅ IMPLEMENTED

The `AnthropicClassifierClient.classify()` method now includes:
- Up to 3 retries for 429 (Too Many Requests) errors
- Exponential backoff delays:
  - Attempt 1: 15 seconds
  - Attempt 2: 30 seconds  
  - Attempt 3: 60 seconds
- Respects `retry-after` header from API responses if provided
- Non-429 errors are immediately raised (no retry)
- Detailed logging for each retry attempt

**Key Code:**
```python
max_retries = 3
base_wait = 15  # segundos

for attempt in range(max_retries + 1):
    response = await client.post(...)
    
    if response.status_code == 429:
        if attempt < max_retries:
            retry_after = response.headers.get("retry-after")
            wait_time = int(retry_after) + 1 if retry_after else base_wait * (2 ** attempt)
            logger.warning("Rate limit (429) na tentativa %d/%d. Aguardando %ds...", ...)
            await asyncio.sleep(wait_time)
            continue
```

### 2. Reduced Concurrency
**File:** `app/services/publication_search_service.py`  
**Status:** ✅ IMPLEMENTED

Concurrency settings optimized for Anthropic rate limits:
- **CONCURRENCY:** 1 (sequential, not parallel)
- **Sleep between requests:** 12.0 seconds
- **Result:** Stays well within 5 RPM limit (only 5 requests per 60 seconds = 4.2 RPM)

**Rationale:** With sequential processing at 12-second intervals:
- 5 requests ÷ 60 seconds = 0.083 RPM (way below 5 RPM limit)
- Each request estimated at ~200 tokens input
- 5 × 200 = 1000 tokens per minute (way below 10K TPM limit)

---

## Testing Instructions

### Option 1: Using the React Frontend
1. Ensure the application is running:
   ```bash
   cd /sessions/admiring-sharp-cray/mnt/onetask
   docker-compose up -d
   ```
2. Navigate to http://localhost:5173
3. Look for the "Reclassify" button in the Publications section
4. Click to trigger reclassification of pending records
5. Monitor the backend logs for retry activity

### Option 2: Direct API Call
```bash
curl -X POST http://localhost:8000/api/v1/publications/reclassify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>"
```

### Option 3: Python Script
```python
import requests
response = requests.post(
    "http://localhost:8000/api/v1/publications/reclassify",
    headers={"Authorization": "Bearer <TOKEN>"}
)
print(response.json())
```

---

## Expected Behavior After Fix

### During Classification Run:
- Backend logs should show repeated warnings like:
  ```
  Rate limit (429) na tentativa 1/3. Aguardando 15s...
  Rate limit (429) na tentativa 2/3. Aguardando 30s...
  ```
- Classification will progress more slowly (12+ seconds per record) but should continue
- All records should eventually be processed

### Success Criteria:
- ✅ Classification Rate > 50% (at least 96+ records)
- ✅ No final failures; all retries eventually succeed
- ✅ Logs show exponential backoff being applied
- ✅ Total classification time: ~2-3 hours for 167 unclassified records

---

## Code Verification

### ✅ Verified Implementation:

**ai_client.py changes:**
- ✅ `asyncio` imported for sleep functionality
- ✅ Retry loop with exponential backoff (15s, 30s, 60s)
- ✅ `retry-after` header support
- ✅ Only retries on 429, not other errors
- ✅ Comprehensive error logging

**publication_search_service.py changes:**
- ✅ CONCURRENCY reduced from 3 to 1
- ✅ Sleep interval set to 12.0 seconds
- ✅ Respects Anthropic rate limits (5 RPM, 10K TPM)

---

## What's Different From Previous Attempts

| Aspect | Previous | Current |
|--------|----------|---------|
| Concurrency | 3-5 parallel requests | 1 sequential request |
| Sleep interval | 0.3-0.5 seconds | 12.0 seconds |
| Retry strategy | None (requests were skipped on 429) | Exponential backoff (15s, 30s, 60s) |
| Failure handling | Logged and skipped | Automatically retried |
| Rate limit respect | Aggressive | Conservative |

**Key Improvement:** Failed requests are now **retried** rather than **skipped**, ensuring all records get classified.

---

## Next Steps

1. **Start the Application:**
   ```bash
   docker-compose up -d
   ```

2. **Monitor Backend Logs:**
   ```bash
   docker logs -f onetask-api
   ```

3. **Trigger Reclassification:**
   - Via Frontend: Click "Reclassify" button
   - Via API: POST to `/api/v1/publications/reclassify`

4. **Track Progress:**
   ```bash
   # Check classification progress
   sqlite3 data/database.db "SELECT COUNT(category) as classified FROM publicacao_registros WHERE description IS NOT NULL"
   ```

5. **Verify Results:**
   - Expected: ~25 → 150+ classified records
   - Timeline: 2-3 hours for 167 records at 12-second intervals
   - Success: 0 failed records (all retries successful)

---

## Files Modified

- `app/services/classifier/ai_client.py` - Retry logic
- `app/services/publication_search_service.py` - Concurrency and sleep settings

## Files NOT Modified (But Important)

- `app/models/publicacao.py` - Publication model (no changes needed)
- `app/services/classifier/classification_service.py` - Uses ai_client (no changes needed)
- `app/api/v1/endpoints/publications.py` - Uses both services (no changes needed)

---

## Support

If classification still fails after testing:
1. Check backend logs for specific error messages
2. Verify Anthropic API key is valid and account has sufficient credits
3. Consider increasing `base_wait` from 15s to 30s if still hitting 429s
4. Reduce CONCURRENCY further or add longer inter-request delays if needed

