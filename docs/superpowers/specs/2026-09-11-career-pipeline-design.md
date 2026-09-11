# Career Pipeline — Product and Architecture Design

**Date:** September 11, 2026  
**Status:** Approved conversational design; awaiting written-spec review  
**Plugin name:** `career-pipeline`

## 1. Product objective

Career Pipeline is a private-beta Codex Desktop plugin for experienced knowledge-work professionals pursuing business, operations, product, strategy, technology, and leadership roles.

It gives each user a local-first job-search operating system that:

- conducts a guided career and ambitions interview;
- turns the user's resume and interview into an approved career profile;
- discovers and evaluates current job opportunities on a user-selected schedule;
- automatically creates a searchable backlog of qualifying roles in the user's own Linear workspace;
- prepares verified application packets immediately when the user requests them;
- keeps final application PDFs easy to browse in a local `Applications/` folder and attached to Linear; and
- optionally reconciles application status from the user's email and calendar.

Career Pipeline does not operate a developer-owned service, collect telemetry, retain user data centrally, submit applications, send messages, or contact employers.

## 2. Product boundaries

### Included in version one

- Codex Desktop plugin installation and conversational onboarding
- Required Linear connection and standardized job-search project
- Optional LinkedIn, Indeed, Firecrawl, browser, Notion, GitHub, Gmail, Google Calendar, Google Drive, and USAJOBS sources
- Resume import and career interview
- Approved local career profile, search criteria, and writing preferences
- Scheduled job discovery with user-configurable cadence and timezone
- Automatic Linear ticket creation for Strong Match and Worth Considering roles
- Conversational backlog review
- Immediate, user-triggered resume and optional cover-letter creation
- Local and Linear packet delivery
- Optional weekday application-status reconciliation
- Resumable workflows, validation, and synthetic test fixtures

### Excluded from version one

- A hosted Career Pipeline service or shared database
- Product telemetry or analytics
- Automatic job applications
- Employer or recruiter outreach
- A custom graphical onboarding interface
- Support for users without Codex Desktop
- A scheduled application-packet creation automation
- Manual Linear label changes acting as background wake-up events

## 3. Privacy and ownership model

The plugin contains reusable instructions, templates, validation scripts, schemas, and synthetic examples only. It must contain no personal data from the original Career workspace.

Each user's private data lives in:

1. a local workspace selected or created during onboarding; and
2. the user's own connected Linear workspace.

Optional connector content may be processed by Codex and the relevant third-party service. Onboarding must explain this accurately. “No Career Pipeline data collection” means the plugin author operates no collection service and receives no automatic copy of connector content, local files, run records, or feedback.

The plugin must not include telemetry, analytics SDKs, developer-controlled credentials, remote logging, or hidden network destinations. Beta feedback is voluntary and manually shared by the user.

## 4. Plugin architecture

Career Pipeline contains four user-facing skills plus supporting templates and deterministic validation tools.

### 4.1 Onboard

Purpose: create and validate a private Career Pipeline workspace through a resumable conversation.

Responsibilities:

- explain privacy and connector choices;
- create the local workspace;
- connect and configure Linear;
- offer and test optional connectors individually;
- preserve the source resume unchanged;
- conduct the career and ambitions interview;
- generate the career profile, search criteria, and writing preferences;
- collect packet and schedule defaults;
- run a readiness test; and
- create the selected automations only after explicit user approval.

### 4.2 Discover jobs

Purpose: find, verify, assess, deduplicate, and record qualifying current opportunities.

This skill is invoked by the scheduled discovery automation and may also be run manually. It uses the approved profile and source-specific checkpoints. Every new Strong Match or Worth Considering role is created in Linear automatically after an immediate duplicate check and delivery readback.

### 4.3 Review backlog

Purpose: help the user compare and manage the already-reviewed Linear backlog.

It can summarize new roles, compare selected tickets, record not-pursuing decisions, surface deadlines, and accept one or more tickets for application-packet creation. It does not submit applications.

