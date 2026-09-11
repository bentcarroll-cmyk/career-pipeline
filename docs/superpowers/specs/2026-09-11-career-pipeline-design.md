# Career Pipeline — Product and Architecture Design

**Date:** September 11, 2026  
**Status:** Approved
**Plugin name:** `career-pipeline`

## 1. Product objective

Career Pipeline is a private-beta Codex Desktop plugin for experienced knowledge-work professionals pursuing business, operations, product, strategy, technology, and leadership roles.

It gives each user a local-first job-search operating system that:

- conducts a guided career and ambitions interview;
- turns the user's resume and interview into an approved career profile;
- discovers and evaluates current job opportunities on a user-selected schedule;
- creates a searchable local backlog of qualifying roles under stable `JOB-000123` identifiers;
- prepares verified application packets immediately when the user requests them;
- keeps final application PDFs easy to browse in a local `Applications/` folder;
- optionally exports selected records or packets to user-connected destinations; and
- optionally reconciles application status from the user's email and calendar.

Career Pipeline does not operate a developer-owned service, collect telemetry, retain user data centrally, submit applications, send messages, or contact employers.

## 2. Product boundaries

### Included in version one

- Codex Desktop plugin installation and conversational onboarding
- User-approved local workspace as the sole system of record
- One canonical folder per qualifying job with stable local IDs
- Regenerable JSON indexes for fast backlog and duplicate lookup
- Optional LinkedIn, Indeed, Firecrawl, browser, Notion, GitHub, Gmail, Google Calendar, Google Drive, USAJOBS, and Linear connections
- Resume import and career interview
- Approved local career profile, search criteria, and writing preferences
- Scheduled job discovery with user-configurable cadence and timezone
- Automatic local record creation for Strong Match and Worth Considering roles
- Conversational backlog review
- Immediate, user-triggered resume and optional cover-letter creation
- Local packet delivery and optional user-requested export
- Optional weekday application-status reconciliation
- Resumable workflows, backed-up migrations, validation, and synthetic test fixtures

### Excluded from version one

- A hosted Career Pipeline service or shared database
- SQLite or another database dependency
- Product telemetry or analytics
- Automatic job applications
- Employer or recruiter outreach
- A custom graphical onboarding interface
- A required project-management connector
- Automatic background mirroring to Linear or another external backlog
- A scheduled application-packet creation automation
- File, label, or external-status changes acting as background wake-up events

## 3. Privacy and ownership model

The plugin contains reusable instructions, templates, validation scripts, schemas, and synthetic examples only. It must contain no personal data from the original Career workspace.

Each user's private data lives in a local workspace selected or created during onboarding. Optional connector content may be processed by Codex and the relevant third-party service. Onboarding must explain this accurately. “No Career Pipeline data collection” means the plugin author operates no collection service and receives no automatic copy of connector content, local files, run records, or feedback.

The plugin must not include telemetry, analytics SDKs, developer-controlled credentials, remote logging, or hidden network destinations. Beta feedback is voluntary and manually shared by the user.

## 4. Plugin architecture

Career Pipeline contains four user-facing skills plus supporting templates and deterministic local tools.

### 4.1 Onboard

Purpose: create and validate a private Career Pipeline workspace through a resumable conversation.

Responsibilities:

- explain privacy and connector choices;
- create the local workspace and canonical folder store;
- offer and test every connector individually;
- preserve the source resume unchanged;
- conduct the career and ambitions interview;
- generate the career profile, search criteria, and writing preferences;
- collect packet and schedule defaults;
- run a local readiness test; and
- create the selected automations only after explicit user approval.

### 4.2 Discover jobs

Purpose: find, verify, assess, deduplicate, and record qualifying current opportunities.

This skill is invoked by the scheduled discovery automation and may also be run manually. It uses the approved profile, source-specific checkpoints, canonical job folders, and regenerable indexes. Every new Strong Match or Worth Considering role is written locally after an immediate duplicate check and record readback.

### 4.3 Review backlog

Purpose: help the user compare and manage the already-reviewed local backlog.

It can summarize new roles, compare selected job IDs, record not-pursuing decisions, surface deadlines, and accept one or more job IDs for application-packet creation. It reads canonical job folders, may regenerate stale indexes, and does not submit applications.

### 4.4 Prepare application

Purpose: immediately create and deliver a tailored application packet for one or more explicitly selected local job IDs.

It is user-triggered, not scheduled. A local status such as `prepare_application` records durable state, but editing a file manually does not wake Codex. The expected trigger is a request such as “Prepare an application packet for JOB-000123.”

## 5. Local workspace and canonical records

Onboarding creates the following structure beneath a user-approved root:

