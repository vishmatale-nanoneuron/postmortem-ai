import { describe, expect, it } from "vitest";
import { DRAFTED_SECTIONS, TEMPLATE_MARKDOWN } from "../app/postmortem-template/template-markdown";

// The template page tags five sections "drafted by the tool". That claim is
// only true while those five match what apps/api/app/services/postmortem.py
// returns (summary, root_cause, detection, resolution, contributing_factors)
// and while each is actually a heading in the Markdown handed out by the
// copy button. Both halves are pinned here so neither can drift silently.
describe("postmortem template", () => {
  it("has a heading for every section the tool drafts", () => {
    for (const name of DRAFTED_SECTIONS) {
      expect(TEMPLATE_MARKDOWN).toContain(`## ${name}\n`);
    }
  });

  it("tags exactly the six things the backend drafter returns", () => {
    // summary, root_cause, detection, resolution, contributing_factors,
    // actions -- see the JSON schema in services/postmortem.py.
    expect([...DRAFTED_SECTIONS].sort()).toEqual(
      ["Action items", "Contributing factors", "Detection", "Resolution", "Root cause", "Summary"].sort(),
    );
  });

  it("tells the author to record an honest gap rather than guess a root cause", () => {
    // The exact marker the product itself writes for an ungrounded section.
    expect(TEMPLATE_MARKDOWN).toContain("Not established by the recorded evidence.");
  });

  it("keeps the author-owned sections the tool never fills", () => {
    for (const name of ["Impact", "Timeline (UTC)", "What went well", "Lessons"]) {
      expect(TEMPLATE_MARKDOWN).toContain(`## ${name}\n`);
    }
  });
});
