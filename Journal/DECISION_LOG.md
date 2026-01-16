# Decision Log

**Project:** StreamFlow DataOps Implementation  
**Purpose:** Track key technical and architectural decisions

---

## Decision Template

```
## [ID] Decision Title
**Date:** YYYY-MM-DD
**Status:** Proposed / Accepted / Rejected / Deprecated
**Context:** Why this decision is needed
**Decision:** What was decided
**Consequences:** Impact and trade-offs
**Alternatives Considered:** Other options evaluated
```

---

## [D001] Use Django ORM Instead of SQLAlchemy

**Date:** December 16, 2024 (pre-project)  
**Status:** ✅ Accepted  
**Context:** Original Component 1 used SQLAlchemy. Need to choose ORM for Django integration.  
**Decision:** Migrate from SQLAlchemy to Django ORM for all models.  
**Consequences:**
- ✅ Better Django ecosystem integration
- ✅ Simplified admin interfaces
- ✅ GeoDjango support for future spatial features
- ❌ Lost some SQLAlchemy-specific features
- ❌ Required migration of existing code

**Alternatives Considered:**
1. Keep SQLAlchemy alongside Django ORM (rejected - too complex)
2. Use Django with SQLAlchemy views (rejected - poor integration)

**Reference:** DJANGO_MIGRATION.md

---

## [D002] Celery + Redis for Task Queue

**Date:** December 16, 2024 (pre-project)  
**Status:** ✅ Accepted  
**Context:** Need asynchronous task processing for data collection.  
**Decision:** Use Celery with Redis as message broker.  
**Consequences:**
- ✅ Proven, mature solution
- ✅ Django-Celery-Beat for dynamic scheduling
- ✅ Easy to scale with multiple workers
- ✅ Good monitoring tools (Flower)
- ❌ Additional infrastructure (Redis)

**Alternatives Considered:**
1. Django-RQ (rejected - less features than Celery)
2. Huey (rejected - smaller community)
3. Dramatiq (rejected - less Django integration)

---

## [D003] PostgreSQL for Production, SQLite for Development

**Date:** December 16, 2024 (pre-project)  
**Status:** ✅ Accepted  
**Context:** Need to choose database system.  
**Decision:** Use PostgreSQL in production, SQLite for local development.  
**Consequences:**
- ✅ PostgreSQL handles concurrent writes
- ✅ Better performance for large datasets
- ✅ Advanced features (JSON, full-text search)
- ✅ SQLite simplifies local setup
- ⚠️ Need to ensure compatibility between both

**Alternatives Considered:**
1. PostgreSQL only (rejected - harder local setup)
2. MySQL (rejected - prefer PostgreSQL features)
3. SQLite only (rejected - not suitable for production)

---

## [D004] Django REST Framework for API

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Need to expose data via REST API for dashboard and other consumers.  
**Decision:** Use Django REST Framework (DRF) for all API endpoints.  
**Consequences:**
- ✅ Industry standard for Django APIs
- ✅ Excellent serialization system
- ✅ Built-in authentication, permissions, throttling
- ✅ Browsable API for development
- ✅ Great documentation tools (drf-spectacular)
- ❌ Learning curve for advanced features

**Alternatives Considered:**
1. FastAPI (rejected - would require separate app, prefer Django ecosystem)
2. Django Ninja (rejected - newer, less mature)
3. Plain Django views with JSON (rejected - too much manual work)

---

## [D005] JWT for API Authentication

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Need secure authentication for REST API.  
**Decision:** Use JWT (JSON Web Tokens) via djangorestframework-simplejwt.  
**Consequences:**
- ✅ Stateless authentication
- ✅ Works well for service-to-service communication
- ✅ Token refresh mechanism
- ✅ Can include custom claims
- ⚠️ Need proper token expiration handling
- ⚠️ Token invalidation requires additional logic

**Alternatives Considered:**
1. Session-based auth (rejected - not ideal for API)
2. API keys only (rejected - less flexible)
3. OAuth2 (rejected - overkill for this use case)

**Additional:** Will also support API keys for simpler service integration.

---

## [D006] Separate Backend (DataOps) from Frontend (Dashboard)

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Dashboard currently has data collection embedded. Need to separate concerns.  
**Decision:** Build DataOps as standalone backend service with REST API; Dashboard becomes API consumer.  
**Consequences:**
- ✅ Separation of concerns
- ✅ Each system can be developed/deployed independently
- ✅ API can serve multiple clients
- ✅ Easier to scale backend vs frontend independently
- ✅ Better testability
- ❌ More complex deployment (two services)
- ❌ Network latency for API calls
- ⚠️ Need caching strategy in dashboard

