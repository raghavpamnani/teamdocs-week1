# TeamDocs — 2 minute 45 second demo

## Before recording

1. Run the app and open the browser at a comfortable desktop width (roughly 1440 × 900).
2. Open this repository on GitHub with the completed Actions result available.
3. Keep `sample-files/launch-plan.md` ready to upload.
4. Open a terminal in the repository with the virtual environment activated. Prepare `python scripts/security_demo.py`.
5. Sign in as Administrator. Do one rehearsal. Avoid displaying unrelated browser tabs, personal information or tokens.
6. In Loom, choose the application window or browser tab and your microphone. Record in your own voice; a camera bubble is optional.

## Script and actions

| Time | What to show | What to say |
|---|---|---|
| 0:00–0:20 | Document library | “I built TeamDocs, a secure document workspace for small teams. The problem is simple: files get scattered, approvals are unclear, and access is often just hidden buttons. This project connects all five days of Week 1 into one working application.” |
| 0:20–0:50 | Upload `launch-plan.md`, then approve it | “I can upload a document into this workspace, give it a category, and send it for review. The backend validates the file and stores it privately. As an administrator, I approve it here. The status change is persisted, so this is a real workflow.” |
| 0:50–1:10 | Export CSV, then Activity log | “I can export the workspace register and trace the upload, approval and export in the activity log. Each event records the actor, action and request ID.” |
| 1:10–1:35 | Sign out; choose Viewer | “Now I’m a viewer. I can browse and download, but I can’t upload, approve or export. These controls reflect server-side permissions. The backend also checks membership and document ownership.” |
| 1:35–1:55 | Run `python scripts/security_demo.py` | “Here are real API requests. Reading my workspace succeeds. Exporting as a viewer returns 403. A different workspace and a guessed document ID return 404. So changing a URL doesn’t bypass the isolation.” |
| 1:55–2:15 | Optional: sign in as Admin and open GitHub import | “There’s also a public GitHub README import, with timeouts, bounded responses and upstream error handling. It brings repository documentation into the same review workflow.” |
| 2:15–2:35 | GitHub repository, README and green Actions run | “The repository includes a one-command Docker startup after configuration, pinned dependencies, automated API tests, and container build and startup checks. There are also health endpoints, structured logs and backup verification tools.” |
| 2:35–2:45 | Return to document library | “The biggest lesson was that security belongs in every resource lookup, and a good demo should prove those boundaries. TeamDocs is the foundation I can build future AI document workflows on.” |

If running behind schedule, skip the live GitHub import. Show its dialog briefly; do not let external network latency consume the demo. Only claim a passing CI run once it is actually green.

## Suggested Loom title

**TeamDocs | Secure Multi-Tenant Document Workspace | Week 1 Demo**

## Suggested video description

TeamDocs combines the Week 1 foundations into a working document workspace: authentication, role and tenant boundaries, secure file handling, approvals, CSV export, third-party API integration, Docker, CI and observability. The demo includes direct API checks proving that restricted and cross-tenant requests are blocked. Repository: add the public repository URL.

## Email reply draft — send after recording

Hi everyone,

Here’s my Week 1 project: **TeamDocs**, a secure document workspace with tenant isolation, role-based permissions, file uploads, approvals, CSV exports, and an audit trail.

The demo also shows direct API checks for unauthorized and cross-tenant access, plus the automated test and container workflow.

Loom: add your recording link
GitHub: add the public repository link

Thanks!

Do not submit the draft with placeholders. The recording and email/Form submission are separate final steps.
