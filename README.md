# Walta HerdShield climate dashboard and livestock advice API

The supplied climate dashboard now occupies `front_end/` and is served by the existing Flask application. Its observation, historical-rainfall, and policy endpoints are registered from `climate_api.py`. The standalone FastAPI backend and its documentation are also included in `front_end/`.

The Flask app serves the livestock advice JSON API (`/api/meta`, `/api/advice`, `/api/history`, `/api/drought`) and phone service (`POST /ussd`). The Destocking Advisor remains the main livestock feature at `/destock.html`; it is linked from the dashboard, rainfall, climate evidence, and policy sidebars.

## Run
    pip install -r requirements.txt
    python app.py            # http://localhost:5000
    python tests/test_all.py

The climate dashboard is at `/`. The sidebar links to the rainfall assessment, climate evidence, policy page, and the main Destocking Advisor.

On Replit: upload the folder, press Run (uses `.replit`), set the Africa's Talking USSD callback to `https://<your-repl>/ussd/<USSD_SECRET>`.

## How the advice is made (`engine.py`)
For one animal, each month: sell at today's price, or wait one more month. Waiting may pay more, but costs feed/water,
risks the animal getting thinner or dying, and can crash prices if everyone sells late. The engine works backwards over a
3-month window and compares "wait" against "sell now". Result -> HOLD or SELL 25/50/75%.
- **Real (from NMIS file):** current price per market, thin/medium/fat price gaps, normal monthly price drift, and a price-based selling-pressure proxy (falling prices across many markets). The `quantity` column is NOT used because its meaning is not confirmed.
- **Assumed (`assumptions.json`):** death rates, chance of getting thinner, extra pressure per drought level, holding costs, decision thresholds.
  These are NOT measured. Replace them with sourced numbers.

## Connecting your drought model (`drought_provider.py`)
Your model reports by REGION (Afar / Somali / Oromia). Each market is mapped to its region in `data/market_regions.json` (please verify), so Borana markets use the Oromia outlook. Accepts 4 probabilities OR just a class label.
Any ONE of: env `DROUGHT_MODEL_URL` (GET ?region=Oromia&market=... ), a file `data/drought_outlook.json`
(see the `.example.json`), or `POST /api/drought` with header `X-Api-Key` (set env `ADMIN_KEY`).
Region-wide outlooks cap confidence at Medium. A town-level override can be added under `markets`.
Until one is connected the advice assumes normal conditions and confidence is LOW. The dashboard lets you pick a scenario.

## Updating prices
Replace `data/Livestock_Market_Table_Data.csv` with a newer export (same 11 columns) and restart.
Cleaning (duplicates, swapped min/max, wild prices) is automatic and reported in `/api/meta`.

## Known limits
- ~1 year of prices, oxen only, thin per-market coverage (see `/api/meta`). Selling-pressure proxy uses only markets with enough recent history (about 4).
- Amharic/Oromo wording needs native-speaker review. Amharic is not on USSD (script may not display on basic phones).
- The other dashboard pages (Dashboard, Forecast, XAI, Policy) still show simulated numbers until wired to your real drought model.


## Honesty features and checks (added after an outside review)
- **Drought status is never hidden.** `status` is `live_model`, `cached_file`, `scenario` or `unavailable`. If the forecast is missing, undated or older than 14 days, the headline advice is marked "IF NORMAL CONDITIONS", a table shows the advice for every drought scenario, and the phone shows both "normal rains" and "moderate drought" advice.
- **Strict forecast checks:** each probability must be a number from 0 to 1, no NaN, all four classes present, total about 1. Saved with an atomic write and a date.
- **Confidence has three parts** (data quality, drought forecast, decision stability) and the overall value is the weakest one. It is never "High" while the death/thinning numbers are unvalidated.
- **Decision stability** re-runs the advice with each assumption nudged +/-50% (and price drift +/-1%/month).
- **Price drift is 0 by default** because a rolling backtest showed it does not beat "no change" (`reports/PRICE_BACKTEST.md`).
- **Sensitivity:** `python reports/sensitivity.py` -> `reports/SENSITIVITY.md`. Most sensitive assumption: the market-crash effect (no real evidence yet).
- Herd size limited to 1-5000. CORS is off unless you set `ALLOWED_ORIGIN`. Set `OUTLIER_FILTER=0` to keep every price (the filter removes 4 rows; they are listed in `/api/meta`).
- The four older pages (Dashboard, Forecast, XAI, Policy) carry a "DEMONSTRATION PAGE" banner: their numbers are simulated.

