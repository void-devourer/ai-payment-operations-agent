---
name: Scope & Pay
description: Clear agreements in a calm business workspace.
colors:
  primary: "#080a0d"
  primary-hover: "#272a2f"
  ink: "#111316"
  muted-ink: "#5b616b"
  paper: "#ffffff"
  rail: "#f5f7fa"
  selected: "#c6dcff"
  navigation-blue: "#003087"
  focus: "#0070e0"
  divider: "#d8dadd"
  field-border: "#aeb3ba"
  success-ground: "#e6f0e9"
  success-ink: "#28583e"
  warning-ground: "#f5eddc"
  warning-ink: "#77531b"
typography:
  headline:
    fontFamily: "Arial, 'Helvetica Neue', sans-serif"
    fontSize: "36px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Arial, 'Helvetica Neue', sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Arial, 'Helvetica Neue', sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Arial, 'Helvetica Neue', sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.55
rounded:
  tag: "6px"
  field: "8px"
  source: "10px"
  panel: "14px"
  agreement: "18px"
  pill: "999px"
spacing:
  related: "12px"
  control: "16px"
  mobile-gutter: "20px"
  section: "24px"
  region: "32px"
  desktop-gutter: "48px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "11px 12px"
  tag-success:
    backgroundColor: "{colors.success-ground}"
    textColor: "{colors.success-ink}"
    rounded: "{rounded.tag}"
    padding: "4px 10px"
  agreement-summary:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "26px"
---

# Design System: Scope & Pay

## Overview

**Creative North Star: "PayPal-inspired business workspace"**

The approved PayPal sandbox dashboard reference supplies the visual language: pale navigation, white content, strong black type, pill actions and blue selected states. Scope & Pay keeps its own identity and a basic, classic, organized interface without flashy effects.

The workspace and client review share readable forms, quiet boundaries and clear human decisions. Source words, proposed scope, exact prices and provider state remain distinguishable.

**Key Characteristics:**

- Pale navigation rail and white reading surfaces.
- Black pill actions with blue navigation and visible keyboard focus.
- Generous grouping, simple outline SVG icons and factual amounts.

## Colors

### Primary

- **Action Black:** Primary decisions and creation actions; hover softens to charcoal.
- **Navigation Blue:** Links, selected tab underline and selected navigation text.
- **Selected Blue:** Pale active navigation fill and text selection.
- **Focus Blue:** Keyboard outlines, distinct from selection.

### Secondary

- **Affirmative Green:** Positive status text and its pale ground, rather than primary actions.
- **Warning Amber:** Labelled ambiguity and warning states.

### Neutral

- **Document Ink and Muted Ink:** Main reading text and secondary explanations.
- **White Paper and Pale Rail:** Main content and navigation/context regions.
- **Divider and Field Border:** Quiet record boundaries and readable form outlines.

**The Labelled State Rule.** Color reinforces a visible label; it never carries a decision or provider state alone.

## Typography

The shipped utility typeface is Arial with Helvetica Neue and sans-serif fallbacks.
Tabular numerals support amounts. Body copy has a maximum width of 75ch.

- **Headline:** Main page titles; project titles use 34px, reducing to 28px on mobile. General mobile headings use 30px.
- **Title:** Section headings; home sections use 19px, client proposal titles use 27px, reducing to 24px.
- **Body:** Main reading and form content; supporting text commonly uses 14–15px.
- **Label:** Names above fields, with a 7px gap. Controls use bold 700 weight.
- **Amount:** The workspace total is 72px/1.15 at weight 750 with tight tracking (-0.04em); it reduces to 60px below 1000px, 48px below 760px and 42px below 380px. The currency annotation is subordinate. This amount treatment is not a display-heading font rule.
- **Reference:** Monospace is reserved for hashes and technical references inside disclosures.

## Layout

Desktop pairs a 260px rail with flexible content. The signed-in header is 88px
high and sticky; the rail sticks below it. Main content is capped at 1640px with
50px top, 48px horizontal and 72px bottom padding. At 1200px the rail is 230px
and main gutters are 32px; at 1800px the rail grows to 280px and gutters to 60px.
Project views start at 30px top padding.

Reading and source regions stack at 1000px. At 760px the header and rail become
static, workspace navigation wraps, main padding is 30px 20px 48px, quick access
becomes two columns and overview panels stack. Project tables become readable
records. Mobile fields retain 16px text. The smallest layout has additional
adjustments at 380px.

Client review is centered at a maximum width of 1180px. The agreement pairs a
flexible document with a 350px decision region, shrinking to 300px before stacking
at 760px. Desktop document padding is 36px; mobile regions use 26px 22px.

## Elevation & Depth

The system is flat: there are no box shadows. Pale regions, thin borders and
white space distinguish navigation, summaries and the client decision region.
Control feedback uses short color transitions (160ms). Reduced motion removes
transitions and animation and restores automatic scrolling.

## Shapes

Primary and secondary actions are pills. Fields are gently rounded; status tags
are tighter, source quotations moderately rounded and context panels broader.
The client agreement has the largest panel corner, reducing to 14px on mobile.
Quick-action icons sit inside circles (64px, 58px on mobile); their SVG strokes
remain simple and consistent.

## Components

### Buttons

Primary buttons are black with white text; secondary buttons are white with a
thin gray border. Both have a 44px minimum height. Primary hover is charcoal;
secondary hover uses a cool tint and pressed state deepens it. Keyboard focus is
a 3px blue outline with 3px offset. Disabled controls use gray fills and stop
accepting clicks. Text actions are blue and underlined.

### Inputs and fields

Visible labels precede full-width white fields with a thin gray stroke. Textareas
resize vertically. Currency uses a separate symbol beside a decimal field.
Focus shares the visible blue outline. Errors retain explanatory text.

### Navigation

The pale rail uses outline icons and roomy entries. Selected entries have pale
blue fill, dark blue text and medium weight. Desktop entries have 14px corners;
mobile entries use 10px. Project tabs use a blue underline, not pills.

### Cards and containers

Overview panels use thin borders, 14px corners and 23px 22px 20px padding. The
agreement summary uses the pale rail tone, a thin border and 26px padding. Client
review uses one bounded agreement with a distinct adjoining pale decision area.

### Status labels

Small rounded labels identify inclusion, additions, ambiguity, acceptance and
invoice states. Semantic green and amber reinforce text. Sample and simulated
results remain explicitly labelled where mistaken identity would matter.

### Source quotations and disclosures

Source-link buttons are full-width, left-aligned quotation blocks with pale fill,
a thin cool border, 10px corners and 16px 18px padding. Hover adds blue tint.
Selecting one opens the original conversation and highlights the exact words.
Review rerun controls and history use native disclosures; technical references
remain subordinate.

## Do's and Don'ts

### Do:

- **Do** keep source words, scope interpretations and human decisions distinguishable.
- **Do** use visible labels, readable body text and keyboard focus states.
- **Do** label sample reviews and local simulated invoice payments explicitly.
- **Do** stack complex reading regions on narrow screens.

### Don't:

- **Don't** reproduce PayPal branding or invent financial totals.
- **Don't** add flashy animation or decorative gradients.
- **Don't** hide the exact deliverable and price behind summary metrics.
- **Don't** style disabled financial actions as available controls.
