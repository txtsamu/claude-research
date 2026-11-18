---
type: troubleshooting
tags: [gmail, email, inbox-zero, browser-automation, browse-extension, chrome, filters]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Gmail bulk inbox cleanup from a browser agent (4,152 → 12 conversations)

Driving Gmail through a browser-automation extension to archive a 4,000+ conversation inbox. The interesting part is not the archiving, it is that **most of the obvious bulk actions silently do nothing** while telling you they worked. This note records the traps and the one path that actually works.

## Time estimate

- **Total: about 75 minutes** of interactive work (estimated from tool-call timestamps, not a stopwatch). It was long because every hypothesis cost a UI round trip.
- The actual cleanup, once the working method was found: **about 6 minutes** of actions.
  - Each filter create-and-apply: **15–30 s** of clicking, then **30–60 s** of Gmail server-side processing in the background (measured: the unread count settled roughly 40 s after the filter was created).
  - Manual triage of the surviving 112 conversations, page by page: **~4 min** (two passes, 50 rows read each time).

If you already know the trap list below, the same job is a 10-minute task.

## Context

- Gmail in Brave on Fedora, account index `u/1`, driven through the `browse` browser extension (`browse.*` tools).
- Starting state: **4,152 conversations in the inbox, 2,445 unread**, spread over the Primary / Promotions / Social / Updates / Purchases / Forums tabs.
- Mandate given: whole inbox, archive aggressively, keep anything genuinely important. Archive is reversible (mail goes to All Mail), delete is not, so **no action in this session ever used Delete or Report spam**.

## The traps (read this part first)

1. **The category tab is not "inbox ∩ category".** Clicking the sidebar `Promotions` (which navigates to `#category/promotions`) gave a view whose "select all N conversations in Promotions" banner happily archived 743 conversations and then reported "Your Promotions tab is empty" — while the inbox total did not move at all. Those 743 were already-archived mail carrying the category label. Same for Social (115). Net effect on the inbox: zero.
2. **The inbox counter is the only trustworthy progress signal.** Verify with the `1–50 of N` counter in the inbox view (or `document.title`, which carries the unread count). Do not trust toasts, tab-empty messages, or sidebar numbers.
3. **"Confirm bulk action" silently eats clicks.** Archiving more than ~50 at once opens a modal ("This action will affect all N conversations in Inbox. Are you sure?"). Until you click OK, the toolbar is blocked and every subsequent click appears to do nothing. That cost the most time.
4. **Gmail clears only 100 per bulk action.** Selecting 743 and confirming archived exactly 100 and left 643. Sometimes it then continues in the background ("We archived some conversations… This might take longer"), sometimes it stops. Always re-read the counter.
5. **Counts become `of many`.** For large result sets Gmail refuses to print a total (`1–50 of many`), so you cannot compute progress from the search view. Use the inbox counter.
6. **The search box keeps its text across hash navigation and even reload.** After a search, navigating to `#inbox` or `#category/...` leaves the query in the box, and the view can quietly stay in search-result mode. Symptom: "the tab clicks do nothing", `aria-selected` stuck on Primary, sidebar pushed off-screen at negative x. Fix: `fill` the search input with an empty string, then click the Inbox sidebar link (or open a **fresh tab**). Fresh tabs are the cheapest reset.
7. **DOM `.click()` does not drive Gmail toolbar buttons.** It works fine for **row checkboxes**, but for the toolbar (Archive/Delete/More) you need a real mouse event. Click by coordinates taken from `getBoundingClientRect()` in the same call, because Gmail's toolbar can sit under a Material overlay (`div.uW2Fw-bHm`) that swallows naive selector clicks.
8. **Pagination (`Older`) is unreliable.** In this session the pager reported `aria-disabled="true"` on page 1 of a 943-conversation category view, and sometimes accepted the click without advancing. Do not build a scan that depends on it.
9. **Filters with `in:` are perfect for one-shot operations.** Gmail warns: *"Filter searches containing 'label:', 'in:', 'is:', date range… are not recommended as they will never match incoming mail."* That is exactly the property you want when trimming existing mail: it cannot change future behaviour, and it works server-side on thousands of messages at once.

