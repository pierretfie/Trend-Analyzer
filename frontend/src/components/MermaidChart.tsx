import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
  flowchart: { htmlLabels: true, curve: "basis" },
});

let idCounter = 0;

/** Remove any orphaned Mermaid error/work divs that got injected into <body>. */
function cleanupMermaidBodyDivs(id: string) {
  // Mermaid 11 injects a work div into body; clean it up after render.
  document
    .querySelectorAll<HTMLElement>(`#${id}, #d${id}, [id^="mermaid-"]`)
    .forEach((el) => {
      // Only remove elements that are direct children of body (orphans).
      if (el.parentElement === document.body) {
        el.remove();
      }
    });
}

/** Fix common LLM-generated Mermaid syntax issues before handing to the parser. */
function sanitizeMermaid(raw: string): string {
  return (
    raw
      // Decode HTML arrow entities the LLM sometimes emits
      .replace(/&ndash;&gt;/g, "-->")
      .replace(/&mdash;&gt;/g, "-->")
      .replace(/&#45;&#45;&gt;/g, "-->")
      .replace(/&minus;&minus;&gt;/g, "-->")
      .replace(/–>/g, "-->")
      .replace(/—>/g, "-->")
      // Decode other common HTML entities inside labels
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      // Mermaid 11 is strict about bare parens/brackets in unquoted labels —
      // wrap any unquoted node label that contains special chars in double-quotes.
      .replace(
        /(\b\w+)\[([^\]"]+[()&|{}/\\][^\]"]*)\]/g,
        (_, id, label) => `${id}["${label.replace(/"/g, "'")}"]`,
      )
      .replace(
        /(\b\w+)\(([^)"]+[[\]&|{}/\\][^)"]*)\)/g,
        (_, id, label) => `${id}("${label.replace(/"/g, "'")}}")`,
      )
      // Trim trailing whitespace per line (can cause parse failures)
      .split("\n")
      .map((l) => l.trimEnd())
      .join("\n")
      .trim()
  );
}

/** Try progressively simpler versions of the diagram until one parses. */
async function tryRender(raw: string): Promise<string> {
  const attempts: string[] = [
    sanitizeMermaid(raw),
    // Strip subgraph blocks — common LLM mistake
    sanitizeMermaid(raw.replace(/subgraph[\s\S]*?end\b/gim, "").trim()),
    // Strip click/callback directives
    sanitizeMermaid(raw.replace(/^\s*click\s+.+$/gim, "").trim()),
    // Keep only the first block type declaration + simple node lines
    sanitizeMermaid(
      raw
        .split("\n")
        .filter((l) => !/^\s*(style|classDef|class|linkStyle)\s/i.test(l))
        .join("\n"),
    ),
  ];

  let lastErr: unknown;
  for (const attempt of attempts) {
    if (!attempt) continue;
    const id = `mermaid-${++idCounter}`;
    try {
      const { svg } = await mermaid.render(id, attempt);
      cleanupMermaidBodyDivs(id);
      return svg;
    } catch (err) {
      cleanupMermaidBodyDivs(id);
      lastErr = err;
    }
  }
  throw lastErr;
}

/** One-time global sweep — removes any bomb divs already in <body> from prior renders. */
function sweepOrphanedMermaidDivs() {
  document.querySelectorAll<HTMLElement>("[id^='mermaid-']").forEach((el) => {
    if (el.parentElement === document.body) el.remove();
  });
}

export function MermaidChart({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svgContent, setSvgContent] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  // Sweep any pre-existing orphaned Mermaid divs on first mount.
  useEffect(() => {
    sweepOrphanedMermaidDivs();
  }, []);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;

    setSvgContent("");
    setError(null);

    void (async () => {
      try {
        const svg = await tryRender(code);
        if (!cancelled) {
          setSvgContent(svg);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : "Syntax error in diagram.";
          setError(
            (msg.split("\n")[0] ?? msg).replace(/^Error:\s*/i, "").trim() ||
              "Diagram syntax error.",
          );
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <div className="my-4 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-3 text-xs font-mono">
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-amber-400 font-semibold">
            ⚠ Diagram could not be rendered
          </span>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="text-[10px] text-slate-500 hover:text-slate-300 transition"
          >
            {collapsed ? "show source ▾" : "hide source ▴"}
          </button>
        </div>
        <p className="text-slate-400 mb-2 text-[11px]">{error}</p>
        {!collapsed && (
          <pre className="overflow-x-auto whitespace-pre-wrap text-slate-500 text-[11px] leading-relaxed border-t border-white/[0.06] pt-2 mt-1">
            {code}
          </pre>
        )}
      </div>
    );
  }

  if (!svgContent) {
    return (
      <div className="my-4 rounded-xl border border-white/[0.08] bg-surface-900/50 p-4 flex justify-center">
        <span className="text-xs text-slate-600 animate-pulse">
          Rendering diagram…
        </span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="my-4 overflow-x-auto rounded-xl border border-white/[0.08] bg-surface-900/50 p-4 flex justify-center mermaid-container"
      dangerouslySetInnerHTML={{ __html: svgContent }}
    />
  );
}
