# Career Pipeline

A job-search assistant for Codex Desktop that keeps your career profile, opportunities, and application files in a folder you control.

**Private beta · v0.1.1 · invited testers only.** Career Pipeline is ready for guided testing. Installation and everyday use on a new tester's computer still need feedback; this is not a one-click installer.

## What it helps you do

- **Set up your search:** work through a resumable conversation about your experience, target roles, compensation, location, and writing preferences.
- **Find relevant jobs:** check available sources against criteria you approve, avoid duplicates, and explain fit, gaps, and missing information.
- **Review your backlog:** compare saved roles and decide what to pursue next.
- **Prepare application materials:** request a tailored two-page résumé and optional one-page cover letter for a saved role, with factual, text, and visual checks before the PDFs are marked ready.

Discovery schedules are optional and require your approval. Application materials are prepared when you ask. Career Pipeline does not submit applications or contact employers.

## Get started

This beta targets **Codex Desktop on macOS**, where the local package checks have been validated. Native Windows is unsupported by the current workspace locking, and Linux has not been validated. Installation on a new tester's Mac still needs beta testing.

You also need access to this private GitHub repository and Python 3.11 or newer for the local helpers. Codex may already provide a suitable Python runtime; the setup guide helps check. The core helpers need no additional `pip` packages. Web discovery needs an available web capability, and application packets need Codex document and PDF capabilities.

1. Accept your repository invitation and sign in to GitHub.
2. Open [Releases](https://github.com/bentcarroll-cmyk/career-pipeline/releases) and download `career-pipeline-plugin.zip` and `career-pipeline-plugin.zip.sha256` from the newest release. The initial friend-testing release is [v0.1.1](https://github.com/bentcarroll-cmyk/career-pipeline/releases/tag/v0.1.1).
3. Follow the [guided setup](docs/private-beta-installation.md). It includes a prompt you can paste into Codex.
4. After installation, start a **new Codex task** and say: **“Set up my job search.”**

Keep the extracted plugin folder separate from the private workspace you choose during setup. Keep the plugin folder in place while it is registered as a local marketplace.

## Your files and privacy

Your chosen workspace is the source of truth. It contains your profile and source résumé, one folder per saved job, and versioned PDFs under `Applications/`. The plugin has no hosted database, telemetry, or automatic feedback collection, and its author receives no automatic copy of your workspace.

Local storage does not mean all processing stays on your computer. Codex processes the information you ask it to use under your account's settings and terms. Any services you choose to connect process their requests under their own terms.

Every connector is optional, including Linear. You can start with a local résumé, an interview, and available public job sources. Email/calendar context and exports to Linear are separate choices; a connector's availability and permissions determine what it can do.

## Using the beta

Try prompts such as:

> Discover jobs using my approved criteria.

> Review my job-search backlog.

> Prepare an application packet for JOB-000123.

Use a real job ID from your own backlog for the last prompt. Job availability, source coverage, and connector capabilities can change. Review the reported evidence and any gaps, and read your final PDFs before using them.

- [What to test and how to send feedback](docs/beta-testing.md)
- [Update safely without losing your workspace](docs/private-beta-upgrades.md)
- [Changes by version](CHANGELOG.md)
- [Release process for maintainers](docs/releasing.md)

Share feedback manually through [GitHub Issues](https://github.com/bentcarroll-cmyk/career-pipeline/issues). Everyone with repository access may be able to read it; remove personal details and avoid attaching your workspace or résumé.

## License

The [private-beta license](LICENSE) lets invited testers use Career Pipeline for their own job search and beta evaluation. Redistribution requires the repository owner's permission. Your career information and application materials remain yours.
