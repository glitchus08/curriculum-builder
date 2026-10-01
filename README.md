# Glitch Loom

*Weave topics into learning journeys.*

An internal Glitch team tool for planning courses, workshops, cohorts, talks and clinics.
Students never use Loom. They use the Glitch website, which is a separate product.

Loom was built from scratch. It shares no code, prompts, data or content with any earlier curriculum application.

See `SPEC.md` for what Loom does, `ISSUES.md` for what has been found and fixed, `RESULTS.csv` for what was tested, and `HANDOFF.md` before testing.

## Run it

Double-click `start.command`, or run:

```bash
cd ~/Documents/glitch-loom && ./start.command
```

Then open http://127.0.0.1:8790

It runs on this computer only. Nothing is published.

To stop it, close the Terminal window it runs in, or press Control and C there. A request to Claude that is still running is stopped with it. Finished parts stay saved.
To start it again, run `start.command` again. Pages that were open pick up where they were.

To see which build is running, open the course list: the last line shows the version, the build code and when the server started.
The same is at http://127.0.0.1:8790/api/health. If `filesChangedSinceStart` is true there, files were edited after the server started: start it again before testing.

## Where your courses are

Courses are files in the `data` folder inside `glitch-loom`. Each course has its own folder, with earlier copies in `history`.

To keep a copy somewhere safe, open the course list (top right of the page) and choose **Download a backup**.
To bring one back, choose **Restore from a backup file**. Restoring always makes a new course.

## Real content and simulated examples

| Choice on the brief | What you get |
|---|---|
| Weave with Claude | Real content. Claude researches sources, proposes an outline for your approval, then writes each session |
| Make a simulated example | Instant filler built by fixed rules, for trying the screens. Labelled "Simulated example" |

Loom uses the Claude command-line tool, signed in with your own Claude subscription.
Sign in yourself by running `claude auth login` in a terminal. Loom never asks for a password.

Loom does not use an API key.
Loom cannot see or change your account's billing settings. A request has already started by the time the Claude tool reports how it is being billed. If it reports paid extra usage, Loom stops that request. This is a safeguard after the fact, not a guarantee. For certainty, switch extra usage off in your Claude account yourself.

Optional: to choose a model, create `loom.config.json` in this folder:

```json
{ "model": "opus" }
```

Without it, the Claude tool's own default model is used.

## Try things safely

Add `?store=any-name` to the address to use separate test storage. It never touches your real courses.

Add `?motion=reduce` to see the reduced-motion version.

## Run the checks

```bash
cd ~/Documents/glitch-loom && node --test tests/*.test.mjs
```

```bash
cd ~/Documents/glitch-loom && python3 -W ignore -m unittest discover -s tests/server -t .
```

The second set uses a stand-in for Claude (`tests/fake_claude.py`). It uses none of your subscription.
These checks show that Loom handles data correctly. They do not show that a course teaches well.
A check that passes with the stand-in is not a real generation run. Real runs are listed in `RESULTS.csv`.

## Files

| File | Purpose |
|---|---|
| `index.html`, `styles.css` | Page and styling |
| `js/world.js` | The pixel-art world, drawn on a canvas |
| `js/flow.js` | Questions, branching, suggestions, review flags |
| `js/journey.js` | Simulated examples, consistency checks, change previews, export package |
| `js/real.js` | Turning Claude's answers into an editable draft; direct edits; what an edit affects |
| `js/store.js` | Checks saved work in full and brings older work up to date |
| `js/api.js` | Talks to the local server |
| `js/app.js` | Screens and actions |
| `serve.py`, `loom_server/` | Local server: course files, backups, and running the Claude tool |
| `loom_server/prompts.py` | What Loom asks Claude, and the shape every answer must have |
| `tests/` | Automated checks |
| `RESULTS.csv` | What was tested on which build, with PASS, FAIL, BLOCKED or NOT RUN |
| `HANDOFF.md` | What a tester needs: address, build code, test storage, real courses, known weak points |
| `docs/reviews/` | Independent reviews of the real packs |
| `tests/tools/inspect_export.py` | Checks a downloaded package against the approved version on disk |
| `data/` | Your courses. Created on first run |