## Still NOT done (be honest about these)
- The Borana SPI notebook has run and its dated, climatology-only outlook is connected for five Borana markets. The logistic predictor did not beat historical climatology on validation, so the current outlook is not a skillful forecast and confidence remains LOW. Other markets lack local outlooks; rainfall alone does not represent forage, soil moisture, or animal outcomes.
- No separate one-, two-, and three-month drought outlooks.
- Death, thinning, holding-cost and crash-effect numbers are assumptions; no local validation.
- No backtest of the full decision against what happened (needs several years of prices + drought history + herd outcomes).
- USSD callbacks can be protected with `USSD_SECRET`, optionally restricted with `USSD_ALLOWED_IPS`, and are rate-limited per phone in memory. Configure these controls for public deployments because Africa's Talking does not sign callbacks.

## SMS questions and notifications

The supplied `sms.zip` is a **USSD-only** package. It adds a sell/hold option and additional data-quality caveats to an existing Africa's Talking USSD menu; it is not an SMS gateway, does not allocate a phone number, and contains a separate copy of the advisor server. This app already has the advisor and USSD flow, so those duplicate server files are not copied over.

This app adds an Africa's Talking SMS webhook using the existing livestock and climate data:

- Inbound questions support `PRICE <market>`, `DROUGHT <market>`, and `ADVICE <market> <thin|medium|fat> <herd size>`. Short natural questions containing a market and price/drought terms are also recognized. This is a bounded, data-backed responder, not a general-purpose AI chatbot.
- Send `HELP` for formats. `STOP` and `START` unsubscribe/resubscribe the sender; opt-outs are stored in SQLite and block admin sends.
- The protected one-recipient send endpoint is `POST /api/sms/send`, with `X-Api-Key: <ADMIN_KEY>` and JSON `{"to":"+2519...","message":"..."}`. It accepts one E.164 recipient and messages up to 500 characters.
- Inbound callbacks use `POST /sms/inbound/<SMS_WEBHOOK_SECRET>`. Use a long random secret in the provider callback URL. The callback has an in-memory per-number rate limit; use provider-side limits as well for a multi-instance deployment.

Configure these environment variables (never commit their values):

| Variable | Purpose |
|---|---|
| `AT_ENVIRONMENT` | `sandbox` (default) or `production`; selects the provider endpoint |
| `AT_USERNAME` | Africa's Talking account/application username |
| `AT_API_KEY` | Africa's Talking API key |
| `SMS_WEBHOOK_SECRET` | Random secret embedded in the inbound callback URL |
| `ADMIN_KEY` | Protects `/api/sms/send` |
| `AT_SENDER_ID` | Optional approved sender ID for production outbound messages; ignored in Sandbox |
| `SMS_OPTOUT_DB` | Optional path for the persistent SQLite opt-out database |
| `SMS_STAKEHOLDER_PASTORALIST_1` … `SMS_STAKEHOLDER_GOVERNMENT` | Optional fixed stakeholder phone numbers; configure privately, never in source control |

Copy `.env.example` to `.env` in the project root (alongside `app.py`) and fill in credentials. `app.py` loads this file with python-dotenv without overriding environment variables already supplied by the operating system or hosting platform. Sandbox is the default and uses `https://api.sandbox.africastalking.com/version1/messaging`; only set `AT_ENVIRONMENT=production` when you intentionally want the production endpoint. Sandbox requests go only to the Sandbox API; the integration does not send production SMS while in Sandbox mode. The Sandbox shortcode is not sent as `AT_SENDER_ID`.

The public source contains stakeholder roles and authorized commands, but no real sender numbers. For local fixed identities, put the seven `SMS_STAKEHOLDER_...` values in the ignored `.env.stakeholders` file in the project root, or set them in the hosting environment. Numbers must be unique Ethiopian mobile numbers in `+2519XXXXXXXX` form. Leaving a value empty disables that fixed identity; dynamic registrations continue to be looked up from the existing registration database.

