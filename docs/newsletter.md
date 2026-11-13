# The newsletter: sending through a platform you connect

A newsletter cub (the reference one is `newsletter`, in `kranto paths examples`) drafts an issue
from the week's briefs, and Needs you shows it as one line: its subject, whether it is ready, and
**Send**. Send opens one dialog: the subject, whom it goes to ("312 subscribers on …"), the
issue as it will read, and **Send now** (or **Schedule**, where the platform can). Kranto sends it
only when you click it there, and only through the newsletter platform you connected. The cub
never names a platform and never sees your key: it asks for `send.newsletter`, and Kranto does
the rest with the platform in use.

This page is the one place in Kranto's docs that names the platforms. Kranto offers two:

| Platform | You connect it with | Audience | Can schedule |
|---|---|---|---|
| **Resend** (the default) | a Full access API key, a verified sending domain, an audience | a segment you choose | yes |
| **Buttondown** | an API key | all your subscribers | no (sends now) |

A new cub is in **practice**: an approval sends nothing, and the page says "Nothing was sent
(practice)". The dialog has a **Send for real** switch (the cub's own setting: it applies to
later issues too); turn it on there when you are ready. Nothing is sent while
`~/.config/kranto/cubs.STOP` exists.

What stops a send is fixed in the dialog: with no account connected its button is **Connect a
newsletter account**, which opens the connect form in place and comes back to the same issue;
Send waits, with one line saying why. An issue you did not approve in time, or approved in
practice, stays on its row as the newest draft: Send asks again with the same issue (no new
draft, no model call). Its history says what happened: "Practiced on 28 Oct: not sent".

## Which one to connect

- **You already use Resend** (for a website's mail, say): connect Resend. It is the same
  account and the domain you already verified; you add a Full access API key (a Sending access
  key cannot make broadcasts), an audience with your subscribers in it, and a from address on
  that domain. Issues can be scheduled.
- **You want the fewest steps**: Buttondown needs one API key, and its subscribers are the ones
  your Buttondown newsletter has. Issues go now.

## Resend

What kranto reads and does there is from Resend's own documentation (resend.com/docs, read on
2026-10-21). In Resend's words an audience is now a **segment** (Resend renamed Audiences to
Segments in November 2025); Kranto calls it the audience.

### Your steps, once

1. **An account.** Sign up at resend.com.
2. **Your sending domain.** In Resend open **Domains**, click **Add Domain** and type the
   domain you send from. Resend recommends a subdomain, such as `news.example.com`, so
   the newsletter's reputation is kept apart from your own mail.
3. **Its DNS records.** Resend lists the records to add: for SPF an MX and a TXT record on
   `send.` your domain, for DKIM a TXT record on `resend._domainkey.` your domain, and, only if
   you turn on click tracking, a CNAME. Add each exactly as shown at your DNS provider, then
   click **Verify DNS Records**. The domain says *pending* while Resend looks; if it finds no
   records within 72 hours it says *failed* (check the records, then verify again). Resend
   suggests DMARC once the domain is verified; Kranto does not need it.
4. **Your audience.** In Resend open **Audience**, make a segment for the newsletter (for
   example *Newsletter*). Import your subscribers into it: **Add contacts**, **Import CSV**,
   upload a file with an `email` column (`first_name` and `last_name` are optional), map the
   columns, and choose the segment. A contact who unsubscribed stays unsubscribed and is never
   sent a broadcast.
5. **An API key.** Open **API Keys**, click **Create API Key**, name it `kranto`, and choose
   **Permission: Full access**. A *Sending access* key can only send single emails: Resend
   refuses it for broadcasts, audiences and domains, and Kranto's check says so. Copy the key now:
   Resend does not show it again.
