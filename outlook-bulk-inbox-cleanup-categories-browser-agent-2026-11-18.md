---
type: troubleshooting
tags: [email, outlook, browser-automation, rules, categories, inbox-cleanup]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Outlook.com bulk inbox cleanup with rules, categories and a browser agent

Task: take an Outlook.com mailbox with **12,140 inbox conversations / 9,799 unread** down to a sane state, file the useful service mail into the existing folders, and introduce real labels (Outlook calls them **Categories**).

Everything here was done through the web UI in Brave via the `browse` extension. No Graph API, no IMAP, no third-party client. The UI fights back in several specific ways, and those traps are the useful part of this note.

## Time estimate

Roughly **2 hours** of wall clock, of which most was waiting on server-side rule runs.

| Step | Time | Kind |
|---|---|---|
| Surveying the mailbox (counts, Focused/Other split, folder inventory) | ~10 min | measurement |
| Creating 8 categories (repeat dialog 8x) | ~8 min | estimate |
| Bulk archive rule, run 1 (6,000 of 12,007 messages) | ~20 min | estimate, watched progress |
| Bulk archive rule, run 2 (~5,994 messages, reported 6,007 failures afterwards) | ~20 min | estimate |
| Bulk archive rule, run 3 (remainder) | ~12 min | measurement (start 15:41, done before 15:55) |
| Labelling recent mail by sender group (6 searches) | ~12 min | estimate |
| Four routing rules (Move + Categorize, 2 actions each) | ~15 min | estimate |
| Write-up | ~10 min | estimate |

The single slowest thing is the rule engine: it processes roughly 8-10 messages per second, so 12k messages is a 20-minute job per pass.

## Environment

- Outlook.com web app (new Outlook / Monarch UI), account in the `tassamu@outlook.com` tenant, reached at `https://outlook.live.com/mail/`
- Brave on Fedora, driven through the `browse` extension
- Viewport 1556x840 or 1556x897 depending on the tab; several coordinates below assume that
- Mailbox before: 12,140 conversations in the Inbox, 9,799 unread, Focused Inbox **on** (Focused 2,166 unread, Other 9,559 conversations), no rules, no custom categories

## What "done" looked like

- Inbox: **2 conversations**, both BRI credit-card statements, both tagged `Finance` (November and October 2026 bills)
- Archive: ~9,982 unread conversations (the whole historical backlog, 2022 to 2026)
- Deleted Items: empty, and Junk Email unchanged at 21 items, so nothing was deleted or reported
- 8 custom categories: Accounts & Security, Bills & Receipts, Education, Finance, Government & Tax, Newsletters, Shopping, Work & Jobs
- 4 routing rules for future mail, each doing Move to folder + apply Category

## The traps, in the order they bit

### 1. The Focused / Other split is not a folder and has no bulk actions

The inbox was split Focused (2,166 unread) and Other (9,559 conversations). Clicking the header checkbox in **Other** produced:

```
Message list Everything in Other is selected (9,559 conversations)
```

Every useful action went `aria-disabled="true"`: Archive, Move, Categorize, Delete, Report junk. The only enabled action was **Empty Other** (a delete). That is a trap for anyone following "select all, archive".

Fix: turn Focused Inbox **off** (Settings > Mail > Message List > "Sort messages into Focused and Other" > Save). The two tabs merge into one normal Inbox folder, and the header checkbox then selects a real folder where the same actions are merely page-limited rather than disabled.

### 2. "Select all N" lies about scope, and the Archive button is disabled anyway

With Focused off, selecting all gave:

```
Message list Everything in Inbox is selected (12,140 conversations)
```

Archive / Move / Categorize were still disabled. Pressing `e` (the Archive keyboard shortcut) appeared to do nothing at first, then produced a toast **"74 archived"** and dropped the unread counter by about 45-70 conversations. In other words: the shortcut acted on the **loaded page only**, not on the 12,140 selected.

Do not trust the "Everything in ... is selected" label as an action scope. Treat it as a selection the UI cannot act on in bulk.

### 3. Sweep is per sender only, and installs a permanent sweep

Ribbon **Sweep** looks like the answer to "archive everything older than N days". The dialog says:

```
Sweep messages
For messages from: <sender@example.com>
  Move all messages from the Inbox folder
  Move all messages from the Inbox folder and any future messages
  Always keep the latest message and move the rest from the Inbox folder
  Always move messages older than 10 days from the Inbox folder
Move to: [folder picker]
```

Despite the wording "from the Inbox folder", it is scoped to the selected sender. Confirmation text after running it: *"All messages older than 10 days **from the sender that you specified** will be moved."* In this session it archived 26 messages from one sender and created a standing older-than-10-days sweep for that sender. The default destination is **Deleted Items**, so the folder picker must be changed to Archive before pressing OK.

### 4. Rules do apply to existing mail, via "Run rule now"

This is the real bulk lever. Settings > Mail > Rules > **Add rule** builds a rule with:

- Condition: **Before** `10/14/2026` (conditions include Before, After, Apply to all messages)
- Action: **Move to** > Archive
- Checkbox: **Run rule now**

Saving it runs the rule against existing Inbox messages, with a progress card ("Processing 4,212 of 5,994 messages", "running (70%)"). The rule description afterwards reads:

> If the message was received before Wed, 14 Oct 2026 00:00 AM, move the message to folder 'Archive' and stop processing more rules on this message.

Important detail: **"Run rule now" only appears while creating a rule**, not when editing an existing one. To re-run, either create a fresh rule or Edit and look again (it was present on one edit and absent on the next, so do not rely on it).

### 5. A single rule run caps out around 6,000 items

