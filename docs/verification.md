# Verification record — 2026-10-05

The rewrite was developed in .rewrite and copied into the project only after staging checks passed. The original source is retained in .migration-backup/20261005-original, including the pre-existing uncommitted album-caption edit. SHA-256 manifests verified the original snapshot and all 58 installed files.

| Check | Result |
| --- | --- |
| Full suite from the installed project, Python 3.10 | **98 passed**, including real-service integration tests |
| Staging suite, Python 3.14.5 | **97 passed**, followed by a passing newly added ownership-schema rejection test |
| PostgreSQL 16.15 integration | Fresh and Tortoise-created schemas, existing data, binary identifiers, UTC timestamps, concurrent counters, ownership and no-op Alembic checks passed |
| Redis 7.0.15 integration | Existing keys, cache round trips, concurrent additions, invalidation and shutdown passed |
| SQLite legacy migration | Original Tortoise 0.20.0 fixture, earlier schema additions, row/sequence preservation, incompatible schemas and repeat upgrades passed |
| Legacy behavior comparison | All 13 result categories matched the original implementation |
| Telegram registrations | All 62 original event-handler registrations matched |
| Ruff | Passed |
| pip check | No broken requirements |
| git diff --check | Passed |

Runtime versions: Telethon 1.45.0, SQLAlchemy 2.0.54, Alembic 1.20.0. Redis remains part of the application and dependency container. No Tortoise/Aerich imports remain in runtime code.

Tests used synthetic user IDs, fake Telegram credentials, isolated databases and temporary services. Live Telegram authentication/delivery and a production deployment were not exercised. The production database and Telegram session were not modified. Integration PostgreSQL databases were uniquely named and dropped by the tests; temporary PostgreSQL/Redis services were stopped afterward.

## Backup, recovery and performance follow-up

The follow-up adds complete PostgreSQL dumps, separate data-only snapshots, a confirmed restore workflow, versioned metadata caches, expired Telegram reference renewal, and safe concurrent download limits. Existing event registrations and legacy behavior contracts remain part of the regression suite.

| Final follow-up check | Result |
| --- | --- |
| Complete Python 3.10 suite with both real PostgreSQL servers and Redis | **159 passed**, no skips, 215.07 seconds |
| Python 3.14.5 final delivery/cache/restore-handler regressions | **27 passed** |
| Python 3.14.5 analytics/cache/handler/delivery regressions before the final counter refinement | **57 passed** |
| PostgreSQL download limit concurrency | Passed on fresh and adopted Tortoise schemas; 10 requests produce exactly 3 deliveries for a limit of 3 |
| Pending-delivery backup consistency | Pending sends do not increment permanent SQL counters or enter data backups |
| Ruff / pip check / git diff --check | Passed |

Real cross-major tests use PostgreSQL **16.15 and 18.6**, with client 18 for archive reading. The 22 scenarios cover both directions for full SQL, data-only COPY, INSERT with/without column names, custom full/data-only archives, tar, SQL gzip, custom gzip, tar gzip, and the portable data snapshot. These are logical application-data restores into the current Alembic schema, preserving binary references, ownership, UTC timestamps, passwords, captions and counters. Arbitrary schema downgrades or rebuilding external database objects are outside this workflow.

Redis 7.0.15 tests run on a separate service. PostgreSQL test databases use random names and are dropped in finally blocks. Delivery and bot upload/confirmation tests use Telegram doubles. The production database and live Telegram session remain untouched. See [the recovery guide](backup-restore.md) for formats, boundaries, settings, and test configuration.
