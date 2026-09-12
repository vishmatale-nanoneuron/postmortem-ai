// Airlock's mark.
//
// A padlock would have been the obvious choice and the wrong one: a lock
// says "sealed", and this product is not a wall. An airlock is a chamber
// with two doors that are never open at the same time -- something comes
// in through the outer door, is held and inspected, and the inner door
// opens only if it is clean. That is exactly the mechanism, so that is the
// mark:
//
//   - the chamber, drawn as the enclosure
//   - the outer door, dashed: permeable, untrusted content comes through it
//   - the inner door, solid and heavy: the boundary that protects the agent
//   - the payload, held between the two, in the accent colour
//
// It also reads correctly at 16px, where a padlock's shackle turns to mush.
export function AirlockMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      role="img"
      aria-label="Airlock"
      className={className}
    >
      {/* The chamber. */}
      <rect x="2.25" y="4.75" width="19.5" height="14.5" rx="3.25" className="stroke-ink" strokeWidth="1.6" />
      {/* Outer door: dashed, because untrusted content passes through it. */}
      <path
        d="M8 4.75V19.25"
        className="stroke-ink"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeDasharray="2 2.4"
        opacity="0.55"
      />
      {/* Inner door: solid and heavier -- the side that does not yield. */}
      <path d="M16 4.75V19.25" className="stroke-ink" strokeWidth="2.2" strokeLinecap="round" />
      {/* Held for inspection, between the two. */}
      <circle cx="12" cy="12" r="2" className="fill-accent" />
    </svg>
  );
}
