# CLAUDE.md — working rules for this project

These rules are the standard for this project. They are general rules, not tied to any tech
stack. Follow them in every session.

## Project facts

- **Project name:** ForwardState *(from README — confirm)*
- **What it is for:** Turn market events and analyst assumptions into stock scenario forecasts,
  portfolio risk and explainable alerts — decision support only, never trading. *(from README — confirm)*
- **Who it is for:** <user> *(assumed for now: an investor or analyst who manages a portfolio and
  makes every buy/sell decision themselves)*

## 1. How to respond (every reply)

Use simple words and short sentences. Explain any jargon the first time you use it.

Use this shape. Skip a section only when it is truly empty.

- **TL;DR** — 1–3 lines: the answer, or what was done.
- **What changed** — only when the approach, design or plan moved.
  Before → Now → Why. One line each. Link the approach .md file.
- **Do next** — numbered, concrete actions. Mark who acts: (you) / (Claude) / (other: name).
- **Details** — only what is needed to act. Tables over paragraphs.
- **Compass** — 📍 Phase · Step · Next milestone · Open blockers
- **Refs** — clickable links to every decision, approach and key file this reply created,
  changed or relied on, one per line, each with a few words on what it is:
  - `[D007 v2 — cache API responses](docs/decisions/D007-cache-api-responses.md) · changed`
  - `[A004 — server-side search](docs/approaches/A004-server-side-search.md) · new, Trying`
  - `[COMPASS.md](COMPASS.md) · v05 → v06`

  Write "Refs — none" when nothing applies. Never mention a D### or A### anywhere in a reply
  without linking it.

Rules:
- Lead with the answer, not the reasoning.
- Give one recommendation, not a list of options. Show alternatives only when the user must choose.
- Say plainly when something is an assumption, a guess, or unverified.
- Link files with relative paths so they are clickable.
- No walls of text. If a reply gets long, move the depth into a .md file and link it.

## 2. COMPASS.md — where we are, where we are going

[COMPASS.md](COMPASS.md) (repo root) is the single source of truth for project status. It holds:
- Version and last-updated date (e.g. "Compass v01 · 2026-01-01").
- North Star: one short paragraph on who this is for and what "done and useful" looks like.
- "Right now" table: Phase · Step · Next milestone · Blockers · Time · Top risk.
- Phase map: phase · done when · status (✅ done · 🟡 in progress · ⚪ not started).
- Cut list: what gets dropped first if time runs short (cut breadth before depth).
- Change log: version · date · what moved · decisions changed.

Rules:
- Update it whenever the phase, step, a key decision, a blocker, the schedule, the cut list or
  the next milestone changes.
- It is versioned. Before changing it, copy the current file to
  `docs/compass-history/COMPASS-vNN.md`, then bump the version and add a change-log row.
  Never edit old versions.
- End every substantive reply with the one-line Compass footer taken from it.

## 3. ACTIVITY-LOG.md — so the user can restart after days away

At the end of every working session, in [ACTIVITY-LOG.md](ACTIVITY-LOG.md):
- Update the "Pick up here" box at the top:
  Last session · Where we are · Next 3 actions (with owner) · Waiting on ·
  "Say this to Claude to restart: …"
- Add a dated entry at the top of the log (newest first): what was done, decisions made, files
  created or changed (linked), and what was NOT done.

## 4. Decisions — never edited in place