6. **Connect it in Kranto.** Settings › Accounts › **Newsletter**, **Connect a provider**,
   **Resend**. Paste the API key, type the audience's name and your from address (`Your Name
   <news@news.example.com>`, on the verified domain), and click **Save and test**.
7. **Read what the check says.** Save and test only reads: it keeps the key if Resend accepts
   it with Full access, then says, in plain words, what is still missing:
   - "your domain … isn't verified yet: add these DNS records …" (step 3);
   - "there is no audience named …": click **Create the audience** to make it at Resend now
     (your approval makes it; nothing else is written there), or make it yourself (step 4);
   - the audience's subscriber count, and a reminder to import when it is 0.
   **Check again** reads again after you fix something.
8. **Send for real.** Open the issue's Send dialog and turn on **Send for real** (or on the
   cub's page: Home › Cubs › Newsletter › Settings). `kranto cub dry newsletter
   send.newsletter` turns it back to practice from a terminal.

### What each action does

| Step | At Resend | Safe? |
|---|---|---|
| The cub drafts an issue | a **draft broadcast** to your audience, from your address (`POST /broadcasts`) | yes: a draft sends nothing |
| You open Send | one read: the audience's subscriber count. The dialog is Kranto's own (the subject, the audience and its count, the issue; Details has the from address and the footer) | yes |
| You click Send now, in practice | nothing | yes |
| You click Send now, for real | kranto reads the broadcast (it must still be a draft with the same subject), then sends it (`POST /broadcasts/<id>/send`), or schedules it for the time you chose (Schedule) or the cub's `newsletter.send_at` | **this sends** |
| After the action | kranto reads the broadcast's status back: sent, queued or scheduled | yes |

Every issue gets a footer with Resend's unsubscribe link (`{{{RESEND_UNSUBSCRIBE_URL}}}`, one
per reader); Resend handles the unsubscribe.

**Never twice.** Resend offers no idempotency key for broadcasts, so Kranto holds the line
itself: an issue is approved once; the action sends only the broadcast its draft names, and
only while Resend says it is a draft; an action whose answer does not come back is `unknown` and
Kranto never repeats it (look in Resend's Broadcasts before doing anything else).

**Undo.** A *scheduled* broadcast can be cancelled in Resend (Broadcasts, the broadcast,
Cancel) until its time: it goes back to a draft and nothing is sent. A *queued* one can be
cancelled too, which stops the emails not yet delivered. A *sent* one cannot be recalled.

**Limits.** Resend allows 10 API requests a second for your team; an action uses three or four.
Your plan's daily or monthly sending quota applies: over it, Resend refuses the send and the
issue's history says it was not sent, and why.

## Buttondown

1. Sign in at buttondown.com and open **Settings**, then **API**.
2. Copy the API key.
3. In Kranto: Settings › Accounts › **Newsletter**, **Connect a provider**, **Buttondown**;
   paste the key and click **Save and test**. Kranto names the connection after your newsletter.
4. Turn on **Send for real** in the issue's Send dialog.

An issue goes to all your subscribers, now (Kranto does not schedule a Buttondown issue). Undo a
sent issue within minutes at Buttondown by setting it back to draft.

## Switching platforms

Connecting another platform makes it the one in use. A draft already held at the old platform
is still sent there (its Details say where); a draft Kranto holds goes out through the one in
use at your approval. If the audience changes after a draft was made, its action is refused:
redraft the issue.

## A newsletter cub from before the neutral names

`newsletter` 1.0.0 asked for `send.buttondown` and the broker service `buttondown`. This
release keeps both as aliases of `send.newsletter` and `newsletter` (for one release), so the
installed cub, its drafts and what it asks you work as before, and if you had turned on Send
for real it stays on. To move it to the neutral names, run `kranto cub update newsletter` and
apply the update on the cub's page.

## Subscribers

Kranto does not collect sign-ups. Your subscribers live at the platform: import them there
(Resend: step 4 above). A sign-up form is a follow-up a cub could provide.

## Webhooks

Resend can report deliveries, bounces and complaints by webhook. Kranto listens on 127.0.0.1
only, so it does not take them; the delivery figures are in Resend's dashboard.
