// Real, official brand marks for the three third-party services this app
// actually integrates with today (Slack is not included -- it was removed
// from the simple-icons dataset this project sources marks from, and hand-
// drawing an unofficial approximation of a trademarked logo is worse than
// leaving it out). Paths are copied verbatim from simple-icons
// (https://simpleicons.org, CC0 for icons without an overriding license --
// Linear and Google Gemini both use the default CC0 license),
// which exists specifically for this "who we integrate with" use case.
// Each renders in `currentColor` so the marquee in landing.tsx controls
// color/opacity centrally rather than hardcoding each brand's own hue --
// this app shows one accent color, not a rainbow of borrowed brand colors
// (see CLAUDE.md-equivalent shadcn guidance: avoid multiple accents
// fighting each other).

import type { SVGProps } from "react";

export function LinearLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
      <title>Linear</title>
      <path d="M2.886 4.18A11.982 11.982 0 0 1 11.99 0C18.624 0 24 5.376 24 12.009c0 3.64-1.62 6.903-4.18 9.105L2.887 4.18ZM1.817 5.626l16.556 16.556c-.524.33-1.075.62-1.65.866L.951 7.277c.247-.575.537-1.126.866-1.65ZM.322 9.163l14.515 14.515c-.71.172-1.443.282-2.195.322L0 11.358a12 12 0 0 1 .322-2.195Zm-.17 4.862 9.823 9.824a12.02 12.02 0 0 1-9.824-9.824Z" />
    </svg>
  );
}

export function GeminiLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg role="img" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
      <title>Google Gemini</title>
      <path d="M11.04 19.32Q12 21.51 12 24q0-2.49.93-4.68.96-2.19 2.58-3.81t3.81-2.55Q21.51 12 24 12q-2.49 0-4.68-.93a12.3 12.3 0 0 1-3.81-2.58 12.3 12.3 0 0 1-2.58-3.81Q12 2.49 12 0q0 2.49-.96 4.68-.93 2.19-2.55 3.81a12.3 12.3 0 0 1-3.81 2.58Q2.49 12 0 12q2.49 0 4.68.96 2.19.93 3.81 2.55t2.55 3.81" />
    </svg>
  );
}
