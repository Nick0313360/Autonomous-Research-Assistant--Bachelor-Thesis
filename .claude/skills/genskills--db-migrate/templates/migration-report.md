## Migration Report

### Schema Change
- Description of what was changed
- Database engine and version
- Estimated rows affected

### Migration File
- path/to/migration/file
- Idempotent: YES / NO
- Reversible: YES / NO

### Safety Check
- Data loss risk: NONE / WARNING (details)
- Locking risk: NONE / WARNING (estimated lock duration)
- Disk space impact: +X MB estimated
- Backwards compatible: YES / NO (details)
- Replication impact: NONE / MONITOR (details)

### Testing
- Dry-run result: PASS / FAIL / SKIPPED
- Rollback tested: YES / NO
- Data integrity check: PASS / FAIL

### Status
- Migration applied: YES / PENDING REVIEW
- Schema valid: YES / NO
- Schema drift: NONE / DETECTED (details)

### Disaster Recovery
- Pre-migration backup: VERIFIED / NOT TAKEN
- Rollback path: AUTOMATED / MANUAL / RESTORE FROM BACKUP

### Follow-up
- [ ] Run `/genskills:test-generator` to add tests for new schema
- [ ] Update API types/interfaces to match new schema
- [ ] Update seed data if applicable
- [ ] Schedule Phase 2 (contract) migration if using expand-contract
- [ ] Monitor application error rates post-deployment
- [ ] Remove old column/table after verification period (if applicable)
