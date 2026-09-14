"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { airlock, type AirlockFeedback, type AirlockSuggestion, type AirlockTuning } from "../api";

// Tuning: what the account's own reports of wrong verdicts add up to. A
// report is made from the playground ("this should have been allowed") or
// from the SDK; here the reports become suggestions with the evidence
// behind them -- a rule reported as a false positive on three distinct
// scans, a source whose paraphrases keep getting through -- and one click
// applies a mute through the account policy. Reports that included their
// text export in the same format the repository's fine-tuning dataset
// uses, so a customer tuning their own classifier gets their own labelled
// examples out.
//
// The card renders as absent when the API cannot answer for it. The web
// deploys on merge and the API is deployed by hand afterwards; for that
// window this must not be an error on every paying account's dashboard.

const VERDICT_STYLE: Record<string, string> = {
  block: "bg-red-50 text-red-700",
  flag: "bg-amber-50 text-amber-800",
  allow: "bg-emerald-50 text-emerald-700",
};

function when(ms: number): string {
  return new Date(ms).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Verdict({ value }: { value: string }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 font-mono text-[10.5px] font-semibold uppercase", VERDICT_STYLE[value])}>
      {value}
    </span>
  );
}

export function TuningPanel({
  policyVersion,
  onPolicyChanged,
}: {
  // Bumped whenever the policy is written anywhere on the page, so a mute
  // applied here and a mute saved in the editor never overwrite each other.
  policyVersion: number;
  onPolicyChanged: () => void;
}) {
  const [tuning, setTuning] = useState<AirlockTuning | null | undefined>(undefined);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [showReports, setShowReports] = useState(false);

  const load = useCallback(async () => {
    try {
      setTuning(await airlock.tuning());
    } catch {
      setTuning(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, policyVersion]);

  // Not answered (deploy gap, signed-out race): nothing to show.
  if (tuning === undefined || tuning === null) return null;

  async function mute(suggestion: AirlockSuggestion) {
    if (!suggestion.rule_id) return;
    setBusy(suggestion.rule_id);
    setError("");
    setDone("");
    try {
      const policy = await airlock.muteSuggestion(suggestion.rule_id);
      setDone(`${suggestion.rule_id} muted. ${policy.muted_rules.length} rule${policy.muted_rules.length === 1 ? "" : "s"} muted on this account; applies to the next call on any key.`);
      onPolicyChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply the suggestion.");
    } finally {
      setBusy("");
    }
  }

  async function withdraw(report: AirlockFeedback) {
    setBusy(report.id);
    setError("");
    setDone("");
    try {
      await airlock.deleteFeedback(report.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not withdraw the report.");
    } finally {
      setBusy("");
    }
  }

  async function exportExamples() {
    setBusy("export");
    setError("");
    try {
      const { filename, text } = await airlock.tuningExport();
      const url = URL.createObjectURL(new Blob([text], { type: "application/jsonl;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export the examples.");
    } finally {
      setBusy("");
    }
  }

  const { reports, suggestions, examples_with_content: withContent, examples_in_deep_scan: inDeepScan } = tuning;

  return (
    <div className="mb-4" data-testid="airlock-tuning">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Tune Airlock</h3>
        {withContent > 0 && (
          <Button type="button" size="sm" variant="outline" onClick={exportExamples} disabled={busy === "export"}>
            {busy === "export" ? "Preparing…" : `Export ${withContent} example${withContent === 1 ? "" : "s"} (JSONL)`}
          </Button>
        )}
      </div>
      <p className="mb-2 text-xs text-muted">
        {reports.length === 0 ? (
          <>
            No reports yet. When a verdict is wrong, report it from the try-it box on{" "}
            <a className="underline underline-offset-2" href="/airlock#try-it">
              the Airlock page
            </a>{" "}
            or with <code className="font-mono">POST /v1/airlock/feedback</code>. Three reports naming the same rule
            become a suggestion here; a report that keeps its text tunes your deep scans and exports as a training
            example.
          </>
        ) : (
          <>
            <span className="font-mono text-ink">{reports.length}</span> report{reports.length === 1 ? "" : "s"} ·{" "}
            <span className="font-mono text-ink">{suggestions.length}</span> suggestion
            {suggestions.length === 1 ? "" : "s"} · <span className="font-mono text-ink">{withContent}</span> with text.
            {withContent > 0 && (
              <>
                {" "}
                Gemini is shown {inDeepScan === withContent ? (withContent === 1 ? "it" : `all ${withContent}`) : `the ${inDeepScan} most recent`}{" "}
                as worked answers on every deep scan on this account.
              </>
            )}{" "}
            Each suggestion shows the count behind it; nothing is applied until you say so.
          </>
        )}
      </p>
      {error && (
        <p role="status" className="mb-2 text-sm text-red-600">
          {error}
        </p>
      )}
      {done && (
        <p role="status" className="mb-2 text-xs text-emerald-700">
          {done}
        </p>
      )}

      {suggestions.length > 0 && (
        <ul className="mb-3 space-y-2">
          {suggestions.map((suggestion) => (
            <li
              key={`${suggestion.kind}-${suggestion.rule_id ?? suggestion.source}`}
              className="rounded-md border border-line bg-paper p-3 text-xs"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-ink">
                  {suggestion.kind === "mute_rule" ? `Mute ${suggestion.rule_id}` : `Deep scan for "${suggestion.source}"`}
                </span>
                <span className="text-muted">
                  {suggestion.reports} distinct scan{suggestion.reports === 1 ? "" : "s"} reported
                </span>
                {suggestion.kind === "mute_rule" && (
                  <Button
                    type="button"
                    size="sm"
                    className="ml-auto"
                    onClick={() => void mute(suggestion)}
                    disabled={busy === suggestion.rule_id}
                  >
                    {busy === suggestion.rule_id ? "Applying…" : "Mute this rule"}
                  </Button>
                )}
              </div>
              <p className="mt-1 leading-relaxed text-muted">{suggestion.detail}</p>
            </li>
          ))}
        </ul>
      )}

      {reports.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowReports((value) => !value)}
            className="mb-2 text-xs text-accent underline-offset-2 hover:underline"
            aria-expanded={showReports}
            aria-controls="airlock-tuning-reports"
          >
            {showReports ? "Hide reports" : `Show ${reports.length} report${reports.length === 1 ? "" : "s"}`}
          </button>
          {showReports && (
            <div id="airlock-tuning-reports" className="overflow-x-auto rounded-md border border-line">
              <table className="w-full text-left text-xs">
                <thead className="bg-paper text-muted">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">When</th>
                    <th className="px-3 py-1.5 font-medium">Given</th>
                    <th className="px-3 py-1.5 font-medium">Expected</th>
                    <th className="px-3 py-1.5 font-medium">Rules</th>
                    <th className="px-3 py-1.5 font-medium">Source</th>
                    <th className="px-3 py-1.5 font-medium">Text</th>
                    <th className="px-3 py-1.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {reports.map((report) => (
                    <tr key={report.id}>
                      <td className="px-3 py-1.5 font-mono whitespace-nowrap text-muted">{when(report.created_at)}</td>
                      <td className="px-3 py-1.5">
                        <Verdict value={report.verdict_given} />
                      </td>
                      <td className="px-3 py-1.5">
                        <Verdict value={report.verdict_expected} />
                      </td>
                      <td className="px-3 py-1.5 font-mono text-muted">{report.rule_ids.join(", ") || "—"}</td>
                      <td className="px-3 py-1.5 font-mono text-muted">{report.source ?? "—"}</td>
                      <td className="px-3 py-1.5 text-muted">{report.has_content ? "kept" : "hash only"}</td>
                      <td className="px-3 py-1.5 text-right">
                        <button
                          type="button"
                          onClick={() => void withdraw(report)}
                          disabled={busy === report.id}
                          className="text-accent underline-offset-2 hover:underline"
                          aria-label={`Withdraw report ${report.content_sha256.slice(0, 8)}`}
                        >
                          Withdraw
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
