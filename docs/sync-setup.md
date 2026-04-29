# Sync setup — sharing seen / favorites between devices

Your seen + favorited markers live in `state.json` at the root of this repo
(not under `docs/`, so the public site doesn't carry the file). When you
click the ⚙ chip in the report header and provide a token, the report:

1. Reads `state.json` from `raw.githubusercontent.com` (public, no auth).
2. Merges with whatever's in your browser's `localStorage`
   (last-write-wins per field).
3. After every state change, debounces 2 s, then PUTs the merged state back
   via the GitHub Contents API using your token.

If two devices write at the same time, GitHub's optimistic locking (file
SHA) kicks in: the loser gets a 409, re-fetches, re-merges, retries once.

## Create a fine-grained personal access token (PAT)

1. **Open GitHub's fine-grained PAT page**
   <https://github.com/settings/personal-access-tokens>

2. Click **Generate new token**.

3. **Token name**: anything, e.g. `vb-rental-finder sync (laptop)`.

4. **Resource owner**: your own user (the same one that owns this repo).

5. **Expiration**: pick something reasonable. 1 year is the maximum for
   fine-grained tokens. Set a calendar reminder to rotate it.

6. **Repository access**:
   choose **Only select repositories** -> select **vb-rental-finder**.
   Do **not** grant access to all repos.

7. **Repository permissions** (only one needed):
   - **Contents**: change from `No access` to **Read and write**.

   Leave every other permission at `No access`. The token will be useless
   for anything other than reading + writing files in this repo.

8. Click **Generate token**. Copy the `github_pat_…` value — GitHub shows
   it once.

9. Back on the report, click the ⚙ chip. Paste the token, set a display
   name (used as `seen_by` / `favorited_by` in `state.json`), click
   **Test**, then **Save**.

## Sharing with a second user

Each user creates their own PAT with the same scope on their own account.
GitHub will accept commits from both as long as both tokens have
Contents:Read+Write on this repo. Commit messages identify which user
made the change via the display name they configured.

If your wife isn't a GitHub user, you can:
- Make her a collaborator on the repo (Settings → Collaborators), then
  she creates her own PAT;
- Or share a single PAT generated under your account (less granular —
  every change shows up as you).

## What lives in state.json

Just IDs and booleans. No personal info, no addresses, no rents, no notes
of the listings themselves. The full schema:

```json
{
  "version": 1,
  "updated_at": "2026-04-29T12:34:56.789Z",
  "listings": {
    "<id>": {
      "seen": true,
      "seen_at": "2026-04-29T12:34:56.789Z",
      "seen_by": "waldomiro",
      "favorited": true,
      "favorited_at": "2026-04-29T12:34:56.789Z",
      "favorited_by": "waldomiro",
      "notes": ""
    }
  }
}
```

`<id>` is a 12-char hex hash of the listing's `dedup_key`, stable across
runs as long as address + beds + baths don't drift.

## Security model & caveats

- The token is stored in `localStorage` keyed on the page origin. On
  GitHub Pages that's `borgesw26.github.io`, so any other Pages site you
  publish under the same user could in principle read it. Don't host
  untrusted code on your own GitHub account.
- The token never leaves the browser except as an `Authorization: Bearer`
  header to `api.github.com`. It is **never** written into any file the
  page generates.
- If you lose a device, **revoke the token** at
  <https://github.com/settings/personal-access-tokens> — every PAT can be
  invalidated independently.
- Browser dev tools can read `localStorage`. If your laptop is shared,
  use the **Clear** button in the modal when you're done.

## Troubleshooting

- **"Auth failed (401)" / "(403)"** — token is wrong, expired, or doesn't
  have Contents:Read+Write on this repo.
- **"Sync error"** chip in the header — last push failed. Click ⚙ →
  **Test** to see the specific status. The next click on a row or star
  retries the push.
- **My changes don't show up on the other device** — the other device
  needs to refresh the page; sync is on save+load, not a live stream.
- **State seems to keep flipping between two values** — two devices
  toggling the same listing simultaneously. Wait a couple of seconds and
  refresh both — last write wins.
