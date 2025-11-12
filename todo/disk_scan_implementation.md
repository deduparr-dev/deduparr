# Deep Scan Implementation Plan

## Overview
Add optional filesystem-based duplicate detection to complement Plex's API-based detection. This will catch duplicates that Plex misses, such as files in different directories with case-sensitivity differences or files that failed to hardlink properly.

## Problem Statement

### Current Situation
- Deduparr relies exclusively on Plex's `find_duplicate_movies()` and `find_duplicate_episodes()` API
- Plex's duplicate detection has limitations:
  - May not detect duplicates across different library locations
  - Case-sensitivity in filenames can cause misses
  - Files that should be hardlinked but aren't may not be detected
  
### Real-World Example Found
Testing revealed 2 groups of true duplicates (4 files, ~89GB wasted) that Plex didn't detect:
1. **Minions (2015)** - 2 copies × 9.59 GB
   - `/plexdownloads/Filmer/Minions.2015.SWEDiSH.2160p.WEB.h265-EKOLLON/minions.2015.swedish.2160p.web.h265-ekollon.mkv`
   - `/plexdownloads/Filmer/Minions (2015)/Minions.2015.SWEDiSH.2160p.WEB.h265-EKOLLON.mkv`

2. **Sonic the Hedgehog 2 (2022)** - 2 copies × 34.85 GB
   - `/plexdownloads/Filmer/Sonic.the.Hedgehog.2.2022.NORDiC.ENG.2160p.SDR.BluRay.DTS-HD.MA.TrueHD.7.1.Atmos.x265-NorTekst/Sonic.the.Hedgehog.2.2022.NORDiC.ENG.2160p.SDR.BluRay.DTS-HD.MA.TrueHD.7.1.Atmos.x265-NorTekst.mkv`
   - `/plexdownloads/Filmer/Sonic the Hedgehog 2 (2022)/Sonic.the.Hedgehog.2.2022.NORDiC.ENG.2160p.SDR.BluRay.DTS-HD.MA.TrueHD.7.1.Atmos.x265-NorTekst.mkv`

**Why Plex missed these:**
- Different directory structures (torrent folder vs organized library folder)
- Case differences in filenames
- Possibly in different Plex library sections

## Solution Design

### Architecture Decision
**Create a standalone `DiskScanService`** - completely independent of Plex/Radarr/Sonarr:
- ✅ Reusable and modular
- ✅ Can be tested independently
- ✅ No coupling to external APIs
- ✅ Works even if Plex is down/misconfigured

### User Experience
**Always use deep scan when enabled** - no per-scan toggle:
- User enables "Deep Scan" in Settings (one-time decision)
- All future scans automatically include disk scanning
- Clear warning that it's slower but more thorough

## Implementation Tasks

### Phase 1: Core Disk Scan Service

#### Task 1.1: Create `backend/app/services/disk_scan_service.py`
**Purpose:** Standalone filesystem-based duplicate detector

**Key Components:**
```python
class DiskScanService:
    """
    Filesystem-based duplicate detection service.
    Independent of Plex/Radarr/Sonarr - scans directories directly.
    """
    
    # Core scanning methods
    def find_duplicate_movies_on_disk(
        self, 
        directory_paths: List[str]
    ) -> Dict[str, List[Dict]]
    
    def find_duplicate_episodes_on_disk(
        self, 
        directory_paths: List[str]
    ) -> Dict[str, List[Dict]]
    
    # Helper methods
    def _scan_directory(
        self, 
        directory: str, 
        recursive: bool = True
    ) -> List[str]
    
    def _normalize_filename(self, filename: str) -> str
    
    def _extract_year(self, filename: str) -> str
    
    def _extract_episode_info(self, filename: str) -> str
    
    def _are_hardlinks(self, file1: str, file2: str) -> bool
    
    def _group_by_normalized_name(
        self, 
        files: List[str]
    ) -> Dict[str, List[str]]
    
    def _filter_hardlinks(
        self, 
        groups: Dict[str, List[str]]
    ) -> Dict[str, List[str]]
```

**Implementation Details:**

