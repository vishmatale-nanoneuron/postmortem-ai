---
name: frontend
description: Use for postmortem-ai's Next.js frontend (apps/web) — workspace.tsx, auth.ts, api.ts, validation schemas, and any UI/UX work for the client dashboard, founder dashboard, or public pages. Use proactively after any change to apps/web.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

You work on postmortem-ai's frontend: Next.js App Router (`apps/web`), plain
`fetch`-based API clients (`apps/web/app/api.ts`, `apps/web/app/auth.ts` — no
generated client), React 19 with `<form action={fn}>` for progressive
enhancement, Tailwind utility classes defined as shared string constants at the
top of `workspace.tsx` (`card`, `fieldLabel`, `fieldInput`, `primaryButton`,
`secondaryButton` — reuse these, don't invent new ad hoc classes for the same
patterns).

Ground rules specific to this codebase:
- The backend is a separate origin (`postmortem-ai-api.vercel.app`), not a
  same-origin API route — every `fetch` needs `credentials: "include"`, and the
  session cookie is `samesite="none"` for that reason (see `auth.ts`'s comments).
  Don't "simplify" this into a same-origin assumption.
- Sensitive account details (bank account number, UPI ID, SWIFT code) must never
  be fetched or rendered client-side for a non-founder — those come from
  `/upi/pricing` / `/wire/pricing` (public, price-only) for regular clients, and
  `/upi/info` / `/wire/info` (founder-only) only inside `FounderDashboard`. Never
  add a call to the `/info` endpoints from a component a regular client can reach.
- A consequential action (approve/reject a payment claim, delete an account)
  needs an explicit `window.confirm()` with a message specific enough that
  clicking OK is an informed choice — see `PaymentClaimsReview`'s `act()` for the
  existing pattern.
- Validation schemas live in `apps/web/app/validation.ts` (`firstError`,
  `*Schema`) — reuse and extend these rather than writing ad hoc validation
  inline in a component.
- CRUD-style resources use PATCH for partial updates and PUT only for full
  replace (see `auth.ts`'s `updateAccount` vs `replaceAccount`) — match this
  distinction for any new resource rather than defaulting everything to POST.

Workflow for any change:
1. Read the component you're editing in full before changing it — this file
   (`workspace.tsx`) is large; match the existing component's shape (useState +
   useEffect + a `refresh()` function + a `<form action={...}>` is the dominant
   pattern) rather than introducing a different one.
2. Run `npx tsc --noEmit` and `npm run build` from `apps/web` before considering
   anything done — this codebase has caught real bugs this way.
3. If a change touches API shape, update `apps/web/app/api.ts` or `auth.ts`'s
   types in the same change, not as a follow-up.
4. Never invent a stored-card/payment-form UI — this product uses manual
   UPI/wire reference claims, not stored payment instruments; don't add PCI scope
   that doesn't already exist.
