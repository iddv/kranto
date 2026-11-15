## Usage reports: the notice

**Who.** The controller is The Kranto authors, based in the European Union. Contact: the
maintainer, through https://github.com/iddv/kranto: open an issue asking the maintainer to
contact you, and put no personal data in it. The EU's General Data Protection Regulation and
the ePrivacy rules apply.

**What and why.** Kranto can send its maker one report a day about how it is used, so that
Kranto can be improved, and, when something fails, an error report within minutes, so that the
failure can be found and fixed before you have to tell anyone: the exception's type, where in
Kranto's code it happened, and its message with every word that could be yours removed. The
fields are listed below, and nothing outside that list can be sent. Basic reports have no
identifier, no content of yours, and no time finer than the day (an error report: the hour).
The detailed tier, which you must choose yourself, adds a random install id that is replaced
every 180 days and that you can reset, and how Kranto's assistant tools are used, hour by hour:
which of Kranto's verbs were called, from which door (the page, the console, kranto mcp, the
command line) and by which assistant, how each call ended (done, refused and the kind of
refusal, failed, prepared for your approval, then confirmed or dismissed), how long it took and
the ladder's rung; each assistant session's length, model, place and how it started and ended;
and which of Kranto's slash commands were used, by name. Never a prompt, a reply, a tool's
arguments or results, a file's contents, a topic's name, an id or a path.

**Only if you choose.** Nothing is sent until you answer the question at first run (`kranto
setup`, or the first page of the app); clicking Enter sends nothing. Until you answer, Kranto
counts on your machine only, and you can read those counts with `kranto telemetry show`. You can
change your mind at any time in Settings › Privacy & access, with `kranto telemetry off`, or by setting
`DO_NOT_TRACK=1` (or `KRANTO_TELEMETRY=off`) in Kranto's environment. With `local` or `off`
nothing is sent. With basic or detailed, the first report covers the first whole day after you
chose; each day's report is sent once, between 02:00 and 05:00 UTC the next morning. Error
reports follow the same choice: with basic or detailed they are sent within minutes of an error
(the same error at most once an hour, with a count); with local or off none is kept or sent.
The assistant's usage goes with detailed only; with any other choice none is kept or sent, and
leaving detailed deletes any waiting. The choice is yours alone: an assistant working in Kranto
can prepare it for your approval on the page, but never make it, whatever the assistant settings
say; it may turn reports off.

**Lawful basis.** Your consent (GDPR Art. 6(1)(a); ePrivacy Directive Art. 5(3)). Withdrawing it
is as easy as giving it, and stops all sending from the next day.

**Where it goes.** To a relay run by the controller on Amazon Web Services in the EU (Ireland,
eu-west-1), at https://dde6yrzwuxncv.cloudfront.net/v1/logs: the report enters through Amazon
CloudFront, AWS's network of edge servers, and is stored only in the EU. AWS is a processor
under its standard data processing terms. From there the reports go to a machine the
controller runs. The relay reads your connection's address only to work out a two-letter
country code and to limit how many reports one address can send; it never stores the address
or anything made from it. Nothing is sold, shared or used for anything but improving Kranto. If
you set `KRANTO_TELEMETRY_ENDPOINT` or `telemetry.endpoint`, reports go there instead, and
this notice does not cover that destination.

**How long.** Raw reports: 90 days. Figures and error reports made from basic reports, which
identify no one: 24 months. Detailed reports (with the install id): 13 months, then only
figures without the id.

**Your rights.** You can read everything sent from your install (`kranto telemetry show --sent`,
Settings › Privacy & access). For detailed reports you have the rights of access, erasure and objection:
ask the maintainer to contact you as described under Who (with no personal data and no install
id in the issue), then give the install id Settings › Privacy & access shows. Basic reports carry no
identifier, so the controller cannot find "your" basic reports to delete them; you can delete
your local copies. You may complain to your data protection authority.

**Separately: the update check.** When update checks are on (Settings › System › Updates), Kranto asks
GitHub's API for the newest release once a day; GitHub sees your address under GitHub's
privacy statement. That is not a usage report and is not covered by the choice above.

**Separately: Feedback.** Feedback (in the app's header) sends nothing by itself. File it
files the issue you read, through your own `gh` login, on Kranto's repository on GitHub; Open on
GitHub opens GitHub's new-issue page with it filled in, and you submit it there. Either way it
is a GitHub issue under GitHub's privacy statement, readable by whoever can see that repository,
and what it carries is shown to you before it is sent. That is not a usage report and is not
covered by the choice above.