1. **Video File Detection:**
   - Extensions: `.mkv`, `.mp4`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.m2ts`, `.ts`
   - Exclude sample files (regex patterns: `sample`, `trailer`, `preview`, `rarbg.com`, etc.)

2. **Filename Normalization:**
   - Convert to lowercase
   - Remove quality markers: `1080p`, `720p`, `2160p`, `4k`, `BluRay`, `WEB-DL`, `x264`, `x265`, etc.
   - Remove brackets/parentheses content (except year)
   - Remove release group info
   - Normalize separators (`.`, `_`, `-` → space)
   - Strip extra whitespace

3. **Year Extraction:**
   - Regex: `\b(19\d{2}|20\d{2})\b`
   - Used to differentiate same-titled movies from different years

4. **Episode Info Extraction:**
   - Patterns: `S01E01`, `s01e01`, `1x01`, `season.1.episode.1`
   - Normalize to `S01E01` format

5. **Hardlink Detection:**
   - Compare `st_ino` (inode) and `st_dev` (device)
   - If same inode + device → hardlink (NOT a duplicate)
   - Only flag files with different inodes as true duplicates

6. **Return Format:**
   ```python
   {
       "movie_title|year": [
           {
               "path": "/path/to/file.mkv",
               "size": 12345678,
               "is_hardlink": False,
               "inode": 12345,
               "normalized_name": "movie title"
           },
           ...
       ]
   }
   ```

#### Task 1.2: Add Unit Tests - `backend/tests/test_disk_scan_service.py`
**Test Coverage:**
- Filename normalization edge cases
- Year extraction (with/without year)
- Episode info extraction (various formats)
- Hardlink detection
- Sample file exclusion
- Cross-directory scanning
- Empty directory handling

**Test Data Setup:**
- Create temporary test directories
- Generate test files with hardlinks
- Mock os.stat for inode testing

---

### Phase 2: Database & Configuration

#### Task 2.1: Add `enable_deep_scan` Config Setting
**File:** `backend/app/models/config.py`

**Add to Config model documentation:**
```python
# Scan Settings
enable_deep_scan: bool  # If True, always include filesystem-based duplicate detection
```

**Migration:** No schema change needed - uses existing key-value Config table

**Default Value:** `False` (opt-in feature)

#### Task 2.2: Create Config Routes for Deep Scan Setting
**File:** `backend/app/api/routes/config_routes.py`

**Add endpoints:**
```python
@router.get("/deep-scan")
async def get_deep_scan_setting(db: AsyncSession = Depends(get_db))
    # Return current enable_deep_scan value

@router.put("/deep-scan")
async def update_deep_scan_setting(
    enabled: bool,
    db: AsyncSession = Depends(get_db)
)
    # Save enable_deep_scan to database
```

---

### Phase 3: Scan Route Integration

#### Task 3.1: Update Scan Service - `backend/app/services/scan_service.py` (or create new)
**Create orchestration logic:**

```python
class ScanOrchestrator:
    """Coordinates Plex API scans and disk scans"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.plex_service = PlexService(db)
        self.disk_scan_service = DiskScanService()
    
    async def scan_movies(
        self, 
        library_name: str
    ) -> Dict[str, List[Movie]]:
        """
        Scan for duplicate movies using Plex API and optionally disk scan
        """
        # Check if deep scan is enabled
        deep_scan_enabled = await self._get_deep_scan_setting()
        
        # Always run Plex API scan (fast, primary method)
        plex_duplicates = self.plex_service.find_duplicate_movies(library_name)
        
        if not deep_scan_enabled:
            return plex_duplicates
        
        # Deep scan: get library paths and scan filesystem
        library = self.plex_service.get_library(library_name)
        library_paths = self._get_library_paths(library)
        
        disk_duplicates = self.disk_scan_service.find_duplicate_movies_on_disk(
            library_paths
        )
        
        # Merge results (deduplicate)
        merged = self._merge_duplicate_results(plex_duplicates, disk_duplicates)
        
        return merged
    
    async def scan_episodes(
        self, 
        library_name: str
    ) -> Dict[str, List[Episode]]:
        # Same pattern as scan_movies
        pass
    
    def _get_library_paths(self, library) -> List[str]:
        """Extract filesystem paths from Plex library"""
        # Get all location paths from Plex library object
        pass
    
    def _merge_duplicate_results(
        self, 
        plex_results: Dict, 
        disk_results: Dict
    ) -> Dict:
        """
        Merge Plex and disk scan results, avoiding duplicates
        
        Strategy:
        1. Use Plex results as base (they have full metadata)
        2. Add disk-only findings not in Plex results
        3. Match by file path to avoid double-counting
        """
        pass
```

#### Task 3.2: Update Scan Routes - `backend/app/api/routes/scan_routes.py`
**Modify existing endpoints:**

```python
@router.post("/movies")
async def scan_movies(
    library_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Scan for duplicate movies (includes deep scan if enabled)"""
    orchestrator = ScanOrchestrator(db)
    duplicates = await orchestrator.scan_movies(library_name)
    
    # Process duplicates (existing logic)
    # Store in DuplicateSet/DuplicateFile models
    # Return results

