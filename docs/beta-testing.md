# Trying Career Pipeline with friends

Start with three to five invited testers. A useful first session ends with an
approved profile and search criteria, a small set of reviewed roles, and one
requested application packet when a suitable role is available.

## Your first session

1. Follow the [installation guide](private-beta-installation.md). Allow about
   15 minutes for guided installation; onboarding and research may take longer.
2. Start a new Codex task and say: **Set up my job search.** Bring a current
   résumé and preferences for role, compensation, location, and travel.
3. Choose a career workspace separate from the plugin installation. Review the
   profile and criteria before approving them. Every connector is optional.
4. Ask: **Discover jobs using my approved criteria.** Review the evidence and
   coverage gaps with the shortlist. Relevant results depend on current openings.
5. Choose one saved job and ask: **Prepare an application for JOB-000001.** Use
   the actual job ID shown in your backlog. Review the resulting PDFs in your
   workspace's `Applications/` folder before using them.

## Feedback

Use the [beta feedback form](https://github.com/bentcarroll-cmyk/career-pipeline/issues/new?template=beta_feedback.yml)
or [report a problem](https://github.com/bentcarroll-cmyk/career-pipeline/issues/new?template=bug_report.yml).
Issues in this private repository are visible to everyone with repository access.
Share a short description or a synthetic example. Leave out résumés, personal
profile files, account details, and application documents. You can also give Ben
feedback directly through the channel where you received your invitation.

The three most useful signals are:

- **Setup:** Did installation and onboarding work? Where did you need help?
- **Relevance:** Were the suggested jobs worth considering? Which criteria missed?
- **Materials:** What needed correction in the résumé or cover letter?

Include the plugin version and your operating system when describing a problem.
Feedback is voluntary; the plugin does not send telemetry to its author.

## Invitation draft for the maintainer

Send this after the friend has been granted access to the repository:

> I built Career Pipeline, a Codex plugin that helps organize a job search,
> find relevant roles, and prepare tailored application materials. I'm inviting
> a few friends to try the private beta. You'll use your own career folder and
> choose which, if any, account connections to enable.
>
> Start here: https://github.com/bentcarroll-cmyk/career-pipeline
>
> Sign into the GitHub account I invited and accept the repository invitation.
> The README links to the download and setup guide. After installation, start
> a new Codex task and say "Set up my job search."
>
> I'm happy to walk through the first setup. I'd love to know where it was
> confusing, whether the roles were useful, and what you corrected in the
> application materials. Please keep the plugin within the invited beta group.

## First-friend observation

During the first real setup, record the app/OS version, whether the bundled
Python and Codex CLI were available, whether the plugin appeared after install,
whether the new task used onboarding, and the point where help was needed.
The automated package journey uses synthetic local data; it does not establish
that installation or generated writing works well on a friend's computer.

Ask for the three feedback signals after the first session and again after one
week of use. These are suggested personal check-ins, not scheduled messages or
automatic collection. [Updating safely](private-beta-upgrades.md) explains how
to preserve the career workspace between releases.