## The method that works

Use a Gmail **filter** whose criteria carry `in:inbox` plus the slice you want gone, action "Skip the Inbox", ticked "Also apply filter to matching conversations", then delete the filter.

### Steps (UI, Gmail settings)

1. Go to `https://mail.google.com/mail/u/1/#settings/filters`.
2. Click **Create a new filter**.
3. In **Has the words**, put the query, e.g. `in:inbox before:2026/01/01`.
4. Click **Create filter** (step 1 button, bottom of the dialog).
5. Confirm the warning dialog with **OK** (the "`in:` never matches incoming mail" warning).
6. On the action screen tick exactly two boxes:
   - **Skip the Inbox (Archive it)**
   - **Also apply filter to matching conversations.**
7. Click **Create filter** (step 2 button — a Material `<button>`, not the old `div[role=button]`; its centre was at ~`(889,558)` at 1556×840).
8. Verify in the filter list that the row exists: `Matches: in:inbox before:2026/01/01  Do this: Skip Inbox`.
9. **Delete the filter** afterwards: the `delete` link on its row, then `OK` in the confirm dialog. Delete the lowest row first so the rows above do not shift under your cursor. Never delete the user's pre-existing filters (in this mailbox: one `Kompas Institute` skip-inbox rule and one `notion.so` recategorise rule — both left untouched).

### Manual triage of what survives

Once the inbox is small, row-level judgment is straightforward and reliable:

- Read all rows with one DOM pass (`tr.zA`, sender from `.yX .yP`, subject from `.y6 span`, date from `.xW span`, unread via `classList.contains('zE')`).
- Select rows by calling `.click()` on each row's `[role="checkbox"]` — this *does* work.
- Then click the toolbar **Archive** by coordinates from `getBoundingClientRect()`.
- Confirm the count went down before the next pass.

## What was actually done, with numbers

| Step | Inbox after | Unread after |
| --- | --- | --- |
| Start | 4,152 conversations | 2,445 |
| Filter `in:inbox category:updates` | 4,073 | 2,380 |
| Filter `in:inbox before:2025/01/01` (big sweep) | — | 282 |
| Filter `in:inbox before:2026/01/01` | 112 | 48 |
| Row triage pass 1 (45 archived) | 33 | 15 |
| Row triage pass 2 (22 archived) | 11 | 3 |
| Final (a new Apple sign-in mail arrived during cleanup) | 12 | 3 |

Kept in the inbox, deliberately: a shared-server password from a colleague, a class community link, Google's account-review nudge, a payment confirmation, a person waiting on a reply, two vendor service notices, two formal downgrade requests, and a case reply.

Archived wholesale, judged unimportant: the pre-2026 backlog (program ads from Dicoding/Bangkit/Indosat/Cake, job alerts, course marketing, donation appeals, newsletters, expired verification codes, login/device notices, verification-code mails).

## Verification

- `in:trash before:2025/01/01` → **"No messages matched your search"**. Nothing was deleted; Trash stayed at its pre-existing 712 conversations.
- Inbox counter read from a freshly loaded tab: `1–12 of 12`, `document.title` = `Inbox (3)`.
- Filter list after cleanup contained only the two pre-existing rules.

## Not verified / caveats

- The `in:inbox before:2025/01/01` filter never appeared in the saved filter list even though its effect was real (unread fell 2,380 → 282). Either it saved and was later removed by a failed step, or the "apply to existing" action ran against an unsaved filter. Either way, an orphan filter should not remain, but it is worth a look in Settings → Filters if anything behaves oddly later.
- Nothing was labelled. Mail that was archived kept whatever Gmail category labels it already had; no new labels were applied.
- The `before:` sweep is a date-based judgment, not a per-message one. Old mail could contain something the owner wanted in view. It is all in All Mail and searchable.

## References

No external sources were used. Everything here was derived from observed Gmail behaviour in this session (DOM inspection, counter reads, and the filter dialog's own warning text).