@router.post("/episodes")
async def scan_episodes(
    library_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Scan for duplicate episodes (includes deep scan if enabled)"""
    # Same pattern
    pass
```

**No API changes needed** - deep scan is transparent to frontend (controlled by config)

---

### Phase 4: Frontend Integration

#### Task 4.1: Add Deep Scan Setting to Settings Page
**File:** `frontend/src/pages/SettingsPage.tsx`

**Add to Scan Settings Section:**
```typescript
<div className="space-y-4">
  <h3 className="text-lg font-semibold">Scan Settings</h3>
  
  <div className="flex items-start space-x-3">
    <input
      type="checkbox"
      id="enable-deep-scan"
      checked={deepScanEnabled}
      onChange={handleDeepScanToggle}
      className="mt-1"
    />
    <div>
      <label htmlFor="enable-deep-scan" className="font-medium">
        Enable Deep Scan
      </label>
      <p className="text-sm text-gray-600">
        Scan filesystem directly for duplicates in addition to Plex API. 
        Slower but finds duplicates Plex might miss (e.g., case-sensitivity 
        differences, cross-directory duplicates).
      </p>
      <p className="text-sm text-yellow-600 mt-1">
        ⚠️ Deep scans take longer, especially for large libraries
      </p>
    </div>
  </div>
</div>
```

**Add API integration:**
```typescript
const { data: deepScanEnabled, refetch: refetchDeepScan } = useQuery({
  queryKey: ['config', 'deep-scan'],
  queryFn: () => api.get('/config/deep-scan').then(r => r.data.enabled)
});

const deepScanMutation = useMutation({
  mutationFn: (enabled: boolean) => 
    api.put('/config/deep-scan', { enabled }),
  onSuccess: () => {
    refetchDeepScan();
    toast.success(`Deep scan ${enabled ? 'enabled' : 'disabled'}`);
  }
});

const handleDeepScanToggle = (e: React.ChangeEvent<HTMLInputElement>) => {
  deepScanMutation.mutate(e.target.checked);
};
```

#### Task 4.2: Update Scan Page UI
**File:** `frontend/src/pages/ScanPage.tsx`

**Add visual indicator when deep scan is active:**
```typescript
{deepScanEnabled && (
  <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-4">
    <div className="flex items-center space-x-2">
      <HardDrive className="h-5 w-5 text-blue-600" />
      <span className="font-medium text-blue-900">Deep Scan Enabled</span>
    </div>
    <p className="text-sm text-blue-700 mt-1">
      Scanning filesystem directly for duplicates. This may take longer.
    </p>
  </div>
)}
```

**Update scan progress messages:**
- "Scanning via Plex API..."
- "Deep scanning filesystem..." (when enabled)
- "Found X duplicates (Y from Plex, Z from disk scan)"

#### Task 4.3: Add API Client Methods
**File:** `frontend/src/services/api.ts`

```typescript
// Config endpoints
export const getDeepScanSetting = () => 
  api.get<{ enabled: boolean }>('/config/deep-scan');

export const updateDeepScanSetting = (enabled: boolean) => 
  api.put('/config/deep-scan', { enabled });
```

---

### Phase 5: Testing & Validation

#### Task 5.1: Integration Tests
**File:** `backend/tests/test_scan_integration.py`

**Test Scenarios:**
1. Scan with deep scan disabled (Plex only)
2. Scan with deep scan enabled (Plex + disk)
3. Verify disk scan finds duplicates Plex missed
4. Verify hardlinks are NOT flagged as duplicates
5. Verify merge logic doesn't create duplicate entries
6. Test with empty libraries
7. Test with libraries containing only hardlinks

#### Task 5.2: Manual Testing Checklist
- [ ] Enable deep scan in Settings
- [ ] Run movie scan, verify it finds test duplicates
- [ ] Run episode scan
- [ ] Disable deep scan, verify faster scan (Plex only)
- [ ] Re-enable deep scan, verify duplicates appear again
- [ ] Test with library containing hardlinks (should NOT be flagged)
- [ ] Test with actual duplicate files (should be flagged)
- [ ] Verify UI shows correct counts and status messages

#### Task 5.3: Performance Testing
**Baseline Measurements:**
- Plex API scan time (existing)
- Deep scan time (new)
- Combined scan time

**Optimization Targets:**
- Deep scan should complete within 2x Plex API time for typical libraries
- Progress indicators should update every 100 files scanned
- Memory usage should not exceed 500MB for 10,000 files

---

### Phase 6: Documentation

#### Task 6.1: Update User Documentation
**File:** `docs/README.md` or create `docs/DEEP_SCAN.md`

**Content:**
- What is deep scan?
- When to use it
- Performance implications
- How it differs from Plex API scan
- Examples of duplicates it catches

#### Task 6.2: Update API Documentation
**File:** `docs/API_USAGE_EXAMPLES.md`

**Add examples:**
```bash
# Get deep scan setting
curl -X GET http://localhost:8655/api/config/deep-scan

# Enable deep scan
curl -X PUT http://localhost:8655/api/config/deep-scan \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Scan movies (automatically includes deep scan if enabled)
curl -X POST http://localhost:8655/api/scan/movies \
  -H "Content-Type: application/json" \
  -d '{"library_name": "Movies"}'
```

#### Task 6.3: Update IMPLEMENTATION_PLAN.md
**File:** `todo/IMPLEMENTATION_PLAN.md`

**Mark as implemented:**
- Deep scan feature
- Filesystem-based duplicate detection
- Hardlink detection

---

## Data Flow Diagram

```
User Enables Deep Scan in Settings
         ↓
    Setting saved to DB (Config.enable_deep_scan = True)
         ↓
User Triggers Scan from Scan Page
         ↓
Backend ScanOrchestrator.scan_movies()
         ↓
    ├─→ PlexService.find_duplicate_movies() (always runs)
    │        ↓
    │   Returns Plex API results
    │        ↓
    ├─→ Check enable_deep_scan from DB
    │        ↓
    │   If enabled:
    │        ↓
    ├─→ DiskScanService.find_duplicate_movies_on_disk()
    │        ↓
    │   1. Get library paths from Plex
    │   2. Scan directories recursively
    │   3. Group by normalized name
    │   4. Filter out hardlinks
    │   5. Return true duplicates
    │        ↓
    └─→ Merge Plex + Disk results
         ↓
    Store in DuplicateSet/DuplicateFile models
         ↓
    Return to Frontend
         ↓
    Display in Scan Page with Deep Scan indicator
```

---

## Edge Cases & Considerations

### Hardlink Handling
- **Issue:** User has 602 hardlinked files (same content, different paths)
- **Solution:** DiskScanService detects hardlinks via inode comparison and excludes them
- **Result:** Only 6 true duplicates flagged (not 608)

### Cross-Library Duplicates
- **Issue:** Same movie in "Movies" and "Downloads" libraries
- **Solution:** Deep scan checks ALL paths within selected library
- **Future:** Could scan multiple libraries simultaneously

### Case Sensitivity
- **Issue:** "Minions.mkv" vs "minions.mkv" treated as different files
- **Solution:** Normalize to lowercase before comparison

### Performance on Large Libraries
- **Issue:** Scanning 10,000+ files can be slow
- **Solution:** 
  - Show progress indicator
  - Scan in batches
  - Cache results (future enhancement)

### Plex Library Path Detection
- **Issue:** Need to get filesystem paths from Plex library
- **Solution:** Use `library.locations` from Plex API
- **Fallback:** If not available, require user to configure library paths in Settings

### Missing Plex Metadata
- **Issue:** Disk-only duplicates don't have Plex metadata (title, year, poster)
- **Solution:** Extract from filename, mark as "disk-only" finding
- **Enhancement:** Try to match with Radarr/Sonarr for metadata

---

## Success Criteria

### Functional Requirements
✅ Deep scan setting can be enabled/disabled in Settings
✅ When enabled, all scans include filesystem-based detection
✅ Hardlinks are correctly identified and NOT flagged as duplicates
✅ True duplicates (non-hardlinks) are detected even if Plex misses them
✅ Results from Plex API and disk scan are merged without duplication

### Performance Requirements
✅ Deep scan completes within reasonable time (< 5 min for 1000 files)
✅ Progress indicators show during scan
✅ UI remains responsive during scan

### User Experience Requirements
✅ Clear documentation of what deep scan does
✅ Warning about performance impact
✅ Visual indicator when deep scan is active
✅ Scan results clearly show source (Plex vs disk)

---

## Timeline Estimate

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| Phase 1: Core Service | Tasks 1.1-1.2 | 4-6 hours |
| Phase 2: Config | Tasks 2.1-2.2 | 2-3 hours |
| Phase 3: Integration | Tasks 3.1-3.2 | 3-4 hours |
| Phase 4: Frontend | Tasks 4.1-4.3 | 3-4 hours |
| Phase 5: Testing | Tasks 5.1-5.3 | 4-5 hours |
| Phase 6: Documentation | Tasks 6.1-6.3 | 2-3 hours |
| **Total** | | **18-25 hours** |

---

## Future Enhancements (Post-MVP)

1. **Checksum-based verification**
   - Optional MD5/SHA256 comparison for 100% certainty
   - Very slow, only for final verification

2. **Smart caching**
   - Cache normalized filename results
   - Only re-scan changed directories

3. **Parallel scanning**
   - Scan multiple directories concurrently
   - Use thread pool for I/O operations

4. **Cross-library scanning**
   - Scan multiple Plex libraries at once
   - Find duplicates across different libraries

5. **Automatic hardlink suggestion**
   - Detect duplicates that could be hardlinked
   - Offer to convert copies to hardlinks (save space)

6. **Radarr/Sonarr integration**
   - Use *arr metadata for disk-only findings
   - Better title/year extraction

---

## Questions to Resolve

1. Should we store deep scan results separately in the database?
   - **Recommendation:** No, merge into existing DuplicateSet/DuplicateFile
   - Add `detection_method` field: "plex_api" | "disk_scan" | "both"

2. Should deep scan be per-library or global setting?
   - **Recommendation:** Global setting (simpler UX)
   - User enables once, applies to all scans

3. How to handle very large libraries (100k+ files)?
   - **Recommendation:** Add batch processing and progress updates
   - Consider adding max file limit with warning

4. Should we scan symlinks?
   - **Recommendation:** Yes, but detect and flag them like hardlinks
   - Same file, different path = not a duplicate

---

## Implementation Priority

**Must Have (MVP):**
- ✅ DiskScanService with basic duplicate detection
- ✅ Hardlink detection and exclusion
- ✅ Config setting to enable/disable
- ✅ Frontend settings toggle
- ✅ Integration with existing scan routes

**Should Have:**
- ✅ Progress indicators during deep scan
- ✅ Visual indicator on Scan page
- ✅ Basic documentation

**Nice to Have:**
- ⏳ Checksum verification
- ⏳ Parallel scanning
- ⏳ Cross-library scanning
- ⏳ Smart caching

**Future:**
- 🔮 Automatic hardlink conversion
- 🔮 Advanced performance optimizations
- 🔮 ML-based duplicate detection
