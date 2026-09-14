"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { drafting, type DraftingPreferences } from "./api";
import { card } from "./dashboard-shared";

// PostMortem AI's tuning, per account and in context: the team's house
// style, and their own most recent published postmortem as an example of
// it, go to the drafting model with every draft. Form only -- every claim
// still needs a citation into this incident's evidence, and the server
// drops what does not have one, whatever the style asks for.
//
// Renders as absent until the API answers for it: the web deploys on
// merge and the API by hand afterwards.

const MAX_CHARS = 1500;

export function DraftingStyle() {
  const [prefs, setPrefs] = useState<DraftingPreferences | null | undefined>(undefined);
  const [instructions, setInstructions] = useState("");
  const [useExample, setUseExample] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => {
    drafting
      .preferences()
      .then((p) => {
        setPrefs(p);
        if (p) {
          setInstructions(p.instructions);
          setUseExample(p.use_published_example);
        }
      })
      .catch(() => setPrefs(null));
  }, []);

  if (prefs === undefined || prefs === null) return null;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const next = await drafting.setPreferences(instructions, useExample);
      setPrefs(next);
      setInstructions(next.instructions);
      setSaved("Saved. Applies to your next draft.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the drafting style.");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const next = await drafting.clearPreferences();
      setPrefs(next);
      setInstructions("");
      setUseExample(true);
      setSaved("Back to the defaults.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the drafting style.");
    } finally {
      setBusy(false);
    }
  }

  const dirty = instructions !== prefs.instructions || useExample !== prefs.use_published_example;

  return (
    <Card id="client-drafting-style" className={cn(card, "scroll-mt-16")} data-testid="drafting-style">
      <h2 className="mb-1 text-base font-semibold">Drafting style</h2>
      <p className="mb-3 text-xs text-muted">
        Tune how drafts are written for your team. Instructions here go to the drafting model with every draft, and
        so does your most recent published postmortem as an example of how you write, if you leave that on. Form
        only: every claim still has to cite this incident&apos;s evidence, and anything that doesn&apos;t is dropped
        no matter what the style asks for.
      </p>
      <form onSubmit={save}>
        <label htmlFor="drafting-instructions" className="mb-1 block text-xs font-medium text-muted">
          House style ({instructions.length}/{MAX_CHARS})
        </label>
        <textarea
          id="drafting-instructions"
          value={instructions}
          onChange={(event) => setInstructions(event.target.value.slice(0, MAX_CHARS))}
          rows={4}
          maxLength={MAX_CHARS}
          placeholder={
            "British spelling. Root cause in one paragraph. Action titles start with a verb. Say 'customer-facing', not 'external'."
          }
          className="mb-2 w-full rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <label className="mb-3 flex items-start gap-2 text-xs text-muted">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={useExample}
            onChange={(event) => setUseExample(event.target.checked)}
          />
          <span>
            Show my most recent published postmortem as an example of our style.{" "}
            {prefs.has_published_example ? (
              <span className="text-ink">One is published and will be used.</span>
            ) : (
              <span>Nothing is published yet, so this does nothing until something is.</span>
            )}
          </span>
        </label>
        {error && (
          <p role="status" className="mb-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" size="sm" disabled={busy || !dirty}>
            {busy ? "Saving…" : "Save style"}
          </Button>
          {!prefs.default && (
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={reset}>
              Reset to defaults
            </Button>
          )}
          {saved && (
            <span role="status" className="text-xs text-emerald-700">
              {saved}
            </span>
          )}
          {!prefs.default && !saved && (
            <span className="text-xs text-muted">
              Drafts made with a style record <code className="font-mono">prompt_version</code>{" "}
              <code className="font-mono">v4+style</code>.
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
