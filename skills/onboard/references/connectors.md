# Connector onboarding

Every connector is optional. Present them in purpose groups so the user can understand the choices without completing every setup during quick start. Offer each connector separately, test semantic actions rather than installation status, and preserve a prior decision until the user changes it.

- Job discovery: Indeed, LinkedIn, Firecrawl, Browser, and USAJOBS.
- Career context: Notion, GitHub, and Google Drive.
- Lifecycle context: Gmail and Google Calendar.
- Optional export: Linear.

| Connector | Benefit and intended access | Fallback |
| --- | --- | --- |
| Linear | Explicit user-requested export of a selected local job summary or verified packet | Local folders remain complete and authoritative |
| Indeed | Job search and company context | Public search, employer boards, and public ATS sources |
| LinkedIn | Job search only when that action is observed; otherwise people and company context | No LinkedIn coverage; state that limitation |
| Firecrawl | Web discovery and structured extraction | Native web search and browser tools |
| Browser | User-controlled authenticated and JavaScript-heavy pages | Public sources only |
| Notion | Read-only career history, goals, and accomplishment context | Resume and interview |
| GitHub | Read-only project and technical-scope evidence | No repository-derived evidence |
| Gmail | Read-only job-related confirmations, rejections, interviews, and offers | Manual lifecycle updates |
| Google Calendar | Read-only interview and deadline context | No calendar assistance |
| Google Drive | Read-only resume import; backup only on an explicit request | Local files remain canonical |
| USAJOBS | Federal-role discovery using the user's securely connected key | Federal API lane disabled |

For each choice, record the observed actions. Use `deferred` when the user is undecided and wants to resume setup later; use `declined` for an explicit skip and `unavailable` when the needed action cannot be used. A deferred nonessential connector does not block readiness when a public discovery lane is enabled. Do not overstate LinkedIn people search as job-search coverage.

Linear is an export destination only. Do not use it for job IDs, duplicate checks, backlog reads, readiness, lifecycle state, or automatic packet delivery. A Linear export requires a separate current user request, exact readback, and a compact local receipt. Export failure never invalidates local work.

Never store a USAJOBS key or another credential in workspace configuration. Sending mail, accepting invitations, creating calendar events, Drive backup, or any connector write requires explicit authorization for that action.
