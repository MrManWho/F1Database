# Local development on Windows

How to run Paddock Legacy 4.0 on your own PC, with Claude Code editing the files and Chrome refreshing as they change.
Nothing here affects the live site or the 4.0 test site.

## Every day

1. Open **PowerShell** and go to the project:

       cd "$env:USERPROFILE\Projects\F1Database"

2. Check which branch you're on, and that there's nothing unexpected (see *Branches* below):

       git status

3. Start the site:

       .\dev.bat

   Leave that window open. It prints the address and where the data lives. The first start takes a minute while it
   installs packages.

4. Open **http://127.0.0.1:5050** in Chrome.

5. Open a **second** PowerShell window, go to the project folder again (step 1), and start Claude Code:

       claude

   Ask it for changes. Chrome updates by itself (see *What updates when*).

6. To stop the site, click its PowerShell window and press **Ctrl+C**. Your local data stays for next time.

To carry on another day, do the same steps again. Before starting, `git pull` brings in anything pushed from the
cloud (see *Working with cloud Claude sessions*).

## Where the data lives

| Copy | Data | Sends emails / Discord / phone alerts |
| --- | --- | --- |
| **Local** (this PC, `dev.bat`) | `.devdata\` in the project folder: `accounts.db`, `careers\*.f1career` (one per league), `backups\`, avatars, imports | Never. They're saved as previews: Account → Settings → *Delivery preview* |
| **Staging** (the 4.0 test site on Render, branch `release-4.0`) | Render's free service. It's forgotten whenever the service restarts | Never (`F1_TRACKER_TEST_SITE=1`) |
| **Production** (the live site, branch `claude/gifted-lovelace-iqzlxy`) | Render's `/data` disk | Yes |

`dev.bat` refuses to start if anything would connect it elsewhere: a data folder outside the project (including the
old desktop app's `%LOCALAPPDATA%\F1UniverseTracker`), the live disk, mail-server settings, Render's variables, or a
Python other than 3.11. Live-site numbers are calculated on 3.11, and 3.12+ gives slightly different decimals.

`.devdata\` is never committed (it's in `.gitignore`). Git protects code; to protect data, copy the folder:

    Copy-Item .devdata ".devdata-copy-$(Get-Date -Format yyyyMMdd-HHmm)" -Recurse

Don't use `run.bat` or `launcher.py` for development. They are the desktop app and open the old desktop saves folder.

## Test data

Create your local account in the browser first. On the first visit the site asks you to set up the site owner. On this
PC no setup code is needed. Then, with the site stopped or in another window:

    .\dev.bat seed YOURLOGIN      a fictional league with 8 rounds played (standard and sprint weekends)
    .\dev.bat finale YOURLOGIN    a fictional league with only its last round left, for the finale and rollover

In the browser, the season-finale league is also under Account → Settings → *Try a season finale*.

To start again from empty, run `.\dev.bat reset`. It asks you to type RESET, then renames `.devdata` to
`.devdata-<date>`, so nothing is deleted. `.\dev.bat where` shows the folders in use.

A copy of real leagues is only for later testing. Use an encrypted backup from the live site (Account → Settings),
keep the original file untouched, and load a copy through Account → Settings → *Load the live site's leagues*.

## What updates when

- **Templates** (`templates\*.html`), **scripts** (`static\js`) and **images**: the open page reloads by itself.
- **Stylesheets** (`static\css`): the new styles are swapped in without reloading the page.
- **Python** (`f1tracker\*.py`): the server restarts by itself, then the page reloads.
- If you've typed into a form, the page doesn't reload. A small **Reload** bar appears at the bottom left instead,
  so nothing you typed is lost.

The site only listens on this PC (127.0.0.1), so other devices can't open it.

## Branches, and what each action does

| Action | What it does | Affects a website? |
| --- | --- | --- |
| Saving a file | Changes the file on this PC | No. Only your local preview |
| `git commit` | Saves a checkpoint of the code on this PC | No |
| `git push` | Sends your commits to GitHub | **Yes, if the branch is deployed** (below) |
| Merging | Combines one branch into another | Only when the merged branch is then pushed |
| Deployment | Render rebuilds a site from its branch | Happens automatically on push |

- `claude/gifted-lovelace-iqzlxy`: the **live site**. Never push to it. Live fixes are made in the cloud, with
  the owner's say-so.
- `release-4.0`: the **4.0 line**. A push redeploys the 4.0 test site, and that resets its data.
- Your own work: a local branch per piece of work, for example `git switch -c local/new-home-cards`. Pushing it to
  GitHub is safe (no site deploys from it), but optional.

Check where you are with `git status` (the first line names the branch).

## Checkpoints and undo

Save a checkpoint (`git add -A` only picks up code, never `.devdata`):

    git add -A
    git commit -m "Short description of the change"

See what changed since the last checkpoint with `git status` and `git diff`. In Claude Code, `/diff` shows its edits.
Undo:

- Throw away unsaved edits to one file: `git restore path\to\file`
- Throw away all uncommitted edits: `git restore .` (careful: this can't be undone)
- Undo a commit that's already pushed: `git revert <commit>`. This adds a new commit that reverses it, so nothing
  shared is rewritten.
- Try something risky: `git switch -c local/experiment-name` first. If it doesn't work out, `git switch release-4.0`
  and the experiment stays on its own branch.

Don't use `git push --force` or `git reset --hard` on a branch anyone else uses.

## Releasing a beta

When the work is ready, type `/ship-4-0` in Claude Code. It pulls in what's on GitHub and bumps the version. It
writes the changelog and admin notes, runs the tests, then shows you a summary and asks before it pushes
`release-4.0`. That push redeploys the 4.0 test site.

## Working with cloud Claude sessions

Claude sessions in the project chat also push to `release-4.0`. Before starting local work, run `git pull`. Before
pushing, run `git pull` again, so you build on what's there. If both sides changed the same lines, Git stops and
shows a conflict: ask Claude Code to resolve it, and don't force anything.
