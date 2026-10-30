# Brand

Cipher Cover is a control room for claims. The dashboard feels like a calm operations console: dark by default, dense where handlers work and quiet everywhere else.

## Fonts

From Google Fonts:

- **Headings**: Bricolage Grotesque, weights 600 and 700
- **Body**: DM Sans, weights 400, 500 and 600
- **Accent (a tagline, a quote or an agent's reasoning)**: Fraunces, italic, weight 400
- **Code, numbers and identifiers**: IBM Plex Mono. Claim ids, policy ids, amounts, times and trace steps always use it.

## Colors

- **Primary**: Ultraviolet `#6C4DFF`, white text
- **Secondary**: Citron `#D7F75B`, Indigo Ink text
- **Tertiary**: Tangerine `#FF7B3D`, Indigo Ink text
- **Information**: Lagoon `#1FB5D9`, Indigo Ink text
- **Highlight or alert**: Cherry `#E5254F`, white text
- **Ink on light backgrounds**: Indigo Ink `#14122B`
- **Ink on dark backgrounds**: Lilac Mist `#E4E1FA`

Use Ultraviolet, Citron and Tangerine when three things sit side by side. Add Lagoon fourth and Cherry fifth.

Meaning is fixed across the whole dashboard:

| Where | Color |
|---|---|
| Claim state: Waiting | Lagoon |
| Claim state: In progress | Ultraviolet |
| Claim state: Waiting for sign-off | Tangerine |
| Claim state: Decided | Citron |
| Decision: Approve | Citron |
| Decision: Refer | Tangerine |
| Decision: Decline | Cherry |
| Security or guard events | Cherry |

Never use color alone. Every state chip also carries its label.

## Surfaces

- **Dark mode (default)**: page background `#0D0B1E`, panels and cards `#181530`, raised panels `#221E42`
- **Light mode**: page background `#F5F3FF`, white panels and cards

Panels are rounded 20 px, cards 14 px and chips fully round. Panels have no outline. Depth comes from the step between surface colors and from a soft shadow on raised panels only.

Ultraviolet and Citron are too bright for small text on the wrong background. On light backgrounds use `#4A2FD6` for Ultraviolet text and `#5E7A00` for Citron text, and `#B8450F` for Tangerine. On dark backgrounds use `#A996FF` for Ultraviolet text and keep Citron and `#FF9A66` for Tangerine.

## Layout

The layout is a console with a rail, a board and a drawer. It replaces a page-per-screen layout.

- **Rail**: a fixed left rail, 72 px wide, icons with short labels beneath. It holds Queue, Sign-off, Referrals, Evaluations, Analytics and Instructions. The active item sits in a rounded Ultraviolet pill. The rail never has a border; it is a darker surface.
- **Command bar**: a single rounded search field at the top of the board. It finds claims by id, customer or policy and opens with the key `/`. Theme switch and run controls sit at its right.
- **Metric strip**: below the command bar, a row of four to five large numbers in IBM Plex Mono: waiting, in progress, waiting for sign-off, decided today and payout total. Each sits on its own card.
- **Board**: the queue is a board of four columns, one per claim state, not a table. Each claim is a card showing its id, the customer's first name and last initial, the claim type, the amount claimed and a state chip. Cards in Waiting for sign-off show how long they have waited.
- **Drawer**: opening a claim slides a drawer in from the right, 560 px wide, over the board. The board stays visible behind it. The drawer has four tabs: Overview, Documents, Decision and Trace.
  - Overview: the customer's story set in Fraunces italic, the items claimed and the policy summary.
  - Documents: one card per document, with its type as a chip.
  - Decision: the decision chip, the payout in large mono type, the calculation as a ledger with amounts right-aligned, the section relied on and the reason.
  - Trace: a vertical timeline, newest at the bottom, one node per agent step. Tool calls show their name and arguments in mono type. A live run shows a pulsing Ultraviolet node at the end.
- **Sign-off**: a separate view with a stacked list of payouts waiting for a handler. Each row has the amount, the handler picker and two buttons, Sign off and Send back.
- **Instructions**: read only, set in mono type on a raised panel with a copy button.

On screens under 900 px the rail becomes a bottom bar, the board columns become a swipeable row and the drawer becomes a full-screen sheet.

## Voice

Paste this section into `BRAND.md`, after Layout.

- **Mic button**: round, 48 px, in the command bar at its right. Idle is Ultraviolet with a white mic icon. Listening is Cherry with a slow 1.4 s pulse. Thinking is Lagoon with three dots. Speaking is Citron with a level bar. Every state also shows its word beside the button: "Ready", "Listening", "Thinking", "Speaking".
- **Captions panel**: a raised panel that slides up from the bottom right, 360 px wide. Your words are right-aligned on an Ultraviolet card with white text. The assistant's words are left-aligned on a raised card in Lilac Mist. Claim ids in captions are IBM Plex Mono chips that open the claim on a click.
- **Push to talk**: hold the mic button or hold the key `V`. Release to send. A tap starts a hands-free turn that ends on silence. Escape stops speech at once.
- **Acting handler**: the handler picker sits at the top of the captions panel. A voice sign-off request shows as a Tangerine highlight on the card in Waiting for sign-off, with a Confirm button that only a click can press.
- **Voice off**: when voice is disabled, the mic button is absent, not greyed out.
- **Motion**: the pulse and the level bar stop under reduced motion and are replaced by static state words.
- **Never**: audio waveforms as decoration, auto-play of speech on page load, or a spoken reply without captions.
- **Tone**: the assistant speaks in plain sentences. "Claim one zero one one is waiting for sign-off for $1,150.00." Not "Great news!"

## Shape and motion

- Spacing steps of 4 px. Panels pad 24 px, cards pad 16 px.
- Numbers align on the right and use tabular figures.
- Motion is short and purposeful: 160 ms for hover and focus, 240 ms for the drawer. A card moving between columns slides, it does not jump. Nothing loops except the live run indicator.
- Respect reduced motion: replace slides with fades.
- Focus rings are 2 px Lagoon with a 2 px offset on every interactive element.
- Contrast: all text meets WCAG AA against its surface.

## Avoid

- Borders on one edge of a panel, and thin lines across the top of the page
- Heavy use of gradient fills. One soft Ultraviolet glow behind the metric strip is the limit.
- Table gridlines. Use spacing and alternating surface steps.
- Pure black panels in dark mode
- Pure white text on the dark page. Use Lilac Mist.
- Icons without labels in the rail
- Color as the only signal of a state

## Tone

Plain business English in US spelling. Short labels, no jargon and no exclamation marks. Say "Waiting for sign-off", not "Pending approval". Say "Send back", not "Reject". Money is in US dollars, such as $1,250.00. Times use the 24 hour clock. Empty states say what to do next in one sentence.
