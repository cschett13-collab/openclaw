# Phase 2 — AI Monetization Playbooks

How to turn the local stack ([`README.md`](./README.md)) into a margin multiplier
instead of a gimmick. The losing move is selling "AI" as the product ("I'll write
your blog posts with ChatGPT"). The winning move is using AI as a **silent
margin-multiplier on a proven business model** — the buyer pays for the outcome,
not the model.

> **Scope note:** these playbooks reference components that live *outside* this
> repo — a `site_auditor.py` scraper, a Next.js client portal, and a GoHighLevel
> (GHL) account. They're documented here as the strategy/architecture; the actual
> scraper, portal, and CRM wiring are separate projects. Edge in all three:
> **fixed local compute cost (electricity)** vs. per-token cloud pricing.

---

## 1. The "Broken Window" B2B lead engine (the audit play)

Built on top of a `site_auditor.py` scraper.

- **Method:** don't sell "marketing." Sell a specific fix to a problem the
  prospect didn't know they had. The scraper crawls local business sites for
  *objective* deficits: missing SSL, no Facebook Pixel, slow load times, no
  chat widget.
- **AI leverage:** the local 5090 ingests the `deficits_json` and writes a
  hyper-personalized, one-to-one email per prospect — at zero marginal cost, so
  you can do it at volume:

  > "Hey [Owner], your roofing site is missing an SSL cert, so Chrome flags it
  > 'Not Secure' to visitors. I recorded a 30-second video showing the fix."

- **Monetization:** **$500** setup fee to fix the deficits → upsell a
  **$297/mo** GHL SaaS subscription to manage chat widgets and lead routing.
- **Stack fit:** feed the deficit JSON into a Knowledge base / prompt template
  (see [`MEMORY.md`](./MEMORY.md)); store your offers and tone-of-voice rules in
  Memory so every email sounds like you.

## 2. Programmatic SEO (local lead flipping)

- **Method:** generate hundreds of hyper-local landing pages for high-ticket
  services — "Emergency Roof Leak Repair in Oshkosh," "Best Commercial Plumber
  in Fox Valley."
- **AI leverage:** cloud APIs charge per token, making tens of thousands of
  pages cost-prohibitive. Your workstation is a fixed cost. Feed the local model
  a strict JSON template; it churns out readable localized copy, FAQs, and
  metadata at **zero marginal cost**.
- **Monetization:** pages rank and capture organic traffic → leads flow into the
  CRM → sell/route them to local contractors for **$50–$100 per lead**.
- **Stack fit:** drive generation with a pinned local model + a structured-output
  prompt; a small batch script hitting Ollama at `:11434` mass-produces pages
  into the Next.js portal.

## 3. High-ticket AI voice & SMS agents

- **Method:** every local business misses calls on the job site — a missed
  burst-pipe call is a four-figure lost job. Build conversational agents that
  hook into the client's SMS / VoIP.
- **AI leverage:** use the local stack to **engineer and test the brain** —
  ingest the client's pricing, FAQs, and calendar into a Knowledge base, then
  iterate the system prompt locally for free. Deploy the *production* agent on a
  cloud voice service (Vapi, Bland AI) for 24/7 uptime.
- **Monetization:** **$1,500** setup fee to build the custom agent + **$500/mo**
  retainer to maintain it and keep it wired to their CRM.
- **Stack fit:** prototype against local models; once the prompt + knowledge base
  are dialed in, export them to the cloud agent. Local = the lab, cloud = the
  always-on runtime.

---

## Why the local stack is the unfair advantage

| Lever | Cloud-only | Local stack |
|-------|-----------|-------------|
| Marginal cost per generation | per-token $$ | electricity only |
| Volume (emails, pages) | throttled by cost | effectively unlimited |
| Client data privacy | leaves your infra | stays on your box |
| Iteration speed | metered | free, instant |

The cloud still wins for one thing: **always-on production uptime** (Playbook 3).
Use it deliberately as the runtime, and keep the expensive, high-volume
engineering and content generation on the 5090.