**Alternatives Considered:**
1. Keep data collection in dashboard (rejected - tight coupling)
2. Merge both into single Django app (rejected - different purposes)
3. Use Django as backend for new dashboard (rejected - Dash already works well)

---

## [D007] Use Journal System for Implementation Tracking

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Complex multi-phase project requiring careful tracking.  
**Decision:** Create Journal folder with structured logs for progress, decisions, and blockers.  
**Consequences:**
- ✅ Clear progress tracking
- ✅ Historical record of decisions
- ✅ Easier to resume work after breaks
- ✅ Better handoff documentation
- ❌ Requires discipline to maintain

**Structure:**
- IMPLEMENTATION_PLAN.md - Master plan
- PROGRESS_TRACKER.md - Task completion tracking
- DECISION_LOG.md - This file
- ISSUES_BLOCKERS.md - Problems and resolutions
- TESTING_LOG.md - Test results and coverage

---

## [D008] Phase Execution Order

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Need to determine optimal order for implementing phases.  
**Decision:** 
1. Phase 0: Foundation
2. Phase 1: Component 3 (Web UI) - Complete UI first
3. Phase 2: Component 4 (REST API) - API after UI is functional
4. Phase 3: Integration - Import data and validate
5. Phase 4: Dashboard Client - Minimal dashboard changes
6. Phase 5: Testing - Comprehensive validation

**Rationale:**
- Complete UI first allows manual testing of backend functionality
- API can be designed based on UI needs
- Integration after both UI and API are functional
- Dashboard changes last (after backend is stable)
- Testing throughout, comprehensive at end

**Alternatives Considered:**
1. API before UI (rejected - UI helps inform API design)
2. Integration first (rejected - need UI/API to validate integration)

---

## [D009] Minimal Dashboard Changes Philosophy

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Dashboard is working production system; minimize disruption.  
**Decision:** Keep dashboard changes to absolute minimum; focus on DataOps development.  
**Consequences:**
- ✅ Reduces risk of breaking working system
- ✅ Faster development (focus on one codebase)
- ✅ Dashboard can continue operating during development
- ⚠️ Integration phase will be more critical
- ⚠️ Need good API design to avoid dashboard rewrites later

**Approach:**
- Only create thin API client layer in dashboard
- Use adapter pattern (can switch between old/new data source)
- Keep dashboard's existing data models and UI unchanged

---

## [D010] Bootstrap 5 + Crispy Forms for UI

**Date:** January 16, 2026 (pre-existing)  
**Status:** ✅ Accepted  
**Context:** Need responsive, modern UI framework for Django templates.  
**Decision:** Use Bootstrap 5 with django-crispy-forms and crispy-bootstrap5.  
**Consequences:**
- ✅ Responsive design out of the box
- ✅ Consistent styling
- ✅ Well-documented
- ✅ Crispy forms simplify form rendering
- ❌ Somewhat generic look (can customize)

**Alternatives Considered:**
1. Tailwind CSS (rejected - prefer component-based framework)
2. Material Design (rejected - heavier, more opinionated)
3. Custom CSS (rejected - too much work)

---

## [D011] Smart Append Logic for Data Collection

**Date:** December 2024 (pre-project)  
**Status:** ✅ Accepted  
**Context:** Need efficient incremental data collection without duplicates.  
**Decision:** Implement Smart Append Logic using PullStationProgress model.  
**Consequences:**
- ✅ Prevents duplicate data
- ✅ Efficient incremental pulls
- ✅ Tracks per-station progress
- ✅ Handles gaps and backfills
- ⚠️ More complex than simple date ranges
- ⚠️ Requires careful state management

**Key Features:**
- Tracks last successful pull per station
- Calculates optimal start date for next pull
- Handles errors without blocking other stations
- Supports backfill for missing data

---

## [D012] Multi-Source Support (USGS, EC, NOAA)

**Date:** December 2024 (pre-project)  
**Status:** ✅ Accepted  
**Context:** Dashboard only supports USGS; need broader coverage.  
**Decision:** Build separate client modules for each data source.  
**Consequences:**
- ✅ Broader geographic coverage
- ✅ More comprehensive dataset
- ✅ Modular design (easy to add sources)
- ❌ More code to maintain
- ⚠️ Different APIs have different capabilities