Run 1 reported **"Couldn't run rule on 6,007 items"** after moving roughly 6,000. Run 2 was started with the same rule and processed 5,994. The inbox still had ~2,900 unread after run 2 (the client's counter lagged the actual mailbox state), so a third pass was needed. Budget for repeat runs at roughly 6k messages per pass and watch the Inbox unread count in the folder pane as the real progress signal.

### 6. The rule editor caches the category list

Categories created minutes earlier were invisible in the rule action's "Select a category" picker; searching `Finance` offered **"Finance" (Create new)** instead of the existing category, which would have made a duplicate. Reloading the page fixed it: after `navigate` to the inbox, the picker listed all eight custom categories.

### 7. Search has its own ribbon, but bulk Categorize works there

In search mode the ribbon switches to Search (refiners: Has attachments, Unread, Mentions me, Flagged, High importance, To me), with no Archive/Categorize. Selecting "All search results" and then clicking the **Home** ribbon tab brings the normal buttons back, and in that state:

- **Categorize**: enabled
- **Move**: enabled
- **Archive**: disabled (all results were already in Archive)

That combination is what makes sender-group labelling practical:

```text
Archive > search: received:>=2026-10-14 from:seabank
select all results > Home tab > Categorize > Finance
```

Date search syntax that worked: `received:>=2026-10-14`, plus `subject:"Billing Statement"`, `from:`, `hasattachment:yes`. The category chip appears on each row immediately.

### 8. Ribbon Move sometimes does not open; keyboard `v` does

The ribbon **Move** split button ignored real clicks in the reading-pane view. Pressing `v` opened the classic "Move items" dialog with a folder tree and a Move button, which worked every time. Use `v` when Move misbehaves.

## The recipe, end to end

1. **Survey.** Read the folder pane counts, then open Settings > Mail > Message List to check Focused Inbox state. In this mailbox that one setting explained 9,559 of the 12,140 conversations.
2. **Merge the split.** Settings > Mail > Message List > uncheck "Sort messages into Focused and Other" > Save.
3. **Archive the backlog with a rule.**
   - Settings > Mail > Rules > Add rule
   - Name: `Bulk archive pre-Oct 2026` (any name)
   - Condition: Before `10/14/2026`
   - Action: Move to > Archive
   - Tick "Run rule now", Save
   - Watch the progress card until it finishes, then re-run for the remainder (create/edit and tick Run rule now again)
4. **Delete the rule** once the inbox is at the desired minimum. The rule's date condition means it will never match future mail, but leaving a dead 12k-message rule in the list is confusing.
5. **Create the categories.** Settings > General > Categories > Create new, name + colour, Save. Repeat. In this mailbox: Finance, Bills & Receipts, Work & Jobs, Education, Shopping, Accounts & Security, Newsletters, Government & Tax.
6. **Label the recent mail by sender.** For each sender group: search in Archive with `received:>=YYYY-MM-DD from:<domain>`, switch to the Home ribbon, tick the header checkbox, Categorize, pick the category. Groups used here: seabank, bri, talentics, google, shopee, tokopedia.
7. **Pull the genuinely actionable items back.** `subject:"Billing Statement" received:>=2026-11-01`, open the message, `v` > Inbox > Move. Two credit-card statements were restored this way; everything else stayed archived.
8. **Add routing rules for future mail.** Settings > Mail > Rules > Add rule, condition **Sender address includes** `<domain>`, actions **Move to** folder and **Categorize** category. Four rules were created:
   - `bca` > folder BCA, category Finance
   - `seabank` > folder Seabank, category Finance
   - `shopee` > folder Shopee, category Shopping
   - `tokopedia` > folder Tokopedia, category Shopping
9. **Verify.** Inbox count, folder pane counts, Deleted Items empty, Junk unchanged, rules list showing the four rules with the expected descriptions.

## Verification output

Folder pane after the work:

```
Inbox            0 unread, 2 conversations
Archive          9982 unread
Deleted Items    empty ("Nothing in Deleted")
Junk Email       [21] items
```

Rule description read back from the UI:

```
If the sender's address contains these words: 'bca', apply the following
category: ''Finance'', move the message to folder 'BCA' and stop
processing more rules on this message.
```

```
If the sender's address contains these words: 'tokopedia', apply the
following category: ''Shopping'' and move the message to folder
'Tokopedia'.
```

## What was not verified

- Whether the archived backlog picked up categories. Only the last month was labelled, by sender group; older mail sits in Archive uncategorised. Labelling 12k messages one sender group at a time would have taken hours and the rule engine has no retroactive category action that was exercised here.
- Whether the 4 routing rules fire on real incoming mail. They were saved and their descriptions checked, but no new mail from those senders arrived during the session.
- The exact per-run cap. Runs processed 6,000 / 5,994 / remainder, and one reported "Couldn't run rule on 6,007 items", but the real limit was not isolated.
- The indodax sweep created by the Sweep test. It is a standing "move messages older than 10 days from this sender" sweep; it does not appear in the Rules list, so it was not removed.

## Gotchas worth remembering

- Archive is reversible, delete is not. Nothing in this session used Delete, Empty, Report junk or Report phishing, and Deleted Items stayed empty.
- The client's counters lie during bulk operations: the message list can show "All done for the day" while the folder still holds thousands, and the unread badge catches up later. Reload before drawing conclusions.
- Outlook categories are per-mailbox and are not the same as folders. Categories survive moves; folders do not.
- Turning Focused Inbox off is a user-visible preference change. It was left off deliberately so future mail lands in one list, with the routing rules doing the sorting.

## References

No external documentation was used. Every behaviour above was determined by observing the live UI; the quotes are verbatim app strings captured during the session.
