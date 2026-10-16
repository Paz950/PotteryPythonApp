# Pottery Studio – Licensing & Distribution Plan

> Status: **idea / not implemented** (2026-10-01). Update this file when decisions are made.

## 1. Background
- Pottery Studio was built at the request of an archaeologist, who supplied the STL files and taught the drawing method.
- He may want to sell the software to other archaeologists.
- Goal: the software must not be passed on to other people without the developer's permission.

## 2. First step – a written agreement (most important)
Technical protection only makes copying harder; the agreement is what really protects the developer.
The agreement should state:
- who owns the code,
- whether the archaeologist may resell it, and to whom,
- how income is split,
- that copies may only be distributed with the developer's permission.

Recommended: a short consultation with a lawyer who handles software / IP contracts.

## 3. Options that were considered
| Option | Verdict |
|---|---|
| Secret file in `C:\` that the program checks | **Weak** – the file is copied together with the program and is easy to find; a Python `.exe` (PyInstaller) can be unpacked and the check removed. |
| License key tied to the computer (signed, offline) | Good – a key copied to another computer does not work; nobody can create keys without the developer's private key. |
| Web version (pay per 50 schemes) | Strongest protection, but: large STL uploads (35–120 MB), many institutions forbid uploading unpublished finds, no internet in the field, the 3D/lasso interface must be rewritten for the browser, monthly server costs. Keep for later, if there is real demand. |
| **Online license check with an offline grace period** | **Recommended** – see §4. |

## 4. Recommended model: online license check + offline grace period
The program and all calculations run on the client's computer (no file uploads, no privacy problem). Only the **license** goes through the internet.

1. **Activation** – on first use the program sends the license key and a machine fingerprint to the license server. The server returns a **digitally signed approval**, saved on the computer.
2. **Regular checks** – whenever there is a connection, the program renews the approval, updates the scheme count and learns about blocks.
3. **Offline grace period** – without internet the program keeps working for a limited time since the last successful check (e.g. **14–30 days**). After that it asks to connect.
4. **Pay-per-use (optional)** – each **Save Scheme Image** uses one scheme. At each check the program takes a small batch in advance (e.g. 5) so a few schemes can be saved in the field and reported later.
5. **Security**
   - Approvals are signed with the developer's private key → a fake approval or a fake server does not work.
   - All communication over HTTPS.
   - No secret key is stored on the client's computer.
   - The `.exe` can be packaged with Nuitka or obfuscated (e.g. PyArmor) to make patching harder.

What the developer can then do from the server: see which computers are activated, block a computer, move a license to a new computer, renew, add schemes.

Limits (accepted): a skilled person can still patch a desktop program; the agreement (§2) covers that.

## 5. Where the license server runs
The license server does **not** run on the developer's own PC. Options:

| Option | What it is | Cost (approx.) | Maintenance |
|---|---|---|---|
| **Licensing service** (e.g. Keygen, Cryptlex, LicenseSpring) | Ready-made: machine activation, renewals, offline period, Stripe integration | Monthly fee (free/low tiers for few users) | None – no server of your own |
| Small cloud server / platform (e.g. Render, Railway, Fly.io, DigitalOcean) | Own small Python server (Flask + database) + Stripe | A few dollars per month | Updates, backups, security are your responsibility |
| Serverless functions (e.g. Cloudflare Workers, Vercel) | Small functions that answer license requests, no machine to manage | Often free at low volume | Low |

**Recommended start:** a licensing service (Keygen or similar) with a 14–30 day offline period – nothing to host or maintain.

## 6. Payments
- Stripe, or a "merchant of record" (Paddle, Lemon Squeezy) that also handles VAT and invoices abroad.
- Archaeologists usually buy through an **institution or research grant** → an **annual institutional license with an invoice** is often easier for them than small payments; pay-per-50-schemes can be offered in addition.

## 7. Open decisions
- [ ] Written agreement with the archaeologist (ownership, resale, revenue split).
- [ ] Pricing model: annual license / pay per schemes / both.
- [ ] Offline grace period length (14 / 30 days).
- [ ] Licensing service vs. own server.
- [ ] Packaging: PyInstaller vs. Nuitka, obfuscation yes/no.

## 8. Implementation (after the decisions)
1. Machine fingerprint + license check module (separate from the GUI and from `pottery_processor.py`).
2. Activation dialog in Pottery Studio (enter license key; shows status, days left offline, schemes left).
3. Scheme counting in **Save Scheme Image**.
4. `.exe` packaging and an installer.
