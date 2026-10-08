# SightOps — Agent Engineering Instructions

## 1. Mission

Build and maintain **SightOps — An Agentic Visual Reliability Engineer**.

Organization: Yabloko Labs  
Competition: OpenCV AI Competition 2026, powered by AWS  
Repository: `sightops`  
Workspace: `/home/azureuser/sightops`

SightOps is an AI-powered visual troubleshooting system for household
appliances and industrial equipment.

Its defining capability is **active perception**:

Observe → Measure → Reason → Investigate → Decide → Act.

The agent must recognize insufficient visual evidence, request or obtain
a better observation, re-run computer vision, and use the new evidence
to determine its next action.

SightOps must be a working product, not a static prototype.

## 2. Source of Truth

Read these files before implementing significant changes:

1. `SIGHTOPS_BUILD.md` — Complete product and engineering specification.
2. `SightOps_OpenCV_AI_Competition_2026_Proposal.pdf` — Original competition proposal.
3. `docs/PROGRESS.md` — Current implementation status.
4. Relevant architecture decision records and source code.

Use `SightOps.png` as the official branding source.

Never overwrite the original logo or proposal.

If specifications conflict, preserve safety and correctness, document
the conflict, and follow the most recent explicit project instruction.

## 3. Execution Mode

Operate as a senior/principal software engineer.

**FULL SEND.**

- Execute autonomously.
- Research before making uncertain technical decisions.
- Implement working features rather than producing scaffolding.
- Test and debug your own changes.
- Fix root causes instead of suppressing errors.
- Make sensible implementation decisions without unnecessary questions.
- Continue through the build phases until complete or genuinely blocked.
- Never claim that unimplemented functionality is complete.
- Never fabricate benchmarks, test results, deployments, or demonstrations.

Prefer simple, maintainable solutions over unnecessary complexity.

## 4. Required Skills and MCP Tools

Discover, read, and use the following where available:

- `ponytail`
- `headroom`
- `Serena MCP`
- `nori`
- `senior-swe`
- `full-send`
- `novgraph`
- `adhd`
- `Tavily`

Do not invent skill commands or MCP interfaces.

Inspect the actual installed capabilities before using them.

### Serena MCP

Use for semantic code navigation, symbol discovery, references,
safe refactoring, and understanding unfamiliar code.

### Hindsight

Use for persistent project knowledge and cross-session continuity.

### headroom

Use supported context-management capabilities to preserve useful
working context.

### novgraph

Use supported graph-based architecture or code-analysis capabilities.

### ponytail, nori, senior-swe, full-send

Follow their installed instructions and apply their engineering workflows.

### adhd

Keep tasks focused, prioritize the next actionable step, and avoid
unnecessary context expansion.

### Tavily

Use for current technical research, API documentation, compatibility
verification, and troubleshooting.

If a requested tool is unavailable, document the limitation and use
an appropriate supported alternative.

### diagram-design — Mandatory Architecture Visualizations

Repository:
https://github.com/cathrynlavery/diagram-design

Discover, install or load, and use the diagram-design skill
according to its official instructions.

Use diagram-design for all major architectural visualizations.

Diagrams must be:
- Professionally designed and visually polished.
- Consistent with SightOps branding.
- Technically accurate.
- Readable at GitHub README width.
- Rendered as actual images, not just Mermaid source.
- Exported to SVG, with PNG fallbacks if necessary.
- Committed to the repository.

Do not invent architecture components or integration statuses.

Include rendered diagrams directly in README.md.

Keep editable diagram sources in the repository.

Verify every diagram renders correctly before committing.

## 5. Hindsight Memory

Hindsight API is expected on port `8888`.

Discover and verify its actual API endpoint and health status.

Dedicated memory bank:

`sightops`

Create the bank if it does not exist.

Use it throughout development.

### Before major work

Recall relevant:

- Architecture decisions.
- Previous implementation progress.
- Known issues.
- Technical research.
- Testing results.
- Dependency constraints.

### After major work

Store concise, useful memories covering:

- Decisions and rationale.
- Completed milestones.
- Implementation details.
- Problems and fixes.
- Test results.
- Benchmark findings.
- Remaining limitations.

Never store credentials or secrets in Hindsight.

If Hindsight is unavailable, continue development and record
knowledge locally for later synchronization.

## 6. Environment and Secrets

Existing credentials are stored in:

`~/.hermes/.env`

Available variables:

- `NEBIUS_API_KEY`
- `ELEVENLABS_API_KEY`
- `TAVILY_API_KEY`

Load them securely when required.

Never print, expose, or commit secret values.

Never copy the complete Hermes environment file into this repository.

Maintain a safe `.env.example`.

All external AI calls must originate from the backend.

Do not expose API keys to browser code.

Use Nebius for the initial AI reasoning implementation.

Use ElevenLabs for voice output.

Use Tavily for technical research.

Verify actual API capabilities before implementation.

## 7. Engineering Architecture

Prefer a clean, modular implementation.

Initial deployment environment:

Azure VM, CPU-first.

Recommended technologies:

- Python
- FastAPI
- OpenCV 5
- NumPy
- React
- TypeScript
- Docker
- SQLite for initial persistence

Choose exact libraries and versions based on verified compatibility.

Do not add Rust solely for the sake of using Rust.

Maintain explicit interfaces between:

- Computer vision.
- Agent orchestration.
- Model providers.
- Voice providers.
- Storage.
- Inspection state.
- Incident management.
- Cloud infrastructure.
- Frontend/API contracts.

Keep the architecture ready for future AWS integration.

## 8. OpenCV Requirements

OpenCV 5 must perform substantive image and video processing.

Implement real computer-vision operations such as:

- Image preprocessing.
- Perspective correction.
- ROI detection.
- Indicator-state analysis.
- Analog gauge reading.
- Image-quality assessment.
- Change detection.
- Frame selection or tracking.

Produce structured measurements with meaningful confidence values.

Never invent measurement results or confidence scores.

Provide visual evidence and annotations where useful.

Verify the actual OpenCV version.

Do not claim OpenCV 5 compliance when running OpenCV 4.

## 9. Agentic Vision Requirements

The system must implement a genuine multi-step
perception-decision-action loop.

The agent should be able to:

1. Inspect visual evidence.
2. Evaluate measurement confidence.
3. Decide whether another observation is necessary.
4. Request another image or invoke another vision tool.
5. Re-evaluate the new evidence.
6. Produce a diagnosis or next action.
7. Escalate or request approval when appropriate.

Tool calls must be observable and testable.

Do not replace the agent with a fixed sequence of hardcoded responses.

A deterministic demo mode is permitted, but it must be clearly labeled
and exercise real implemented components.

## 10. Safety

SightOps is a troubleshooting and decision-support system.

Never allow unrestricted control of real safety-critical machinery.

Require explicit human approval for consequential actions.

The competition shutdown demonstration must be simulated.

Do not recommend bypassing safety interlocks.

Do not provide unsafe electrical repair instructions.

Represent uncertainty clearly.

Escalate when visual evidence is insufficient.

Maintain auditable inspection and action traces.

Validate uploaded files and protect user data.

## 11. AWS and COOL

The initial implementation runs on the existing Azure VM.

The AWS compute grant is not yet confirmed.

Do not provision billable AWS resources without authorization.

Prepare for:

- AWS Graviton.
- Cloud-Optimized OpenCV Library (COOL).
- Amazon Bedrock.
- Amazon S3.
- Amazon DynamoDB.
- AWS Lambda.
- Amazon CloudWatch.

Keep AWS-specific integrations behind clear interfaces.

Do not claim AWS or COOL functionality has been deployed or
benchmarked until it has actually been verified.

## 12. UI and Branding

Use the existing `SightOps.png` logo.

Maintain consistent visual branding.

Build a responsive, accessible interface.

Support:

- Home troubleshooting.
- Industrial inspection.
- Image upload/capture.
- Visual evidence inspection.
- Agent investigation timeline.
- Confidence measurements.
- Incident management.
- Voice guidance.