```text
Career/
├── Profile/
│   ├── Career_Profile.md
│   ├── Search_Criteria.md
│   └── Writing_Preferences.md
├── Sources/
│   ├── Resume_Original.<ext>
│   └── connector-source-notes/
├── Jobs/
│   └── JOB-000123/
│       ├── job.json
│       ├── posting.md
│       ├── assessment.md
│       ├── events.jsonl
│       └── working/
├── Applications/
│   └── JOB-000123_Company_Role/
│       └── v001/
│           ├── Resume_Company_Role.pdf
│           ├── Cover_Letter_Company_Role.pdf
│           └── working/
├── Indexes/
│   ├── backlog.json
│   └── deduplication.json
├── Runs/
│   ├── discovery/
│   └── lifecycle/
└── State/
    ├── config.json
    ├── next-job-id.json
    ├── discovery-state.json
    ├── application-manifest.json
    └── onboarding-state.json
```

The `Jobs/JOB-000123/` folder is the canonical record for that opportunity:

- `job.json` is the validated current snapshot, including status and relative artifact paths;
- `posting.md` preserves the normalized posting evidence and source receipt;
- `assessment.md` preserves the evidence-backed evaluation;
- `events.jsonl` is an append-only history of material state changes; and
- `working/` contains private source snapshots and verification evidence.

`Indexes/*.json` are disposable materialized views. They can always be regenerated from canonical job folders and must never override them. Missing, corrupt, or stale indexes trigger regeneration rather than data loss.

Final employer-facing PDFs sit directly in each application version folder for easy access. Private drafts, extracted text, render images, and review evidence live in that version's `working/` folder. Historical versions are never overwritten.

All persisted paths are generated during onboarding. Reusable plugin instructions use configuration values and relative paths rather than a developer's username or fixed filesystem layout.

## 6. Local consistency model

All mutations use a short-lived workspace lock under `State/`.

Creating a job record:

1. acquires the workspace lock;
2. rebuilds or validates the duplicate baseline from canonical folders;
3. repeats the duplicate check;
4. atomically increments `next-job-id.json`;
5. writes a complete temporary job folder;
6. fsyncs and renames the folder to its final `JOB-000123` name;
7. reads and validates the canonical record;
8. regenerates affected indexes atomically; and
9. releases the lock.

Status changes atomically rewrite `job.json` and append a compact event to `events.jsonl` while holding the lock. If a run is interrupted, canonical folders remain authoritative and index repair is safe.

Job IDs are never reused. Deleting or archiving a job is represented by status and events, not by renaming or removing the canonical folder.

## 7. Onboarding flow

Onboarding begins when the user says “Set up my job search” and proceeds in resumable stages.

1. **Privacy explanation:** explain the local-first model, connector processing, and absence of developer-operated collection.
2. **Workspace:** ask the user to approve a local root, create the standard structure, and verify write/lock access.
3. **Connector choices:** present every connector separately with its benefit, intended reads and writes, connect/skip choices, and fallback behavior. Save and respect each decision.
4. **Resume intake:** copy the original resume into `Sources/` without modifying it and extract a draft chronology and evidence inventory.
5. **Career interview:** gather accomplishments, contribution, scope, career transitions, strengths, ambitions, target work, compensation, geography, work model, travel, timing, constraints, and uncertain claims.
6. **Profile generation:** create `Career_Profile.md`, `Search_Criteria.md`, and `Writing_Preferences.md` for explicit correction and approval.
7. **Packet defaults:** default to a two-page tailored resume and one-page cover letter. Allow the cover letter to be disabled globally or per role.
8. **Schedule:** offer twice each weekday in the user's timezone as the discovery default, plus daily, weekly, or custom alternatives. Offer one weekday application-status reconciliation check when Gmail or Calendar is enabled.
9. **Readiness test:** verify local files, canonical store operations, index regeneration, configured source capabilities, and schedule settings.
10. **Activation:** keep discovery disabled until the user explicitly approves the profile and search criteria.

Progress is persisted after every completed stage. Resume-only defaults cannot activate discovery before profile approval. No connector is required for activation when at least one usable public discovery lane exists.

## 8. Connector design

Every connector is individually optional. Declining one removes its benefit but does not invalidate the local system of record.

