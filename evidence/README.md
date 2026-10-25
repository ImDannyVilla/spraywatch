# evidence

The local page, `server.py`, on `127.0.0.1:8091`. Standard library only.

It shows open alerts with the rule's arithmetic and the label line as proof, every label fact with its quote in context, the spray form and the printable postings. Every write is a POST with the page's form token and a loopback `Host` header, and goes through `agent.approval` or `agent.store`; after each one the check runs, so Slack hears at once.