Prioritize clear instructions for elderly and novice users.

Do not create fake or nonfunctional interface controls.

## 13. Demo Video

Use:

https://github.com/scosman/videowright

Reference existing demo examples in:

`/home/azureuser/mender/demo/videos`

Do not modify the Mender project.

Use ElevenLabs for narration when available.

Preferred narration:

Young adult British female voice.

Create an actual playable demonstration video.

Target duration: approximately 4–4.5 minutes.

Maximum duration: 5 minutes.

Use real application recordings and accurate technical claims.

Clearly distinguish simulated scenarios from real deployments.

## 14. GitHub and Commits

Use the GitHub CLI:

`gh`

Target repository:

`sightops`

Preferred owner:

`Yabloko-Labs`

Verify the actual authenticated account and repository permissions.

Preserve existing remote work.

Do not rewrite unrelated Git history.

Use clear conventional commit messages.

Examples:

- `feat(vision): implement gauge analysis`
- `feat(agent): add active perception`
- `feat(web): build inspection workspace`
- `test(vision): add evaluation fixtures`
- `docs: document deployment`

### Strict Rule: No AI Attribution Footers

Do not add:

- `Co-authored-by:`
- `Generated-by:`
- `Assisted-by:`
- AI-generated signatures.
- Unnecessary automated footers.

Apply this rule to commits, PR descriptions, documentation,
release notes, and generated files.

Do not remove legally required copyright or license notices.

Do not change global Git configuration.

## 15. Testing Standards

Test every major feature.

Required checks include:

- Backend unit tests.
- API integration tests.
- Frontend type checking.
- Frontend production build.
- Browser end-to-end tests.
- Computer-vision evaluation.
- Agent tool-call tests.
- Active-perception tests.
- Human-approval tests.
- Error and timeout handling.
- Docker build and startup.
- Secret scanning.

Fix failures instead of hiding them.

Do not claim tests passed unless they actually ran.

## 16. Progress Tracking

Maintain:

`docs/PROGRESS.md`

Create it if missing.

Update after meaningful milestones.

Use this structure:

### Current Phase

### Completed

### In Progress

### Next Actions

### Blockers

### Tests and Results

### Architecture Decisions

### Known Limitations

### Git Commit / Repository Status

Keep this document concise and factual.

It must allow another agent session to resume without reconstructing
the entire development history.

## 17. Context Recovery

At the start of a new session:

1. Read this `AGENTS.md`.
2. Read `SIGHTOPS_BUILD.md`.
3. Read `docs/PROGRESS.md`, if present.
4. Recall relevant Hindsight memories from bank `sightops`.
5. Inspect Git status and recent commits.
6. Identify the current implementation phase.
7. Resume from the next incomplete task.

Do not restart completed work unnecessarily.

Do not overwrite working implementations without understanding them.

## 18. Completion Requirements

Before declaring a feature complete:

1. Implement it.
2. Run the relevant tests.
3. Verify actual behavior.
4. Update documentation.
5. Update progress tracking.
6. Store useful findings in Hindsight.
7. Commit meaningful changes.

Before declaring the entire project complete, verify:

- Working frontend.
- Working backend.
- Real OpenCV 5 processing.
- Functional agentic inspection loop.
- Household troubleshooting demonstration.
- Industrial inspection demonstration.
- Human approval controls.
- Reproducible evaluation.
- Docker deployment.
- Accurate README.
- Playable demo video.
- Clean GitHub repository.
- No leaked secrets.
- No fabricated technical claims.

## 19. Final Operating Principle

SightOps was inspired by helping a parent troubleshoot a broken
dishwasher remotely.

Build the visual AI assistant that could have helped in that moment.

The defining behavior is not simply recognizing an appliance.

It is knowing:

- What can be observed.
- What remains uncertain.
- What needs to be inspected next.
- When enough evidence exists.
- What safe action should follow.

**See. Diagnose. Act.**

FULL SEND.