| Connection | Benefit | Default access | Fallback when declined or unavailable |
| --- | --- | --- | --- |
| Indeed | Broad job discovery and company context | Job search and company lookup | Public search, employer boards, and ATS sources |
| LinkedIn | Job discovery when the installed capability supports it; otherwise people, company, and networking context | Capability-tested during onboarding | No LinkedIn coverage; never claim it was searched |
| Firecrawl | Web discovery, structured extraction, and difficult-page coverage | Search and page extraction | Native web search and browser tools |
| Browser | Authenticated job boards, JavaScript-heavy pages, and application-path verification | User-controlled browser sessions | Publicly accessible sources only |
| Notion | Career history, goals, notes, and accomplishment context | Read-only enrichment | Resume and interview remain sufficient |
| GitHub | Evidence of projects, technical scope, and public work | Read-only enrichment | No repository-derived evidence |
| Gmail | Application confirmations, rejections, interviews, and recruiter updates | Read only job-related messages; reconciliation writes derived status locally | Application stages remain manual |
| Google Calendar | Interview and deadline context; optional event creation | Read-only by default; create only after an explicit request | No calendar assistance |
| Google Drive | Resume import and optional user-requested backup | Read-only by default | Local files remain canonical |
| USAJOBS | Structured federal-role discovery | Search using the user's securely connected API key | Federal API lane disabled |
| Linear | User-requested export of selected job summaries or final packets | No background sync; write only after explicit export request | Local folders remain fully functional and authoritative |

Onboarding records actual available actions, not merely whether a connector is installed. LinkedIn people search must not be represented as LinkedIn job-search coverage.

Public Greenhouse, Lever, and Ashby adapters are built-in sources rather than personal connectors. Other public ATS adapters may be added behind the same normalized job-source interface.

Linear is never used for ID allocation, deduplication, backlog queries, workflow state, readiness, lifecycle state, or automatic packet delivery. Export failures do not roll back or invalidate a verified local record.

## 9. Canonical job record

`job.json` records:

- schema version and stable local job ID;
- employer and exact title;
- location, workplace model, and travel expectations;
- compensation evidence;
- original posting and application URLs;
- ATS or requisition identity;
- source and verification timestamp;
- Strong Match or Worth Considering disposition;
- current local lifecycle status;
- role-to-profile fit;
- evidence-supported strengths;
- missing qualifications and uncertainties;
- deadline when present;
- recommended next action;
- discovery and re-verification dates;
- relative path to each delivered application version; and
- optional export receipts that never become authoritative.

Qualifying records use statuses including `new`, `needs_confirmation`, `prepare_application`, `packet_ready`, `applied`, `interviewing`, `offer`, `not_pursuing`, and `closed`.

Clear non-matches remain in local run evidence and do not receive canonical job IDs.

## 10. Job-discovery workflow

Each discovery run:

1. reads the approved profile, criteria, configuration, prior source state, and local canonical store;
2. validates or rebuilds duplicate and backlog indexes;
3. searches enabled broad sources and user-prioritized company boards;
4. uses public ATS adapters where available;
5. normalizes each posting into a common candidate schema;
6. verifies the original posting and application path where possible;
7. evaluates responsibilities before relying on title alone;
8. records fit, gaps, compensation, geography, recency, and uncertainty;
9. deduplicates primarily by employer plus ATS/requisition ID and otherwise by a conservative company/title/location/team fingerprint;
10. enters the workspace lock and repeats the duplicate check against canonical folders;
11. atomically creates every qualifying new job folder;
12. reads each created `job.json` back before recording success;
13. atomically updates indexes, source checkpoints, and the stable review batch; and
14. reports new matches, meaningful changes, or actionable source failures.

Failed or partial source checks do not advance that source's last-successful timestamp, seen-record set, or rotation cursor. The run stays quiet when there is no new or materially changed actionable result.

## 11. Immediate application-packet workflow

When a user explicitly selects one or more local job IDs, Career Pipeline:

1. resolves each exact canonical job folder and records `prepare_application` only from a pre-application state, preserving later or terminal lifecycle states;
2. begins work immediately in the same conversation;
3. re-verifies the job posting and actual application destination;
4. reads the current career profile, writing preferences, and role-specific instructions;
5. derives the employer's central hiring outcomes;
6. compares candidate accomplishments by relevance, impact, contribution, scope, distinctiveness, recency, factual support, and rendered space;
7. creates a two-page tailored resume and, by default, a one-page cover letter;
8. runs factual, chronology, tailoring, ATS-structure, page-space, PDF text, page-count, and visual checks;
9. saves the final PDFs and private working evidence in the versioned local application folder;
10. records exact final hashes and relative paths in the application manifest and canonical job record;
11. reads the files and updated record back;
12. sets local status `packet_ready` from a pre-application state, or preserves a later lifecycle status while recording the delivered application version; and
13. clears `prepare_application` only after local delivery is verified.

The default design is clean, text-focused, and ATS-friendly. Workday-specific or other ATS-specific structural rules apply only after verifying the actual destination. Application packet creation never submits the application.

If the user explicitly requests export to Linear or another connected destination, perform it only after local delivery succeeds, store a compact export receipt, and never make local readiness depend on export success.

If processing is interrupted, the application manifest records the latest verified stage. A later “Resume my packet queue” request continues without duplicating files, events, exports, or application versions.

## 12. Application-status reconciliation

Users who enable Gmail or Google Calendar may opt into one weekday reconciliation check in their timezone.

