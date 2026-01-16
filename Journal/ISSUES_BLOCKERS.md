# Issues and Blockers Log

**Project:** StreamFlow DataOps Implementation  
**Purpose:** Track problems, blockers, and their resolutions

---

## Issue Template

```
## [#ID] Issue Title
**Date Reported:** YYYY-MM-DD
**Status:** Open / In Progress / Resolved / Closed
**Severity:** Critical / High / Medium / Low
**Phase:** Phase number
**Reporter:** Name/System
**Description:** Clear description of the issue
**Impact:** What is affected
**Workaround:** Temporary solution (if any)
**Resolution:** How it was resolved
**Date Resolved:** YYYY-MM-DD
```

---

## Active Issues

### [#002] psycopg2-binary Installation Failed
**Date Reported:** January 16, 2026  
**Status:** ✅ Resolved (Workaround)  
**Severity:** Low  
**Phase:** Phase 0  
**Description:** Attempted to install psycopg2-binary==2.9.9 from requirements.txt. Installation failed with error: "pg_config executable not found". This is because PostgreSQL development libraries are not installed on the system.  
**Impact:** Cannot use PostgreSQL database immediately. Limited to SQLite for development.  
**Workaround:** Use SQLite for all development phases. Documented in Decision [D015].  
**Resolution:** Decided to use SQLite for development, PostgreSQL for production only. If PostgreSQL needed for development, install postgresql-devel package or use Docker.  
**Date Resolved:** January 16, 2026

### [#003] Static Files Directory Missing
**Date Reported:** January 16, 2026  
**Status:** 📝 Open (Low Priority)  
**Severity:** Low  
**Phase:** Phase 0  
**Description:** Django `manage.py check` reports warning: "The directory '/home/mrguy/Proj/streamflow-dataOps/streamflow-dataOps/static' in the STATICFILES_DIRS setting does not exist."  
**Impact:** Warning only, doesn't affect functionality. Django staticfiles won't work until created.  
**Workaround:** None needed for Phase 0.  
**Resolution:** Will create `static/` directory in Phase 1 when working on UI.  
**Target Date:** Phase 1

### [#004] Existing Tests Use SQLAlchemy (Not Django ORM)
**Date Reported:** January 16, 2026  
**Status:** 📝 Open (Medium Priority)  
**Severity:** Medium  
**Phase:** Phase 0  
**Description:** The project has 5 test files (test_data_processor.py, test_models.py, test_repositories.py, test_smart_append.py, test_usgs_client.py) but they were written for the original SQLAlchemy implementation, not Django ORM. Tests cannot run in current state.  
**Impact:** Cannot run automated tests until updated. Test coverage is 0%.  
**Workaround:** Manual testing for now.  
**Resolution:** Update tests to use Django ORM and pytest-django in Phase 1-2.  
**Estimated Effort:** 1-2 days  
**Target Phase:** Phase 1 (during UI development)

---

## Resolved Issues

### [#001] Example Placeholder Issue
**Status:** 📝 Template (Removed)  
This was just a template example.

---

## Blockers

### Critical Blockers (Stopping Work)

None.

---

### High Priority Blockers (Impacting Schedule)

None.

---

### Medium Priority Blockers (May Impact Schedule)

None.

---

## Technical Debt

### Identified Technical Debt

#### [TD001] Update Acquisition Layer to Use Django ORM
**Date Identified:** January 16, 2026  
**Status:** 📋 Planned  
**Description:** Component 2 (acquisition layer) was originally built with SQLAlchemy. Needs conversion to Django ORM.  
**Impact:** Code inconsistency, harder maintenance  
**Priority:** High  
**Target Phase:** Phase 3  
**Estimated Effort:** 1-2 days