### 4.4 Prepare application

Purpose: immediately create and deliver a tailored application packet for one or more explicitly selected Linear tickets.

It is user-triggered, not scheduled. The Linear `Prepare application` label records durable state, but adding the label manually does not wake Codex. The expected trigger is a request such as “Prepare an application packet for JOB-123.”

## 5. Local workspace

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
├── Applications/
│   └── JOB-123_Company_Role/
│       └── v001/
│           ├── Resume_Company_Role.pdf
│           ├── Cover_Letter_Company_Role.pdf
│           └── working/
├── Runs/
│   ├── discovery/
│   └── lifecycle/
└── State/
    ├── config.json
    ├── discovery-state.json
    ├── application-manifest.json
    └── onboarding-state.json
```

Final employer-facing PDFs sit directly in each version folder for easy access. Private drafts, source snapshots, extracted text, render images, and review evidence live in `working/`. Historical versions are never overwritten.

All persisted paths in configuration are generated during onboarding. Reusable plugin instructions must use configuration values and relative paths rather than a developer's username or fixed filesystem layout.

## 6. Onboarding flow

Onboarding begins when the user says “Set up my job search” and proceeds in resumable stages.

1. **Privacy explanation:** explain the local-first model, connector processing, and absence of developer-operated collection.
2. **Workspace:** ask the user to approve a local root, create the standard structure, and verify write access.
3. **Linear:** connect to a chosen existing workspace and team; create and verify the standard project, labels, and views.
4. **Optional connectors:** present each connector separately with its benefit, intended reads and writes, connect/skip choices, and fallback behavior. Save and respect the decision.
5. **Resume intake:** copy the original resume into `Sources/` without modifying it and extract a draft chronology and evidence inventory.
6. **Career interview:** gather accomplishments, contribution, scope, career transitions, strengths, ambitions, target work, compensation, geography, work model, travel, timing, constraints, and uncertain claims.
7. **Profile generation:** create `Career_Profile.md`, `Search_Criteria.md`, and `Writing_Preferences.md` for explicit correction and approval.
8. **Packet defaults:** default to a two-page tailored resume and one-page cover letter. Allow the cover letter to be disabled globally or per role.
9. **Schedule:** offer twice each weekday in the user's timezone as the discovery default, plus daily, weekly, or custom alternatives. Offer one weekday application-status reconciliation check when Gmail or Calendar is enabled.
10. **Readiness test:** verify local files, connector capabilities, Linear destinations, configured sources, and schedule settings.
11. **Activation:** keep discovery disabled until the user explicitly approves the profile and search criteria.

Progress is persisted after every completed stage. Resume-only defaults cannot activate discovery before profile approval.

## 7. Connector design

Linear is the only required connector. Declining it prevents activation because Linear is the durable backlog and workflow control plane.

| Connection | Benefit | Default access | Fallback when declined or unavailable |
| --- | --- | --- | --- |
| Linear | Searchable opportunity backlog, workflow state, packet delivery | Read/write within the selected workspace, team, and project | Activation stops |
| Indeed | Broad job discovery and company context | Job search and company lookup | Public search, employer boards, and ATS sources |
| LinkedIn | Job discovery when the installed capability supports it; otherwise people, company, and networking context | Capability-tested during onboarding | No LinkedIn coverage; never claim it was searched |
| Firecrawl | Web discovery, structured extraction, and difficult-page coverage | Search and page extraction | Native web search and browser tools |
| Browser | Authenticated job boards, JavaScript-heavy pages, and application-path verification | User-controlled browser sessions | Publicly accessible sources only |
| Notion | Career history, goals, notes, and accomplishment context | Read-only enrichment | Resume and interview remain sufficient |
| GitHub | Evidence of projects, technical scope, and public work | Read-only enrichment | No repository-derived evidence |
| Gmail | Application confirmations, rejections, interviews, and recruiter updates | Read only job-related messages; reconciliation may write derived status to Linear | Application stages remain manual |
| Google Calendar | Interview and deadline context; optional event creation | Read-only by default; create only after an explicit request | No calendar assistance |
| Google Drive | Resume import and optional user-requested backup | Read-only by default | Local files remain canonical |
| USAJOBS | Structured federal-role discovery | Search using the user's API key | Federal API lane disabled |

Onboarding records actual available actions, not merely whether a connector is installed. For example, LinkedIn people search must not be represented as LinkedIn job-search coverage.

Public Greenhouse, Lever, and Ashby adapters are built-in sources rather than personal connectors. The implementation may add other public ATS adapters behind the same normalized job-source interface.

## 8. Linear project model

Onboarding creates a standardized Job Search project inside the user's selected existing team.

Required labels:

- Strong Match
- Worth Considering
- Needs confirmation
- Prepare application
- Packet ready
- Applied
- Interviewing
- Offer
- Not pursuing
- Closed

Required views:

- New matches
- Needs confirmation
- Preparing materials
- Ready to apply
- Applied
- Interviewing
- Closed / not pursuing

Each opportunity ticket records:

- employer and exact title;
- location, workplace model, and travel expectations;
- compensation evidence;
- original posting and application URLs;
- ATS or requisition identity;
- source and verification timestamp;
- Strong Match or Worth Considering disposition;
- role-to-profile fit;
- evidence-supported strengths;
- missing qualifications and uncertainties;
- deadline when present;
- recommended next action; and
- discovery and re-verification dates.

Linear tickets are created only for Strong Match and Worth Considering roles. Clear non-matches remain in local run evidence.

## 9. Job-discovery workflow

Each discovery run:

1. reads the approved profile, criteria, configuration, and prior source state;
2. verifies the Linear destination and builds a duplicate baseline that includes archived records;
3. searches enabled broad sources and user-prioritized company boards;
4. uses public ATS adapters where available;
5. normalizes each posting into a common candidate schema;
6. verifies the original posting and application path where possible;
7. evaluates responsibilities before relying on title alone;
8. records fit, gaps, compensation, geography, recency, and uncertainty;
9. deduplicates primarily by ATS or requisition ID and otherwise by a conservative company/title/location/team fingerprint;
10. creates every qualifying new Linear ticket after a final duplicate check;
11. reads each created ticket back before recording delivery;
12. atomically updates source checkpoints and the stable review batch; and
13. reports new matches, meaningful changes, or actionable source failures.

Failed or partial source checks do not advance that source's last-successful timestamp, seen-record set, or rotation cursor. The run stays quiet when there is no new or materially changed actionable result.

## 10. Immediate application-packet workflow

When a user explicitly selects one or more tickets, Career Pipeline:

1. resolves the exact Linear tickets and adds `Prepare application`;
2. begins work immediately in the same conversation;
3. re-verifies the job posting and actual application destination;
4. reads the current career profile, writing preferences, and role-specific instructions;
5. derives the employer's central hiring outcomes;
6. compares candidate accomplishments by relevance, impact, contribution, scope, distinctiveness, recency, factual support, and rendered space;
7. creates a two-page tailored resume and, by default, a one-page cover letter;
8. runs factual, chronology, tailoring, ATS-structure, page-space, PDF text, page-count, and visual checks;
9. saves the final PDFs and private working evidence in the versioned local application folder;
10. uploads the exact final PDFs to Linear and verifies the attachments;
11. adds one concise comment explaining the evidence emphasis and actionable gaps;
12. sets `Packet ready`; and
13. clears `Prepare application` only after delivery is verified.

The default design is clean, text-focused, and ATS-friendly. Workday-specific or other ATS-specific structural rules apply only after verifying the actual destination. Application packet creation never submits the application.

If processing is interrupted, the application manifest records the latest verified stage. A later “Resume my packet queue” request continues without duplicating files, attachments, or comments.

## 11. Application-status reconciliation

Users who enable Gmail or Google Calendar may opt into one weekday reconciliation check in their timezone.

The workflow may update Linear automatically only from unambiguous evidence, such as a clearly identified application confirmation, rejection, interview invitation, or offer tied to an exact role. Ambiguous, contradictory, or employer-generic messages are flagged for user review.

The workflow does not send email, respond to invitations, create calendar events, or contact another person without an explicit user request. It preserves source receipts locally without copying complete mailbox or calendar contents.

## 12. Reliability and safety

- Persist onboarding progress after every completed stage.
- Store configuration and manifests atomically.
- Track source success independently.
- Use stable requisition identities and conservative fallback fingerprints.
- Recheck duplicates immediately before Linear creation.
- Read back Linear writes and attachments.
- Record final artifact hashes and review decisions.
- Preserve original source resumes and every delivered version.
- Never infer application submission from packet preparation.
- Never allow an old resume to override a later explicit user correction.
- Remember connector declines and permission limits.
- Ask for confirmation before migrations and back up user state first.
- Avoid duplicate alerts for unchanged failures.
- Never submit applications or send employer-facing communications.

## 13. Testing strategy

The plugin test suite uses synthetic candidates, employers, postings, resumes, emails, and Linear records.

Required scenarios:

- complete onboarding;
- interrupted and resumed onboarding;
- every optional connector accepted and declined;
- installed connectors missing expected actions;
- profile correction and approval gating;
- public ATS extraction for Greenhouse, Lever, and Ashby;
- duplicate roles across ATS, Indeed, and public search;
- closed, reposted, and changed requisitions;
- Strong Match and Worth Considering creation with readback;
- clear non-match exclusion from Linear;
- interrupted discovery with per-source checkpoints;
- immediate single-role and multi-role packet creation;
- interrupted packet generation and delivery resumption;
- factual, chronology, tailoring, page-space, PDF, visual, and ATS checks;
- Gmail status updates with clear, ambiguous, and contradictory evidence;
- upgrade and migration safety; and
- automated scans for developer names, personal identifiers, fixed paths, private URLs, credentials, and original Career workspace data.

## 14. Private-beta distribution

Career Pipeline source lives in a new private repository separate from the original Career workspace. The repository contains the plugin, synthetic fixtures, documentation, tests, version metadata, and changelog.

Beta users receive a Codex plugin installation or share link. After installation, they start a new conversation with “Set up my job search.”

Releases are versioned. Plugin updates do not overwrite user data. Schema changes use explicit, backed-up migrations. The first beta targets three to five users, with manually shared feedback and no automatic logs.

## 15. Beta success criteria

Version one is ready to expand beyond the private beta when:

- a nontechnical Codex Desktop user can install the plugin and complete onboarding without editing files;
- the user can skip any optional connector and receives a clear explanation of the lost benefit and fallback;
- activation cannot occur before Linear and profile readiness pass;
- scheduled discovery creates a useful, deduplicated Linear backlog;
- source limitations and failures are reported accurately;
- the user can request one or several application packets conversationally;
- verified final PDFs appear both in Linear and the local `Applications/` folder;
- interrupted workflows resume without duplicate tickets or artifacts;
- application status changes only from clear evidence or explicit user direction;
- no test or package scan finds personal data from the original Career workspace; and
- beta users can update the plugin without losing their local workspace or Linear history.

## 16. Implementation sequencing

Implementation should proceed in four separately verifiable increments:

1. **Plugin shell and onboarding:** manifest, workspace templates, configuration schema, Linear setup, resume intake, career interview, profile approval, connector capability matrix, and readiness test.
2. **Discovery and backlog:** normalized source interface, public ATS adapters, enabled connector lanes, evaluation, deduplication, Linear creation, state, and reporting.
3. **Immediate application packets:** explicit trigger, manifest, document generation, quality gates, local versioning, Linear delivery, and resumption.
4. **Lifecycle and beta hardening:** Gmail/Calendar reconciliation, upgrade safety, synthetic end-to-end fixtures, privacy scans, packaging, and beta release documentation.

Each increment must work with declined optional connectors and must not introduce a developer-controlled data service.
