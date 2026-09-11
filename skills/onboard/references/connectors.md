# Connector onboarding

Test semantic actions, not installation status. Record the observed action list and never claim coverage that was not tested.

## Required Linear setup

Ask the user to choose an existing Linear workspace and team. Create a Job Search project and verify issue search, issue create/read, label management, view management, comments, and file attachments.

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

Read the project, labels, and views back. If Linear is declined or a required action is unavailable, record the result and explain that activation cannot continue.

## Optional connectors

Offer each entry separately with Connect and Skip choices. A prior decline remains in force until the user changes it.

| Connector | Benefit and intended access | Fallback |
| --- | --- | --- |
| Indeed | Job search and company context | Public search, employer boards, and public ATS sources |
| LinkedIn | Job search only if that action is observed; otherwise people/company context | No LinkedIn coverage; say so explicitly |
| Firecrawl | Web discovery and structured page extraction | Native web search and browser tools |
| Browser | User-controlled authenticated and JavaScript-heavy pages | Publicly accessible sources only |
| Notion | Read-only career history, goals, and accomplishment context | Resume and interview |
| GitHub | Read-only project and technical-scope evidence | No repository-derived evidence |
| Gmail | Read-only job-related confirmations, rejections, interviews, and offers | Manual application stages |
| Google Calendar | Read-only interview/deadline context | No calendar assistance |
| Google Drive | Read-only resume import; backup only on an explicit request | Local files remain canonical |
| USAJOBS | Federal-role search using the user's securely connected key | Federal API lane disabled |

Never store a USAJOBS key or another credential in workspace configuration. Calendar event creation, Drive backup, or any write outside Linear requires an explicit request at the time of the action.