#### [TD002] Incomplete Templates in Component 3
**Date Identified:** January 16, 2026  
**Status:** 📋 Planned  
**Description:** Some templates in `apps/streamflow/templates/` are stubs or incomplete.  
**Impact:** Non-functional UI pages  
**Priority:** High  
**Target Phase:** Phase 1  
**Estimated Effort:** 3-4 days

---

## Risks and Concerns

### [R001] Performance with 1,500+ Stations
**Category:** Performance  
**Probability:** Medium  
**Impact:** High  
**Description:** Data collection and API queries may be slow with full station list.  
**Mitigation:**
- Early performance testing
- Query optimization
- Caching strategy
- Chunking and pagination
**Status:** 🟡 Monitoring

### [R002] USGS API Rate Limiting
**Category:** External Dependency  
**Probability:** High  
**Impact:** Medium  
**Description:** USGS may rate limit or block requests if we exceed limits.  
**Mitigation:**
- Respect rate limits (current: 0.5s delay)
- Implement exponential backoff
- Monitor 429 responses
- Consider caching
**Status:** 🟡 Monitoring

### [R003] Data Consistency During Migration
**Category:** Data Integrity  
**Probability:** Medium  
**Impact:** High  
**Description:** Risk of data loss or corruption when migrating from dashboard database.  
**Mitigation:**
- Comprehensive validation scripts
- Backup before migration
- Dry-run testing
- Parallel operation period
**Status:** 🟡 Monitoring

---

## Questions and Unknowns

### [Q001] PostgreSQL or SQLite for Development?
**Status:** ❓ Open  
**Context:** Plan says PostgreSQL for production, SQLite for dev. Do we need both?  
**Impact:** Development environment setup complexity  
**Decision Needed By:** Phase 0  
**Options:**
1. Support both (requires compatibility testing)
2. PostgreSQL only (requires Docker/local install)
3. SQLite only (may miss PostgreSQL-specific issues)

### [Q002] How to Handle Dashboard During Transition?
**Status:** ❓ Open  
**Context:** Dashboard currently collects its own data. When to switch to API?  
**Impact:** Production availability  
**Decision Needed By:** Phase 4  
**Options:**
1. Hard cutover (risky)
2. Parallel operation with manual sync (complex)
3. Feature flag to toggle between sources (preferred)

---

## Lessons Learned

### [L001] Branch Management
**Date:** January 16, 2026  
**Context:** Had separate `master` and `main` branches with divergent content.  
**Lesson:** Establish single primary branch early; avoid parallel development on multiple branches.  
**Action Taken:** Merged master → main, deleted master branch.

---

## Communication Log

### Internal Notes

**January 16, 2026:**
- Project kickoff
- Completed project analysis
- Created implementation plan
- Set up Journal system

---

## Dependencies Tracking

### External Dependencies

| Dependency | Current Version | Required Version | Status | Notes |
|-----------|----------------|------------------|--------|-------|
| Django | 4.2.7 | 4.2+ | ✅ OK | Installed |
| Celery | 5.3.4 | 5.3+ | ✅ OK | Installed |
| Redis | 5.0.1 | 5.0+ | ✅ OK | Installed |
| PostgreSQL | - | 12+ | ⚠️ TBD | Need to verify |
| DRF | - | 3.14+ | ❌ NOT INSTALLED | Phase 2 |

### Internal Dependencies (Between Phases)

- Phase 1 → Phase 2: UI informs API design
- Phase 2 → Phase 3: API must exist before integration
- Phase 3 → Phase 4: Backend must be stable before dashboard integration
- Phases 1-4 → Phase 5: All features complete before comprehensive testing

---

## Issue Statistics

**Total Issues:** 0  
**Open:** 0  
**In Progress:** 0  
**Resolved:** 0  
**Closed:** 0

**By Severity:**
- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**By Phase:**
- Phase 0: 0
- Phase 1: 0
- Phase 2: 0
- Phase 3: 0
- Phase 4: 0
- Phase 5: 0

---

**Last Updated:** January 16, 2026, 1:30 PM