Each decision is its own file so it can be opened with one click:
`docs/decisions/D###-short-name.md`, copied from
[docs/decisions/_TEMPLATE.md](docs/decisions/_TEMPLATE.md), with:
status (Proposed · Accepted · Superseded by D### / D### vN) · date · the decision in one line ·
why · options considered · evidence · version history (v1, v2 … each with date and trigger).

[docs/decisions/DECISIONS.md](docs/decisions/DECISIONS.md) is the index. It holds:
- A "Decision changes" table at the top (newest first):
  date · decision (linked) · before · now · trigger/evidence · compass version.
- The decisions list: D### (linked) · one-line decision · status.
- A "Learnings" table: anything realised on the fly, linked to the decision or issue it changed.

Rules:
- Never edit a decision in place. A change gets a new version (D### v2, added to the same file's
  version history with the old text kept) or a new D-number that supersedes the old one.
  Log it in the Decision changes table.
- Where the user has not said what they want, make a sensible decision, write it down as
  Proposed, and tell them. They accept or reject it.
- Every decision change also bumps the Compass version.

## 5. Approaches — every new approach gets its own .md

Whenever we try a new approach (a design, a structure, a method, a tool, a workflow):
1. Copy [docs/approaches/_TEMPLATE.md](docs/approaches/_TEMPLATE.md) to
   `docs/approaches/A###-short-name.md` (next number).
2. Fill it in: date · area · status (Trying · Kept · Dropped · Parked) · replaces A### ·
   What changed (Before / Now / Why) · the idea in 3 lines · how we tested it ·
   result (numbers first, before → after) · verdict (keep / drop / park, one-line reason).
3. Add a row to [docs/approaches/INDEX.md](docs/approaches/INDEX.md).
4. If it settles a lasting choice, also log it in DECISIONS.md.

Never delete a dropped approach. Mark it Dropped and say why. What we tried that did not work is
part of the record.

## 6. Working principles

- Narrow and working beats broad and half-working. Cut breadth before depth.
- Measured, not asserted: any "faster / better / smaller" claim needs before/after numbers, with
  how they were measured.
- Check your own work before saying it is done (run it, open it, look at it).
- Ideas for later go in [docs/roadmap/](docs/roadmap/), not into current scope.
- Time is tracked in [docs/BACKLOG.md](docs/BACKLOG.md): task · owner · hours · due · status
  (⚪ not started · 🟡 in progress · ✅ done · ✂️ cut · ⏸️ waiting on a decision).

## 7. Diagrams

When a diagram would help, make one as a separate file the user can open (PNG + PDF).
Keep the source (e.g. Mermaid `.mmd`) in `docs/diagrams/src/`, rendered files in
`docs/diagrams/png/` and `docs/diagrams/pdf/`. In .md files only link to the PNG and PDF. Do not
paste diagram code into them. Bump the version on change, keep the old one, and look at the
rendered image before saying it is done.

## 8. Git and GitHub — manual. Claude never commits.

- Claude never runs git or GitHub commands that change anything: no add, commit, push, pull,
  fetch, merge, rebase, reset, revert, cherry-pick, tag, stash, checkout, switch, branch,
  restore, rm, mv, clean, remote, config, init, clone, `git -C`, and no `gh`.
- This is enforced by the deny list in [.claude/settings.json](.claude/settings.json).
- Claude may run read-only git (`git status`, `git diff`, `git log`) to write accurate messages.
- At the end of any change, Claude gives the user:
  1. a ready-to-paste commit message, and
  2. the exact commands in ```` ```bash ```` code blocks, ONE command per block. The user runs them.
- GitHub account: **vrbabu9000 ONLY.** Never vrajesh9000.
  Remote = `git@github.com-personal:vrbabu9000/<repo>.git` (SSH alias for the personal key).
  Repo-local identity = `vrbabu9000 <vrb.canada@gmail.com>`.
  Before any push command, Claude tells the user to run `git config user.name` to confirm.
- Commit messages use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`,
  `test:`): short subject, bullet body, and the Compass version in the subject when it moved,
  e.g. `docs: scope and first decisions (Compass v02)`. No AI co-author trailer unless the user asks.
- Branches: the user decides. Claude may suggest a name; the user creates it.

## Where things live

| Path | What |
|---|---|
| [COMPASS.md](COMPASS.md) | Status: phase, step, milestone, blockers, cut list |
| [ACTIVITY-LOG.md](ACTIVITY-LOG.md) | Pick-up box + session log |
| [docs/decisions/](docs/decisions/DECISIONS.md) | Decisions, one file each, plus index |
| [docs/approaches/](docs/approaches/INDEX.md) | Approaches tried, one file each, plus index |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Tasks with owner and hours |
| [docs/roadmap/](docs/roadmap/) | Ideas for later |
| [docs/compass-history/](docs/compass-history/) | Old Compass versions (never edited) |
| [docs/diagrams/](docs/diagrams/) | Diagram sources (`src/`), PNG and PDF |