**Sources:**
1. USGS (US Geological Survey) - Primary US source
2. EC (Environment Canada) - Canadian stations
3. NOAA (National Oceanic and Atmospheric Administration) - Forecasts

---

## [D013] API Versioning Strategy

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** API will evolve; need version management.  
**Decision:** Use URL path versioning: `/api/v1/`, `/api/v2/`, etc.  
**Consequences:**
- ✅ Clear version identification
- ✅ Can maintain multiple versions simultaneously
- ✅ Explicit upgrade path
- ❌ URL changes with versions

**Alternatives Considered:**
1. Header versioning (rejected - less visible)
2. Query parameter versioning (rejected - easy to forget)
3. No versioning (rejected - future problems)

**Policy:**
- Start with v1
- Maintain previous version for 6 months after new version
- Deprecation warnings in responses

---

## [D014] SQLite for Dashboard Local Cache

**Date:** January 16, 2026  
**Status:** 💡 Proposed  
**Context:** Dashboard querying API for every request would be slow.  
**Decision:** Keep dashboard's local SQLite cache; sync from API periodically.  
**Consequences:**
- ✅ Fast queries for visualization
- ✅ Works offline/during API downtime
- ✅ Reduces API load
- ⚠️ Data may be slightly stale
- ⚠️ Need cache invalidation strategy

**Sync Strategy:**
- Real-time data: Cache for 1 hour
- Daily data: Cache for 24 hours
- Station metadata: Cache for 7 days
- Manual refresh option in UI

---

## [D015] Use SQLite for Development (All Phases)

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** psycopg2-binary failed to install due to missing PostgreSQL development libraries (pg_config). Attempting to install PostgreSQL would add complexity to local development setup.  
**Decision:** Use SQLite for all development phases (0-5). Only use PostgreSQL for production deployment.  
**Consequences:**
- ✅ Simpler local development setup
- ✅ No external database server required
- ✅ Portable database file (easy to backup/share)
- ✅ SQLite3 built into Python
- ⚠️ Must ensure Django code is PostgreSQL-compatible
- ⚠️ Need to test with PostgreSQL before production
- ⚠️ Some PostgreSQL-specific features unavailable during development
- ❌ Can't test concurrent write scenarios

**Alternatives Considered:**
1. Install PostgreSQL dev libraries (rejected - adds setup complexity)
2. Use Docker PostgreSQL (rejected - overkill for single developer)
3. Use psycopg2 (not binary) (rejected - requires compilation)

**Reference:** PHASE_0_STATUS.md

---

## [D016] Updated Package Versions for Python 3.13

**Date:** January 16, 2026  
**Status:** ✅ Accepted  
**Context:** Python 3.13.11 is newer than tested versions. Some packages in requirements.txt don't support Python 3.13 (specifically pandas 2.1.3).  
**Decision:** Upgrade the following packages to latest compatible versions:
- pandas: 2.1.3 → 2.3.3
- pytest: 7.4.3 → 9.0.2
- pytest-cov: 4.1.0 → 7.0.0
- dataretrieval: 1.0.7 → 1.1.0
- tenacity: 8.2.3 → 9.1.2

**Consequences:**
- ✅ All packages install successfully
- ✅ Python 3.13 fully supported
- ✅ Latest bug fixes and features
- ⚠️ Potential API changes (unlikely with minor versions)
- ⚠️ Need to update requirements.txt

**Alternatives Considered:**
1. Downgrade Python to 3.10-3.12 (rejected - Python 3.13 is fine)
2. Keep exact versions (rejected - won't install)

**Action:** Update requirements.txt in Phase 1 to reflect actual installed versions.

---

## Pending Decisions

### [PD01] Deployment Strategy
**Status:** 🤔 Under Consideration  
**Options:**
1. Docker Compose for both services
2. Kubernetes for production
3. Separate VMs
4. Cloud services (AWS, GCP, Azure)

**Decision Date:** TBD

---

### [PD02] Monitoring and Logging Solution
**Status:** 🤔 Under Consideration  
**Options:**
1. ELK Stack (Elasticsearch, Logstash, Kibana)
2. Grafana + Prometheus
3. Cloud-based (Datadog, New Relic)
4. Simple file logging

**Decision Date:** TBD

---

### [PD03] Backup and Disaster Recovery
**Status:** 🤔 Under Consideration  
**Options:**
1. PostgreSQL WAL archiving
2. Daily database dumps
3. Cloud backup services
4. Replicated databases

**Decision Date:** TBD

---

**Last Updated:** January 16, 2026, 1:30 PM
