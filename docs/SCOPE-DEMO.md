# Scope & Pay setup and demo

This is the active product. It keeps the project's existing local services and
session security, with a new workspace at `/` and the former console at
`/operations`. All sample names and messages are synthetic.

## Start locally

Install the locked dependencies and prepare the ignored local credentials using
the existing [local development guide](LOCAL-DEVELOPMENT.md). Start Docker Desktop
before the services; PostgreSQL stores projects, decisions and invoice jobs.

```powershell
python scripts/setup_local.py
docker compose up -d --build --wait --wait-timeout 180
```

Open `http://127.0.0.1:8000/`. Sign in using a local demo identity and the
`DEMO_LOGIN_KEY` from the ignored `.env`. Keep the key out of screenshots/chat.
The local fixture login is not production authentication. Sign-in survives page
reload; sensitive writes may request recent identity confirmation.

## Complete one workflow

1. Load the sample project. Its $500 brief includes one landing page and one
   revision round. Read the three source messages before using their sample review.
2. Run the labelled sample review. See the included headline revision, tentative
   second page and contact-form addition. These are curated results, not live AI.
   Once results exist, rerun controls and the summary are under **Review options
   and summary** so the source-linked requests stay visible first.
3. Prepare a change proposal. Choose the work, exact source quote and price;
   nothing creates an invoice at this stage.
4. Generate a client review link and open it in a separate tab. Read the exact
   scope and price, enter a sample name and explicitly accept or decline.
5. Return to the project and refresh its records. Acceptance enables one logical
   invoice. Choose local demo invoicing when no sandbox account is configured.
6. Wait for the worker to create the simulated invoice, then record a simulated
   payment using the clearly labelled local action. Reload to confirm persistence.

The review token is returned once in the link's browser fragment. Its server-side
record contains a hash. API requests send the token in an authorization header,
not a URL. Treat the link as private: anyone holding it can decide on that proposal.
It expires after its displayed time and can be revoked. Editing a proposal or its
brief invalidates earlier links and acceptance; invoiced scope cannot be rewritten.

## Optional AI review

Prepare missing profiles and check their local configuration with:

```powershell
python scripts/check_scope_setup.py --init
```

This never overwrites existing files, prints credentials or contacts a provider.
Exit code 2 means setup is incomplete. Rerun without `--init` after saving fields.
A locally valid format does not establish working provider access.

The default example selects Gemini's free tier. In ignored `.env.scope`, set:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=your-generated-key
GEMINI_MODEL=gemini-3.1-flash-lite
```

Use a free-tier project without enabling paid billing for this demonstration.
Free-tier quotas and regional/account availability still apply. Google states
that free-tier data may be used to improve its products; use synthetic inputs.
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)

The optional OpenAI path requires `AI_PROVIDER=openai`, `OPENAI_API_KEY` and
an explicit `OPENAI_MODEL`. There is no automatic provider fallback. Then start:

```powershell
docker compose -f compose.yml -f compose.scope.yml up -d --build --wait --wait-timeout 180
```

The API sends only the current brief and selected source messages. Use synthetic
content until data handling has been reviewed for real clients. Model analysis
is bounded and rate limited; validated citations can still be semantically wrong.
Always review them. Manual proposals remain available if the AI is unavailable.

## Optional PayPal sandbox

Follow [PayPal setup](PAYPAL-SETUP.md) to prepare an account-managed sandbox and
ignored `.env.paypal`, then combine the existing PayPal overlay as well:

```powershell
docker compose -f compose.yml -f compose.scope.yml -f compose.paypal.yml up -d --build --wait --wait-timeout 180
```

The integration first creates a **draft** invoice. The separate **Enable sandbox
payment link** action activates that existing invoice with recipient and sender
email notifications disabled, then reads its status and validates the payment
link. Draft creation alone never makes an invoice payable. A genuine $1 USD
invoice using Workspace B's US sandbox seller has completed user buyer checkout,
validated `PAID` read-back and persistence in a fresh operator session. See the
[verification record](SCOPE-VERIFICATION.md) for the exact scope and limitations.
Local simulated payments cannot modify a PayPal invoice.

To prevent future-date scheduling from overriding notification suppression, this
sandbox adapter sets an issue date using the current UTC−12 calendar date and
rejects future dates or CC recipients before activation. Real merchant timezone
and concurrent provider-dashboard edits need genuine account validation before
using the integration with real client information.

A timeout or worker loss during a PayPal create can leave an unknown outcome.
The app preserves that state and will not blindly create another invoice. Check
the provider record before proceeding. There is no automatic money movement.

## Verification

Run checks while the database is up and the stack is stable. Do not rebuild or
restart services during integration tests.

```powershell
python -m unittest discover -s tests/unit -v
python scripts/check_scope_workflow.py
python scripts/evaluate_scope_ai.py
python scripts/check_docs.py
cd frontend
npm run check
npm test
npm run build
```

The structural evaluator makes zero model calls. See
[AI evaluation](SCOPE-AI-EVALUATION.md) and the
[implementation verification record](SCOPE-VERIFICATION.md) for actual results
and pending release work. A runnable local flow is not a production launch or
evidence of real customer demand.