Set the Africa's Talking inbound SMS callback to `https://<your-host>/sms/inbound/<SMS_WEBHOOK_SECRET>`; use a random secret of at least 32 characters. To receive replies on a dedicated number, first provision an inbound-capable short code/virtual number with Africa's Talking for the target country and connect it to the application. Code cannot purchase or assign a phone number. Outbound sender IDs and inbound numbers may require provider approval. Keep the opt-out database on persistent storage in deployments where the app filesystem is ephemeral; otherwise unsubscribe records will not survive a restart.

All automated replies use English. The app does not contact recipients until an inbound SMS arrives or an authorized administrator calls the send endpoint. Send only to users who have consented and comply with the provider's local messaging rules.

### Seven-role Sandbox simulation

The inbound route supports up to seven application-side stakeholder identities. They are **not** registered with Africa's Talking by this code. In Sandbox, `16273` is the simulated destination users text; it is not an outbound sender ID. Configure each sender number privately using the variable associated with its role. Each configured identity can issue only its assigned report:

| Role | Configuration variable | Authorized command |
|---|---|---|
| Pastoralist 1 | `SMS_STAKEHOLDER_PASTORALIST_1` | `DROUGHT STATUS <region>` |
| Pastoralist 2 | `SMS_STAKEHOLDER_PASTORALIST_2` | `LIVESTOCK ADVICE <market> <thin\|medium\|fat> <herd size>` |
| Pastoralist 3 | `SMS_STAKEHOLDER_PASTORALIST_3` | `WATER UPDATE <region>` |
| Agro-pastoralist / Livestock owner | `SMS_STAKEHOLDER_LIVESTOCK_OWNER` | `HERD RISK <market> <thin\|medium\|fat> <herd size>` |
| Veterinarian | `SMS_STAKEHOLDER_VETERINARIAN` | `ANIMAL HEALTH [region]` |
| NGO representative | `SMS_STAKEHOLDER_NGO` | `COMMUNITY REPORT <region>` |
| Government representative | `SMS_STAKEHOLDER_GOVERNMENT` | `DISTRICT SUMMARY <region>` |

Use the region names returned by `GET /api/regions` (for example `Afar` or `Oromia`) and market names available in `/api/meta`. Numbers are normalized before matching. A registered number using another role's command receives an authorization response; unsupported commands return a help list. Unknown numbers cannot access these stakeholder reports. Existing generic price/advice questions, webhook secret authentication, rate limiting, and STOP/START opt-out handling remain in place.

The regional SMS reports use the application's ERA5-Land/Open-Meteo observations and retrospective 90-day rainfall comparison. The rainfall screen is not a drought diagnosis or a future forecast. Rainfall and reference ET0 are not water-point or groundwater measurements; water availability data is not connected. Community and district livestock-outcome records, as well as animal-health/disease surveillance, are unavailable. The animal-health command can provide environmental context for a named region only, not a diagnosis. Herd advice uses the existing three-month decision aid and assumptions; it does not produce a validated livestock-loss probability. SMS audit rows record request type, stakeholder role, response status, and timestamp only—no sender number or message body.

To try the simulation safely:

1. Keep `AT_ENVIRONMENT=sandbox`, configure the Sandbox username/API key, and start the Flask app with the inbound callback reachable at `/sms/inbound/<SMS_WEBHOOK_SECRET>`.
2. Privately configure the intended sender numbers using the role-specific `SMS_STAKEHOLDER_...` variables. In Africa's Talking Sandbox, separately create/configure each simulated sender identity in the SMS simulator. Use the corresponding phone number as that session's sender and `16273` as the destination. Application configuration does not create or enroll simulator sessions.
3. From each session, send only its assigned command. For example, send `DROUGHT STATUS Afar`, `LIVESTOCK ADVICE Yabalo thin 10`, or `DISTRICT SUMMARY Oromia`. The four region-based reports need a region; advice/risk requests need a known market, animal condition, and herd size from 1 to 5000.
4. Confirm the inbound callback reaches the app and that the Sandbox simulator shows the reply to that same sender. A provider acceptance is not evidence of delivery to a real handset. Never change the environment to production for this test.
5. To verify the automated tests without sending SMS, run `python tests/test_all.py`. The stakeholder workflow tests mock the SMS provider.

