---
version: 1
slug: "frontend-src-scope-app-tsx"
primary_target: "frontend/src/scope/App.tsx"
related_targets: ["frontend/src/scope/Workspace.tsx","frontend/src/scope/ClientReview.tsx","frontend/src/scope/style.css"]
---

# Scope workspace and client review

Mode: Operate. The user supplied a PayPal sandbox business-dashboard screenshot
and explicitly selected applying its visual language to workspace and client review.

THESIS: Give a small studio a calm business workspace where agreed scope, source
requests, client decisions and actual invoice states remain easy to distinguish.

OWN-WORLD: User-pinned PayPal reference: pale neutral navigation rail, white main
canvas, near-black Arial typography, black pill primary actions, outlined secondary
controls, pale blue active navigation, generous separation and simple outline icons.
Use Scope & Pay branding. Do not reproduce PayPal's logo or invent banking features.

STORY: Start on Home, create/open a project, review source-linked requests, prepare
an exact priced proposal, collect client acceptance, then manage its invoice.
Quick access uses existing actions. Projects opens the complete searchable table.

FIRST VIEWPORT: Desktop shows a 260px pale rail with Create project, Home, Projects,
recent projects and actual provider state. A white header carries the studio name
and real session controls. The main Home region shows original project value with
its explicit scope (client projects, excluding samples), circular quick-action
icons, factual project/client/sample counts and a recent-project table. No fake
balance, sales, revenue, chart, notification badge or financial forecast. Mobile
uses compact wrapping navigation, a reduced large amount, two-column quick access,
stacked overview regions and readable project records without horizontal overflow.
Project tabs and source-to-quote navigation remain. Client review uses a centered
white agreement and distinct decision region, same black controls and blue focus.

FORM: User-supplied screenshot is the authority. Seed d2f80565d4d7f77329ee5516f90e2050
was available in degraded form; the explicit pinned reference overrides its index.
No alternative direction or new visual metaphor is being selected. Build code-led.
Signature interaction: one-click quick access joins an existing task, and selecting
a quote still takes the user to the original source. All actions remain truthful.

FINISH: Build fully, inspect desktop and mobile in one batched round, fix the
material defects in one batch, confirm at most once, obtain the independent skill
review, then document the shipped tokens and components. Preserve payment, consent,
authentication, AI and tenant boundaries. No paid provider request is needed for UI QA.
