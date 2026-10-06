# Student-card kiosk: ops backend agreement

**Status:** draft for discussion with the Backend VP; not an approved network contract.  
**Prepared:** 2026-09-16.  
**Meeting date / attendees:** to fill in.  
**Kiosk lead:** Shane. **Backend and tool leads:** to confirm.

## TL;DR — meeting overview

**The ask:** adapt ops from lending makerspace cards to registering students' own cards and activating daily access. Reuse existing account lookup, training records, visits, and authentication. The kiosk API, stored card ownership, tool authorization, and midnight cleanup all need coordinated changes.

**This is a discussion draft.** The kiosk requirements below are agreed; backend endpoints, implementation choices, and recovery policies are not. Findings describe the source reviewed on September 16, 2026, not a verified production deployment.

### What the student experience must be

- **First use:** one card presentation supplies a card UID [the card's identifier] and student number. The backend checks the account, general induction, and eligibility, then registers the card and activates access.
- **Later visits:** a UID-only tap checks eligibility again and activates access or confirms it is already active. Repeated taps never check the student out or create duplicate visits.
- **Replacement:** a verified replacement registers and activates the new card, and the old card loses access. A replaced card must not accidentally register itself again.
- **Midnight:** activation expires at midnight in Toronto; registration stays. Eligible students can reactivate immediately. Tools must reject expired access even if the cleanup job does not run.
- **Tools and refusals:** one activation works across participating tools, but each tool still checks its required training and availability. Missing accounts or induction lead to the appropriate signup/training QR. Other denials need clear backend reasons. The kiosk never reports success without backend confirmation.

Student v1 is self-service. Loan cards, returns, dispensing, founder access, occupancy counting, and entrance-door control are outside scope.

### What we need to agree with the backend team

| Discussion | Decision needed |
|---|---|
| Two logical operations | Activate by UID; register or replace using a verified student-number/UID pair and activate. Agree actual API requests, responses, denial meanings, and QR URLs. These names do not prescribe endpoints. |
| Ownership and simultaneous requests | Keep registration separate from visits; enforce one current card per student and one owner per UID. Prevent duplicate visits and conflicting replacements. Preserve old loan history during migration. |
| Complete writes and lost replies | Prefer completing registration, old-card invalidation, and activation together, or changing none of them. Define partial failures if that cannot be guaranteed. Agree durable request references and result recovery so retries or restarts cannot repeat changes. A timeout does not prove failure. |
| Revocation and conflicts | Decide how lost cards are revoked, how cross-account UID claims are handled, and who may reinstate a revoked card. |
| Tool access and expiry | Tools must prove which current card was presented; student number alone cannot reject a replaced card. Settle tool-specific training versus cumulative levels, delayed replies across midnight, and behavior during use, revocation, or outages. |
| Identity and device permissions | Agree UID format/byte order, student-number handling including leading zeros, accepted same-card evidence, and which authenticated devices may register or replace cards. Physical same-card verification remains unresolved. |
| Delivery and support | Confirm deployed code, migrations, clients, and jobs. Assign owners, dates, test access, privacy/logging rules, timing targets, support, deployment order, and rollback. |

### What counts as done

Backend tests and real integration checks must prove registration, UID-only activation, denials, replacement, duplicate/concurrent requests, lost-response recovery, restart recovery, midnight expiry, and tool enforcement. Existing kiosk tests use simulated results; they do not prove backend writes or physical reader pairing.

**Suggested order:** agree the contract → update data rules and recovery → implement the two operations → update tools and cleanup → test and deploy together. Leave the meeting with decisions recorded and an owner/date for every unresolved item; section 7 provides the worksheet.

---

The kiosk needs ops to maintain a persistent student-card registration and a separate daily activation. A student registers once, then uses a UID-only tap to activate later visits. Each interaction requires an authoritative backend decision before the kiosk displays success.

Leave the meeting with three things: a list of existing capabilities to reuse and changes to make, an agreed meaning for each operation/result, and owners and dates for the remaining work.

**Source reviewed:** the sibling `ops-backend` checkout, branch `master`, commit `046550d159dd204f345eadc636c306d172565aa9`, on 2026-09-16. Routes, services, models, migration files, jobs, and CI were inspected. This is a source review; the deployed revision, applied database migrations, running jobs, and external clients remain unverified. No backend code was changed and no backend integration tests were run. Links into ops below assume the two repositories remain siblings.

**Main finding:** ops currently implements loan-card check-in and return. Its account lookup, training records, visits, and bearer-token authentication provide a useful starting point. Persistent registration, UID-only activation, and operation recovery need changes. Tool authorization and the midnight job also need to change; adapting the kiosk routes alone would leave the old access rules in place.

The kiosk's current operation names are internal vocabulary, not approved endpoint paths or a requirement to create one endpoint per name.

## 1. Agreed kiosk baseline

These requirements come from the [project plan](plan.md#2-confirmed-requirements). Backend implementation and interface details remain to be agreed in this meeting.

- **First registration:** one student-card presentation supplies its UID and student number. Ops verifies an existing account, general induction, and current eligibility before registering and activating it.
- **Returning student:** the UID alone resolves the student. Ops rechecks current eligibility, then activates or confirms an already-active visit. Repeated taps do not check anyone out.
- **Replacement:** after identity and eligibility checks, the new UID replaces the previous one, the old card loses access, and the new card is activated in the same interaction.
- **Daily reset:** activations expire at 00:00 America/Toronto. Registration remains. An eligible student may immediately reactivate; midnight is not an opening-hours restriction.
- **Tools:** one active visit is recognised across participating tools. Each tool still requires its own training; general induction alone does not authorise every tool.
- **Refusals:** no account produces an account-signup QR; missing induction produces a training-signup QR. Neither creates a registration or activation. Other access restrictions and their reasons belong to ops.
- **Outages:** registration and activation require backend confirmation. The kiosk never grants access offline or treats a timeout as proof that a write failed.

Student v1 is fully self-service. Staff approval is not part of routine registration. Founder access, loan cards, dispensing, returns, occupancy counting, and entrance-door control are outside this agreement's scope.

## 2. What exists and what needs to change in ops

### Current API behavior

These are **existing routes at the reviewed commit**, not proposed student-card endpoints. The shared [API router](../../ops-backend/app/api/router.py) requires bearer-token authentication for all four.

| Existing route | Current behavior | Consequence for student cards |
|---|---|---|
| `POST /api/v1/kiosk/check-in` | Accepts a student number, checks for a dashboard account and an outstanding loan, then allocates an available inventory card and creates a visit. The UID is returned, not supplied. | Cannot register the student's presented UID or activate by UID alone. Repeated use is a loan conflict, not already-active confirmation. |
| `POST /api/v1/kiosk/check-out` | Accepts a UID, releases its assignment, closes the visit, and marks the card returned. | Student v1 has no return interaction. Do not call this on a repeated tap. Confirm other clients before retiring or isolating it. |
| `POST /api/v1/equipment/authorize-user` | Accepts a student number; derives the equipment from its API token. Checks the account, any active card assignment for that student, and their highest training level. | Does not verify which physical card was presented, expiry by time, or completion of a particular tool's training module. |
| `GET /api/v1/internal/current-users` | Counts students with active visits and unreleased assigned cards. | Its query depends on the lending model. Under daily activation this cannot establish physical occupancy; agree how existing consumers should interpret it. |

Sources: [kiosk routes and responses](../../ops-backend/app/api/routes/kiosk.py), [kiosk request schemas](../../ops-backend/app/schemas/kiosk.py), [equipment route](../../ops-backend/app/api/routes/equipment.py), [equipment schema](../../ops-backend/app/schemas/equipment.py), [current-users route](../../ops-backend/app/api/routes/internal.py).

### Backend change list

The classifications below are recommendations based on the checkout. Assign owners and confirm the deployed baseline in the meeting.

| ID | Existing implementation | Required change | Treatment |
|---|---|---|---|
| B1 — Eligibility | [Dashboard lookup](../../ops-backend/app/services/dashboard.py) checks account existence. [Training models](../../ops-backend/app/models/training.py) store modules and completions, but kiosk check-in does not check them. | Reuse the account lookup; identify the authoritative general-induction module/completion source and any current restrictions. Check eligibility before every activation, including already-active visits, and again before registration/replacement. Return distinct account, induction, and other denial outcomes. Seed training data is not evidence of production ingestion. | Reuse lookup/storage; add eligibility checks. |
| B2 — Registration | [RFIDCard](../../ops-backend/app/models/rfid.py) has a unique UID and inventory status. `RFIDAssignment` links a card to a **visit**, not directly to a persistent student owner. | Represent the current student–UID association independently of visits. Enforce one current card per student and one owner per UID; retain enough history to distinguish revoked/replaced cards from never-registered ones. | Modify schema and queries. |
| B3 — Activation | [check_in_user](../../ops-backend/app/services/kiosk.py) selects an `AVAILABLE` card and rejects students with an outstanding assignment. | Resolve the submitted UID, check eligibility, then confirm or create the active visit. Unknown UIDs return an identification-needed result without creating a visit. Remove inventory allocation and outstanding-loan rejection from this flow. | Replace lending behavior for student v1. |
| B4 — Registration/replacement | Existing kiosk routes commit or roll back service changes; no operation accepts a verified student-number/UID pair for registration. | Use the existing transaction pattern to register or replace the association, revoke old-card access, and activate consistently. Protect against simultaneous requests for the same student or UID. Do not compose registration and activation as two independently committed kiosk calls. | Add operation; reuse transaction pattern. |
| B5 — Daily expiry | [Visit](../../ops-backend/app/models/visit.py) has start/end/status but no expiry deadline. [invalidate_unreturned_rfid_cards](../../ops-backend/app/services/space.py) releases every active assignment, invalidates its card, and closes its visit. | Expire activation at Toronto midnight while keeping registration. Access checks must reject expired visits even when cleanup is late or absent. Any cleanup must target expired visits only, so a late run cannot revoke a fresh day's activation. | Modify visit validity and job. |
| B6 — Tool authorization | [authorize_user_for_equipment](../../ops-backend/app/services/equipment_authorization.py) checks any active assignment for a supplied student number and compares the maximum completed module level with the equipment's minimum. It does not check `equipment.status`. | Verify the presented current UID, an unexpired visit, and the agreed tool-specific training. Enforce the equipment availability flag. Keep the existing token-to-equipment binding. Coordinate the changed request with tool clients and any caches. | Modify service, schema, and tool clients. |
| B7 — Recovery | The inspected request schemas and services have no operation reference, retained outcome, safe replay, or outcome-recovery operation. | Add durable request identity and a way to recover the original result after a lost reply or restart. Repeating a reference must not repeat writes or turn yesterday's activation into today's. | Add minimal durable recovery support. |
| B8 — Revocation/conflicts | Cards have an invalidation timestamp and assignments have release reasons, all used for lending. | Define replacement/lost-card revocation, cross-account conflicts, and authorised reinstatement. Retain useful history; prevent an old UID from automatically enrolling itself again. | Extend existing status/history where suitable. |
| B9 — Integration/support | [Token validation](../../ops-backend/app/api/dependencies/auth.py) checks token validity, status, and expiry. [ApiToken](../../ops-backend/app/models/auth.py) can link to equipment. Kiosk routes have no kiosk-specific permission check. | Reuse authentication; restrict which devices can register or replace cards. Agree response/error mapping, QR URLs, credentials, and support. Provide a test environment for both kiosk and tool clients. | Reuse authentication; add action permissions and contract. |

### Schema and migration decisions

Keep the existing account, training, and visit foundations. The backend team should choose the smallest schema change that enforces these rules; this document does not require a new framework or a particular set of tables.

- **Registration lifetime and history:** `RFIDAssignment.visit_id` is mandatory today. A current registration must remain resolvable without a current visit. `RFIDCard.label` is also mandatory and unique; decide whether that inventory label remains meaningful for student cards. Preserve historical loan records instead of treating their UIDs as student registrations.
- **Concurrency:** UID uniqueness already exists. It does not enforce one current card per student or prevent duplicate active visits. The current service locks the selected inventory card, not the student's registration; `Visit.rfid_assignment` being declared `uselist=False` is not a database uniqueness constraint. Agree database constraints and transaction locking for duplicate taps, replacement races, and UID conflicts.
- **Expiry:** recommended representation is a visit expiry timestamp computed from the next `America/Toronto` midnight and stored consistently in UTC. An equivalent explicit validity rule is acceptable. Status alone must not authorise yesterday's visit. Agree whether replacement retains the existing active visit, with no duplicate activation record.
- **Identifiers:** ops request schemas, visits, training completions, and the external [DashboardUser mapping](../../ops-backend/app/models/external.py) use integer student numbers. The kiosk preserves a digit string, including leading zeros. Agree canonical identity and boundary conversion before connecting them. The dashboard owns `users`, and [Alembic excludes it](../../ops-backend/alembic/env.py); changing ops alone cannot migrate that external identity source. Also agree UID hex case, byte order, lengths, and validation across both kinds of reader.
- **Migration safety:** [enum values](../../ops-backend/app/enums.py) are persisted as [small integers](../../ops-backend/app/db/types.py). Do not renumber or reinterpret existing statuses without an explicit data migration. Add a forward migration from the confirmed deployed revision, with a plan for old records, outstanding visits, and rollback; do not rewrite previously applied migrations.

### Shared callers and policy mismatches to resolve

**Tool training needs a decision.** The current maximum-level check can accept training for tool A as sufficient for tool B with the same or lower threshold. That meets the kiosk requirement only if the training programme explicitly makes those levels cumulative across all affected tools. Otherwise the backend needs required-module checks for each tool. The earlier `equipment_training_requirements` table was removed by [migration 05ceecc28fe2](../../ops-backend/alembic/versions/05ceecc28fe2_remove_equipment_training_requirements.py); it is not an existing feature to simply call. Agree the policy before deciding whether to restore a mapping in a new migration.

**Tool requests must identify the credential being used.** A student-number-only request cannot distinguish the student's current card from their replaced card once that student has an active visit. Prefer submitting the scanned UID and resolving its owner in ops. If tools use another proof, define how ops verifies that it identifies the current, non-revoked credential. Changing only the kiosk's registration records will not enforce old-card rejection through the present tool API.

**Update the whole lending path together:** kiosk routes/services/schemas; equipment authorization; `space.get_current_user_count`; `space.invalidate_unreturned_rfid_cards` and its [runner](../../ops-backend/scripts/invalidate_missing_rfid_cards.py); and [seed fixtures](../../ops-backend/scripts/seed_phase1.py). Confirm which routes, jobs, and clients are actually deployed before cutover. The invalidation service says it is intended for midnight cron; the checkout does not establish the production schedule or timezone. Occupancy remains outside the kiosk scope, but existing count consumers still need a compatibility decision.

The ops [requirements](../../ops-backend/docs/requirements.md) and [schema document](../../ops-backend/docs/schema.md) retain lending and per-tool-module descriptions that differ from current code. Update them with the agreed implementation so future integration does not rely on removed behavior.

## 3. The two logical operations the kiosk needs

Actual routes, methods, authentication, payloads, and versioning are **to agree**. A future kiosk adapter [code translating between ops and the core] can map the agreed interface to the following internal operations.

### A. Activate a registered UID — currently `ActivateUid`

**Core input:** card UID. The production request also needs the agreed authenticated kiosk identity and operation reference.

1. Resolve the card's current registration and status.
2. Check the holder's current account, general induction, and eligibility.
3. Confirm an already-active eligible visit or create the required activation.
4. Return a definitive outcome. An unregistered card takes the identification route without a write to registration or activation.

This operation must not require a student number. A student with an active visit still undergoes the current eligibility check before receiving “already active.”

### B. Register or replace a card and activate — currently `RegisterAndActivate`

**Core input:** student number and UID from a verified same-card presentation, plus the agreed request identity/reference.

1. Resolve the existing student account; check general induction and current eligibility again at this operation.
2. Check UID ownership and revocation status, including changes since the earlier UID lookup.
3. Create the association or replace the student's old UID. Replacement invalidates old-card access.
4. Confirm activation and the completed association change together.

The backend decides whether this is first registration, an already-correct association, replacement, or a conflict. An unknown student must sign up and present the card again; this operation does not silently provision an account.

**Proposed consistency guarantee:** complete the required association, invalidation, and activation changes together, or leave domain state unchanged. If existing systems cannot provide that guarantee, explicitly define partial completion and recovery before integration. “Card registered, activation failed” cannot be reported as full success or as a clean no-change denial.

### Current core outcome mapping

These are provisional internal names. Ops can use its established naming if the meanings can be mapped without losing information.

| Core outcome | Operation | Meaning required by the kiosk |
|---|---|---|
| `ACTIVATED` | UID activation | Current eligibility was checked and activation is confirmed. |
| `ALREADY_ACTIVE` | UID activation | Current eligibility was checked and an existing active visit is confirmed; no duplicate visit. |
| `UNREGISTERED` | UID activation | Identification is needed; no registration or activation was changed. This does not mean the student lacks an account. |
| `REGISTERED_AND_ACTIVE` | Registration | The requested card association and activation are both confirmed. |
| `REPLACED_AND_ACTIVE` | Registration | The new association and activation are confirmed, and the old UID has lost access. |
| `UNKNOWN_STUDENT` | Either, where applicable | No account can be resolved; show the account-signup QR. No access/registration changes. |
| `MISSING_INDUCTION` | Either | Required general induction is missing; show the training-signup QR. No access/registration changes. |
| `DENIED` | Either | Another backend-owned restriction prevents the operation; return an agreed reason code. No access/registration changes. |
| `UID_CONFLICT` | Either, where applicable | Ownership cannot be accepted under the agreed policy; no access/registration changes. Resolution policy remains open. |

“No changes” here refers to registrations, revocations, and visits; it does not prohibit recording an audit event. Partial writes must be represented separately from these no-change outcomes.

A repeated registration request must still establish both the correct association and activation. The current core does not accept a bare `ALREADY_ACTIVE` as registration success. Agree how ops represents that case, including when two kiosks race to register the same card.

`READ_AGAIN` and `SESSION_EXPIRED` are local kiosk feedback, not backend responses. The core's `BackendError` distinguishes a request definitely **not sent** from an **unknown outcome**; a network timeout normally cannot establish the former.

### Mapping the existing API to the new contract

| Existing response | Migration guidance |
|---|---|
| `DASHBOARD_ACCOUNT_NOT_FOUND` | Can map to `UNKNOWN_STUDENT` if the dashboard account remains the agreed account source. Preserve the distinction from a failed lookup. |
| `OUTSTANDING_RFID_CARD` | Do not rename it to `ALREADY_ACTIVE`. The existing check proves an outstanding loan, not current induction/eligibility or today's activation. |
| `NO_AVAILABLE_RFID_CARD` and checkout/return errors | Lending-specific results have no routine student-registration meaning. In particular, checkout's `RFID_CARD_NOT_FOUND` is not an implemented UID activation decision. |
| `INSUFFICIENT_TRAINING_LEVEL` | This belongs to the equipment flow. It cannot stand in for `MISSING_INDUCTION` without an explicit general-induction check. |
| `INVALID_API_TOKEN` / `DASHBOARD_LOOKUP_UNAVAILABLE` | Device authentication and service failures are not student signup decisions. Agree an explicit technical-failure mapping and whether the response guarantees no domain write. Never infer rollback from an HTTP status alone. |

The equipment route already maps dashboard lookup failure to a structured `503 DASHBOARD_LOOKUP_UNAVAILABLE`; the kiosk route currently rolls back and rethrows it without that mapping. Reuse the established error shape when defining the revised kiosk API. A request rejected by ops was still sent: the adapter must not label it `NOT_SENT`. The core may need an additional confirmed-no-write technical outcome once that contract is agreed.

## 4. Decisions that need explicit agreement

### Write completion, retries, and restart recovery

Consider this failure: ops commits a replacement, but the response never reaches the kiosk. The old card may already be invalidated. Repeating the request blindly or telling the student that nothing happened would be wrong.

**Recommended approach for discussion:** give each logical request a reference that remains unique across kiosks and restarts; support safe repetition with that reference and a way to obtain its authoritative outcome. Agree the reference lifetime, retention period, and behavior when the same reference is submitted with different data. Replaying an old activation after midnight must not silently create a new day's visit; a fresh tap is a new operation.

Retain the outcome consistently with the domain write so a committed change cannot lose its recovery record. Distinguish a completed result, an operation still in progress, and an absent record whose meaning depends on the agreed retention/retry rules. The existing `/health` and `/health/db` endpoints establish process/database reachability only; neither resolves an earlier operation.

The current core stops new interactions in `OUTCOME_UNKNOWN` until the original operation is resolved. A delayed definitive result can release that hold without showing the previous student's result or continuing their registration. If the reply never arrives, a recovery mechanism is still needed. Reconnection and process restart are not proof of rollback [undoing a write]. The core's in-memory `(session_id, op)` reference is not a production idempotency scheme.

### Replacement, revocation, and simultaneous requests

- **Old-card re-enrollment:** if a replaced UID is treated as an ordinary unregistered card, its still-readable student number could enroll it again. Recommended: retain enough revocation/replacement history to reject that route, and agree any authorised reinstatement process. The exact policy is open; the old card must not regain access accidentally.
- **Cross-account claim:** automatic replacement of one's own card does not settle a UID already associated with another account. Agree the denial, support path, and who can resolve it. Do not use a generic replacement response to conceal a transfer.
- **Concurrent changes:** agree the outcome when two kiosks register different UIDs for one student, when eligibility changes during an interaction, or when an old UID activates while replacement is committing. A stale request must not undo a newer replacement.
- **Lost card before replacement:** decide who can revoke it immediately, how that reaches tools, and whether existing backend support can be reused. Routine enrollment remains self-service.

### Midnight and tool enforcement

Expiry follows the next local midnight in `America/Toronto`, not a fixed duration of 24 hours after activation. Registration survives. The backend/tool team owns enforcement and daylight-saving behavior. Authorization must check this validity directly; a cleanup job can close expired records later. The current invalidation job targets all active assignments, so merely rescheduling it in the correct timezone would not fix its semantics or the risk from a late run.

Agree how to handle a response delayed across midnight: the current core consumes outcome codes, not an expiry timestamp, so the adapter/core may need an agreed change to avoid presenting an expired activation as current. Also agree what tools do at midnight or after revocation while equipment is already in use. Tool shutdown behavior and tool offline behavior are separate decisions; the kiosk's offline refusal does not define those policies.

### Identity, permissions, and operational details

- Agree UID representation, byte order across kiosk/tool readers, student-number validation, and maximum lengths. The core preserves leading zeros and uses uppercase hexadecimal UIDs. Nine-digit student numbers were observed on the tested card; that is not yet a universal format specification.
- Define what same-card evidence ops accepts from an authenticated kiosk. `IdentityConfirmed` currently represents a trusted controller assertion; the physical assurance mechanism remains unverified. Backend agreement does not close that hardware acceptance gap.
- Agree the kiosk's authentication and allowed actions, credential provisioning/rotation/revocation, and test credentials. Student identifiers are request data, not credentials for authenticating the kiosk.
- Provide stable denial reasons and the account/training signup URLs. Agree which details display 1 may show. Display 2 receives general instructions and system status without student-specific information.
- Agree request time limits, availability expectations, diagnostic records, retention, and a support contact. Avoid real student identifiers in committed examples or fixtures. Choose measurable timing targets in the meeting rather than copying the diagnostic reader script's pauses.

## 5. Integration acceptance checks

These checks must run against the actual backend/test environment and, where stated, participating tools. Existing pure-core tests use synthetic backend results and do not prove remote writes or enforcement. No tracked backend test files were found in the reviewed checkout; its [CI workflow](../../ops-backend/.github/workflows/lint-format.yml) runs Ruff lint/format checks, not behavior tests. Add backend tests for the changes and run them in CI. Exercise transactions, uniqueness, and concurrent requests against MariaDB, rather than relying only on mocked responses.

| Check | Evidence needed |
|---|---|
| Eligible first registration | The submitted student resolves to an account; one current association and an active visit are confirmed. |
| Returning UID-only tap | A registered UID works without a student-number read and checks current eligibility. |
| Repeated taps and concurrent duplicates | Eligible active students receive confirmation; requests do not create duplicate visits or repeat association changes. |
| Unknown student / missing induction / other denial | Correct outcome and reason mapping; no registration, revocation, or activation change from the denied attempt. |
| Eligibility changes after an earlier success | Already-active confirmation and a later registration attempt recheck eligibility. A previous successful account/induction lookup is not blanket approval. |
| Successful and denied replacement | Successful replacement activates the new UID and invalidates the old across tools. A denied replacement preserves the prior association under the agreed no-change guarantee. |
| Replaced/revoked UID presented again | The old card cannot regain access through either UID activation or automatic re-enrollment. |
| Conflicting or concurrent registration | Agreed conflict/winner behavior; no unintended cross-account transfer or simultaneously current replacement cards. |
| Commit succeeds, response is lost | The original outcome is recoverable; the kiosk never guesses success or rollback; a permitted retry does not repeat changes. |
| Mid-operation failure / conflicting request reference | Association, revocation, visit, and retained-result writes remain consistent. Reusing a reference with different data is rejected without new changes. |
| Kiosk restart during an operation | Operation references and recovery follow the agreed crash policy; startup health alone does not discard an unresolved write. |
| Midnight, daylight-saving changes, and delayed replies | Activation expires at the correct local midnight while registration persists. Fresh reactivation works; replaying an old operation does not create a new visit. |
| Missed or late cleanup | Tools refuse an expired visit without waiting for the job. A late job leaves a new day's activation and permanent registration intact. |
| Shared visit, different tool training | One activation is recognised across tools, while a tool denies a student lacking its specific training. |
| Actual card and equipment validity | A replaced UID is refused even while its holder has a new active card. Equipment marked unavailable is refused. Test through the agreed tool request, not only a student-number lookup. |
| Identifier representation | Agreed UID byte order/case and student-number normalization resolve the same person/card across kiosk, dashboard, and tools; malformed identifiers are rejected. |
| Authentication and outages | Invalid tokens and devices without registration permission are refused. Lookup unavailability is distinct from a missing account. Backend unavailability produces no kiosk success or offline activation. Tool outage behavior matches its separately agreed policy. |
| Legacy migration and client compatibility | Existing loan history stays identifiable, student registration does not inherit loan ownership, and old routes/jobs/clients follow the agreed cutover plan. |

Reader trials must separately establish same-card pairing and interruption handling before accepting production registration.

## 6. Suggested backend work order

1. **Settle the contract:** confirm account/induction sources, tool training policy, UID input, identifier formats, outcomes, permissions, and recovery guarantees. Confirm the actual deployed revision and callers.
2. **Implement the data rules:** persistent registration and revocation history, visit validity, concurrency constraints, and durable operation outcomes. Prepare forward migrations and synthetic fixtures.
3. **Implement the two operations:** reuse the account lookup and transaction pattern; cover successful, denied, repeated, conflicting, and interrupted writes with backend tests. Publish the agreed request/response examples for the kiosk adapter.
4. **Update all access consumers:** change tool authorization, expiry cleanup, and affected count queries; coordinate tool clients and legacy route/job retirement. Verify replacement and midnight behavior end to end.
5. **Integrate and cut over:** run the acceptance checks with the kiosk adapter and real readers in the test environment, update ops docs/CI, and agree deployment order and rollback. Same-card hardware assurance remains a separate acceptance requirement.

These are proposed work packages, not assigned tasks or permission to change ops implementation. The Backend VP should assign backend/tool owners; Shane owns the kiosk integration.

## 7. Meeting worksheet

**Suggested 30-minute agenda:** 5 minutes on scope and existing capabilities; 10 on operations, data changes, and outcome meanings; 10 on replacement/recovery/tool behavior; 5 on owners, dates, and the integration test environment. Extend or assign follow-ups for decisions that cannot be settled in the meeting.

| Decision / deliverable | Agreed answer or follow-up | Owner | Due |
|---|---|---|---|
| Confirm deployed revision, applied migrations, live clients/jobs; approve B1–B9 scope | To fill in | To assign | To agree |
| Actual operations, routes/methods, request/response fields, versioning | To fill in | To assign | To agree |
| Authentication, kiosk permissions, and test credentials | To fill in | To assign | To agree |
| Eligibility source and denial/QR mapping | To fill in | To assign | To agree |
| General-induction module and production training ingestion | To fill in | To assign | To agree |
| Tool-specific modules versus cumulative levels; current-UID proof at tools | To fill in | To assign | To agree |
| Registration/visit schema, uniqueness, and forward migration | To fill in | To assign | To agree |
| Complete-write guarantee and partial-failure representation | To fill in | To assign | To agree |
| Operation reference, safe retries, lost-response and restart recovery | To fill in | To assign | To agree |
| UID conflicts, replaced-card re-enrollment, and lost-card revocation | To fill in | To assign | To agree |
| Existing active visit during replacement or eligibility change | To fill in | To assign | To agree |
| Midnight/delayed-response semantics and tool invalidation behavior | To fill in | To assign | To agree |
| Accepted identity evidence and identifier formats | To fill in | To assign | To agree |
| Privacy/log retention, timing targets, and support contact | To fill in | To assign | To agree |
| Test environment, backend tests/CI, and acceptance owners | To fill in | To assign | To agree |
| Legacy loan data, count consumers, client/job cutover, and rollback | To fill in | To assign | To agree |

**Useful material for the VP to bring:** deployed commit and migration revision; actual job schedule/timezone; the tool-client request flow and cache behavior; production account/training sources; and owners for implementation, test access, and deployment. The source paths above provide the code baseline. Use synthetic accounts for shared examples.

**Meeting completion:** mark each item as agreed or give it an owner and follow-up date. After the backend decisions are recorded, update the kiosk adapter/core mapping where needed. Production registration still requires the hardware assurance and integration evidence described above.

## References

- [Requirements, acceptance criteria, and current core design](plan.md)
- [Open project decisions](../TODO.md)
- [Domain terminology](../CONTEXT.md)
- [Student-card scope decision](adr/0005-student-card-registration-and-daily-activation.md)
- [Current internal events and outcomes](../kiosk/events.py)
- [Current transition behavior](../kiosk/machine.py)