## Public registration and personalized Sandbox welcome SMS

The integrated registration page is `/register.html` and is also linked from the dashboard. The Flask app serves its options from `GET /api/registration/options` and accepts submissions at `POST /api/registrations`. The API validates the name, Ethiopian mobile number, region, category, billing period, and explicit SMS consent. Registration requests are limited to five per source address per hour; phone numbers are unique, and the seven fixed simulator identities cannot be used as registration accounts.

Registrations and SMS attempt records are stored in the same SQLite file used for SMS opt-outs (`SMS_OPTOUT_DB`, default `data/sms_optouts.sqlite3`). The database holds contact details and must remain private; SQLite files are ignored by Git. Each record has a UUID, category, selected region/optional area, monthly or yearly price, `pending_payment` subscription status, SMS status, consent, and timestamp. There is no payment integration; the form does not claim that a plan is paid or active. There is no public endpoint to look up registrations or another user's details.

The six prices are configured server-side and returned to the page for display:

| Category | Monthly | Yearly |
|---|---:|---:|
| Pastoralist | 30 ETB | 300 ETB |
| Agro-pastoralist | 100 ETB | 1,000 ETB |
| Livestock business / livestock owner | 400 ETB | 4,000 ETB |
| Veterinarian / animal health worker | 250 ETB | 2,500 ETB |
| NGO / development organization | 2,000 ETB | 20,000 ETB |
| Government institution | 5,000 ETB | 50,000 ETB |

After saving a consented registration, Flask chooses the distinct welcome template for that category and appends the available climate summary for the matching existing reference point. It sends with the existing `sms_service.send_sms`; the registration endpoint sends only when `AT_ENVIRONMENT=sandbox`, and never exposes provider credentials to the browser. Provider acceptance is not proof of handset delivery. SMS failure does not roll back registration. An existing opt-out continues to suppress delivery. Current observation points are representative grid locations, not administrative boundaries; optional zone/district text is stored but is not treated as a verified geographic mapping. Areas without a connected reference point receive an explicit data-unavailable message. Disease surveillance and water-point data are not connected.

Registered numbers are added dynamically to the existing inbound SMS identity lookup, alongside any privately configured fixed identities. Each new user is scoped to the category's command and registration area. Market-based livestock advice is returned only when the market's existing region mapping agrees with the user's selected region; otherwise the system declines to provide a cross-region estimate. Reports remain subject to the existing webhook secret, rate limit, Sandbox-only response guard, and STOP/START opt-out behavior.

### Safe registration test

1. Start the Flask app with the existing Sandbox credentials and `AT_ENVIRONMENT=sandbox`. Do not put credentials in the browser or frontend.
2. Before submitting, separately configure the test sender in the Africa's Talking Sandbox simulator. Use a valid Ethiopian mobile number (`+2519XXXXXXXX`) assigned to that Sandbox test identity.
3. Open `http://127.0.0.1:5000/register.html` locally, choose a category and region, check the SMS consent box, and submit. Confirm the displayed amount and `pending payment` status.
4. The response distinguishes an accepted Sandbox API request from pending configuration, suppression, or failure. Check the Sandbox simulator for actual message appearance; do not infer delivery from the app's acceptance response.
5. To test inbound reports from this new registration, ensure the Sandbox callback points to `/sms/inbound/<SMS_WEBHOOK_SECRET>` on a publicly reachable HTTPS app and send only the category's authorized command from that simulator identity. The selected region is used when matching climate reference data exists; unsupported coverage is reported as unavailable.
6. Automated registration and SMS integration tests use mocked provider calls and never send SMS: `python tests/test_all.py`.

## Probe
See PROBE_INTEGRATION.md and probe_patch/. `probe_bridge.py` finds candidate sources through a running Probe; a person reviews them; they never change the advice. The dashboard's evidence card is fed by data/evidence.json.