The workflow may update the local canonical job status automatically only from unambiguous evidence, such as a clearly identified application confirmation, rejection, interview invitation, or offer tied to an exact local job ID. Ambiguous, contradictory, or employer-generic messages are flagged for user review.

The workflow does not send email, respond to invitations, create calendar events, or contact another person without an explicit user request. It preserves minimal source receipts locally without copying complete mailbox or calendar contents.

## 13. Reliability and safety

- Persist onboarding progress after every completed stage.
- Store configuration, job snapshots, indexes, and manifests atomically.
- Use a short-lived workspace lock for ID allocation and canonical mutations.
- Treat job folders as authoritative and indexes as disposable.
- Track source success independently.
- Use stable requisition identities and conservative fallback fingerprints.
- Recheck duplicates under the workspace lock immediately before job creation.
- Read back canonical files and optional export writes.
- Record final artifact hashes and review decisions.
- Preserve original source resumes and every delivered version.
- Never infer application submission from packet preparation.
- Never allow an old resume to override a later explicit user correction.
- Remember connector declines and permission limits.
- Ask for confirmation before migrations and back up user state first.
- Avoid duplicate alerts for unchanged failures.
- Never submit applications or send employer-facing communications.

## 14. Testing strategy

The plugin test suite uses synthetic candidates, employers, postings, resumes, messages, connector records, and local job folders.

Required scenarios:

- complete onboarding;
- interrupted and resumed onboarding;
- every optional connector accepted and declined;
- installed connectors missing expected actions;
- activation with no personal connector enabled;
- profile correction and approval gating;
- canonical folder creation and readback;
- stable, never-reused job ID allocation;
- concurrent or interrupted allocation under the workspace lock;
- index deletion, corruption, staleness, and regeneration;
- public ATS extraction for Greenhouse, Lever, and Ashby;
- duplicate roles across ATS, Indeed, public search, and canonical folders;
- closed, reposted, and changed requisitions;
- Strong Match and Worth Considering local creation;
- clear non-match exclusion from canonical job folders;
- interrupted discovery with per-source checkpoints;
- immediate single-role and multi-role packet creation;
- interrupted packet generation and local delivery resumption;
- factual, chronology, tailoring, page-space, PDF, visual, and ATS checks;
- Gmail status updates with clear, ambiguous, and contradictory evidence;
- optional export success, failure, and readback without authority inversion;
- upgrade and migration safety; and
- automated scans for developer names, personal identifiers, fixed paths, private URLs, credentials, and original Career workspace data.

## 15. Private-beta distribution

Career Pipeline source lives in a private repository separate from the original Career workspace. The repository contains the plugin, synthetic fixtures, documentation, tests, version metadata, and changelog.

Beta users receive a Codex plugin installation or share link. After installation, they start a new conversation with “Set up my job search.”

Releases are versioned. Plugin updates do not overwrite user data. Schema changes use explicit, backed-up migrations. Indexes may be rebuilt without migration because they are derived. The first beta targets three to five users, with manually shared feedback and no automatic logs.

## 16. Beta success criteria

Version one is ready to expand beyond the private beta when:

- a nontechnical Codex Desktop user can install the plugin and complete onboarding without editing files;
- the user can skip every connector and receives a clear explanation of the lost benefit and fallback;
- activation cannot occur before local workspace and profile readiness pass;
- scheduled discovery creates a useful, deduplicated local backlog;
- source limitations and failures are reported accurately;
- the user can request one or several application packets conversationally by local job ID;
- verified final PDFs appear in the local `Applications/` folder;
- canonical job folders remain inspectable, portable, and recoverable without special database software;
- deleted or corrupt indexes regenerate without changing canonical records;
- interrupted workflows resume without duplicate IDs, folders, events, or artifacts;
- application status changes only from clear evidence or explicit user direction;
- optional export failure never damages or blocks local state;
- no test or package scan finds personal data from the original Career workspace; and
- beta users can update the plugin without losing local job or application history.

## 17. Implementation sequencing

Implementation proceeds in four separately verifiable increments:

1. **Plugin shell and onboarding:** manifest, workspace templates, canonical job-store schema, ID allocator, indexes, resume intake, career interview, profile approval, connector capability matrix, and local readiness test.
2. **Discovery and backlog:** normalized source interface, public ATS adapters, enabled connector lanes, evaluation, deduplication, canonical folder creation, state, indexes, reporting, and local backlog review.
3. **Immediate application packets:** explicit local job-ID trigger, manifest, document generation, quality gates, local versioning, canonical status updates, and resumption.
4. **Lifecycle and beta hardening:** Gmail/Calendar reconciliation into local state, optional user-requested exports, upgrade safety, synthetic end-to-end fixtures, privacy scans, packaging, and beta release documentation.

Each increment works with every connector declined and does not introduce a database or developer-controlled data service.
