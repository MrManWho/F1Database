# Paddock Legacy 2.0: admin guide

This is for site admins and Race Masters. The What's New screen and Help cover everyday use.

## Before and after the upgrade

- **Nothing to do to upgrade.** Each league upgrades itself (schema 17 → 18) the first time it's opened, after writing
  `backups/<league>-before-v18-upgrade-<time>.f1career`. Nothing existing is changed or removed.
- **Check notifications.** Every membership keeps its old results-email choice for that league only; everything else
  starts on *Important only*. Ask members to open **Notifications** in each league, and mute any test league.
- **Check visibility.** Leagues are private unless you choose Public or Listed (League settings → Visibility).

## Site settings (Account → Settings)

| Setting | Default | Notes |
|---|---|---|
| Let people create their own login | as before | Sign-up needs email set up. |
| Anyone can create a league | **off** (admins only) | Creators become that league's Race Master. 5 new leagues a day per account. |
| Email (SMTP) | as before | Or the SMTP_* environment variables on Render. |

## Per-league settings (League settings)

All of these affect one league only.

- **Visibility**: Private, Public (a share link) or Listed (also in the directory). Public pages only show submitted
  rounds, names, standings, records and news; never emails, usernames, notes, garages, offers, drafts or rounds in progress.
- **Selectable team goals**: off by default. See Help → Team goals. Rewards: Safe +1/0, Competitive +3/−1, Ambitious +6/−3
  Reputation, settled once at the next season rollover.
- **AI difficulty**: recommendations on/off; *Count Sprint points* (off by default in 2.0).
- **Team orders, weekend targets, round gates**: as in 1.20.
- **Joining**: requests, invite only or closed. **Rollover default** for ending contracts.
- **Discord webhook**: kept private; never shown in the Activity Log, exports or downloaded backups.

## Everyday admin tools

- **Members & roles**: roles, invitations (20 an hour per Race Master), join requests (5 an hour per account),
  **Hand the league over** (type the new Race Master's username).
- **Announcements**: pinned, targeted by role, scheduled, with expiry. The form shows who will see it, get a phone
  alert and get an email. Scheduled ones go out the next time anyone opens the league.
- **Grid & contracts**: contract states and seat problems; the **seat repair tool** fixes a mismatch in one step.
- **Season rollover** (Calendar → *Start the next season…*): shows each player driver's seat and contract, asks what happens
  to ending contracts, makes a backup, then settles pledges and team goals and starts the season.
- **Calendar**: rounds with results keep their number. Use *historical correction mode* only to fix a past mistake (logged).
- **Notifications (Manage)**: the delivery log (what, when, how many; never who). Deliveries are held and logged if a
  league suddenly sends too much.
- **Backups & data**: scheduled backups, safety backups (before rollover, restore, upgrade and delete), an integrity check,
  restore (backs up the current state first), JSON export and standings CSV. Downloads leave out the Discord webhook
  and public-link key.
- **Import** (League library → *Import .f1career*, site admins): a file is checked and summarised first and always becomes a new league.
- **Activity log**: every league action as a sentence. It never records passwords, codes, sessions, OCR text or webhooks.

## Accounts and security

- **Signed-in devices** and **two-step sign-in** are in each person's account page. To help someone who lost their
  phone: Accounts → All logins → **Reset two-step** (also signs out their devices).
- **Delete account**: people can delete their own login. Leagues keep their results. The last site admin can't delete
  themselves, and the only Race Master of a league has to hand over first.
- **Reports**: listed leagues can be reported; open reports are under Accounts → Reports. *Remove from the directory*
  hides the league from the directory (its share link still works for people who have it).
- **Rate limits**: sign-in codes (6 per 10 min), invitations, join requests, reports, directory search and demo starts.

## Database changes in 2.0

League files (`careers/*.f1career`), schema 18:

- New tables: `member_notify` (notification choices per member), `deliveries` (delivery log and dedupe keys),
  `seat_flags`, `weekend_targets`, `gate_bypasses`; created on first use: `announcements`, `team_goal_choices`.
- New columns: `events.press_required`, `notifications.category`, `notifications.username`,
  `join_requests.notify_preset`, `invitations.driver_id`.
- New meta keys: `visibility` and league profile fields, `difficulty_sprints`, `team_goal_choice`, `rollover_default`.

Shared `accounts.db` (created on first use): `user_sessions`, `user_leagues`, `rate_hits`, `whats_new_seen`,
`league_reports`, `league_creations`; new `users` columns `email_paused`, `is_demo`, `totp_secret`, `totp_enabled`.

## Rollback plan

Tested: a league upgraded by 2.0 and then opened by 1.20 works, and opening it again in 2.0 kept every result,
member, notification choice and team goal unchanged.

1. **Code only (normal case).** Redeploy the 1.20 commit (`037d0eb`) on the Render branch. 1.20 ignores the new
   tables and columns, so leagues keep working; 2.0-only features (notification choices, announcements, team goals,
   two-step sign-in, device list) are simply unused. Note: while on 1.20, email preferences go back to the old
   account-wide behaviour. Redeploying 2.0 later picks everything up again.
2. **Data (only if a league's data is wrong).** In that league's Backups page, restore the
   `before-v18-upgrade` backup (or any later one). A restore always backs up the current state first, so it can be
   undone. On Render the files are in `/data/backups`; locally in `%LOCALAPPDATA%\F1UniverseTracker\backups`.
3. **Two-step sign-in during a rollback.** 1.20 doesn't ask for codes, so accounts with two-step sign-in can log in
   with their password alone until 2.0 is back.

## Known limitations

- The league list reads every league file; very large sites will notice.
- Rounds can be Postponed but not Cancelled (remove a cancelled round from the calendar).
- Calendars export to .ics but can't be imported.
- Two-step setup shows a key and an authenticator link, not a QR code.
- No league logo upload yet (accent colour only).
- Scheduled announcements go out when the league is next opened, not at the exact minute.
