/** Renders the active tour step over the real UI: a non-blocking spotlight on the target and an explanation
 *  card (popover on desktop/tablet, bottom sheet on phones). The app underneath stays usable. */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMedia } from "../lib/session";
import { GLOSSARY } from "./glossary";
import { placePopover, waitForTarget, type Box } from "./target";
import { resolveTarget, useTour } from "./TourProvider";

type Found = { el: HTMLElement | null; stepId: string };

function useTargetBox(el: HTMLElement | null): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!el) { setBox(null); return; }
    let raf = 0;
    const tick = () => {
      const r = el.getBoundingClientRect();
      setBox((b) => (b && b.top === r.top && b.left === r.left && b.width === r.width && b.height === r.height ? b : { top: r.top, left: r.left, width: r.width, height: r.height }));
      raf = requestAnimationFrame(tick); // follows scrolling, resizing and layout shifts
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [el]);
  return box;
}

export default function TourOverlay() {
  const { tour, step, index, status, ctx, next, back, skip, restart, close } = useTour();
  const reduceMotion = useMedia("(prefers-reduced-motion: reduce)");
  const [found, setFound] = useState<Found | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const [cardSize, setCardSize] = useState({ w: 360, h: 220 });
  const targetId = step ? resolveTarget(step, ctx) : null;

  // Undo a step's side effect (e.g. open search results) when the tour moves on or closes.
  useEffect(() => {
    const leaving = step;
    return () => leaving?.cleanup?.();
  }, [step]);

  // Find the target once its page has rendered; fall back to an unanchored card if it never appears.
  useEffect(() => {
    if (!step) { setFound(null); return; }
    let cancelled = false;
    setFound(null);
    if (!targetId) { setFound({ el: null, stepId: step.id }); return; }
    waitForTarget(targetId).then((el) => {
      if (cancelled) return;
      document.querySelectorAll("[data-tour-active]").forEach((n) => n.removeAttribute("data-tour-active"));
      if (el) {
        el.setAttribute("data-tour-active", "");
        el.scrollIntoView({ block: ctx.isMobile ? "start" : "center", inline: "center", behavior: reduceMotion ? "auto" : "smooth" });
        step.action?.(ctx);
      }
      setFound({ el, stepId: step.id });
    });
    return () => { cancelled = true; };
  }, [step, targetId, ctx, reduceMotion]);

  useEffect(() => () => document.querySelectorAll("[data-tour-active]").forEach((n) => n.removeAttribute("data-tour-active")), []);

  const el = found && step && found.stepId === step.id ? found.el : null;
  const box = useTargetBox(el);

  // Pages keep loading after the target first appears; if that pushes the target off-screen, bring it back.
  // Driven by layout changes (ResizeObserver) during a short settling window, not by fixed delays.
  useEffect(() => {
    if (!el) return;
    const settleUntil = performance.now() + 3000;
    const ro = new ResizeObserver(() => {
      if (performance.now() > settleUntil) { ro.disconnect(); return; }
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) el.scrollIntoView({ block: ctx.isMobile ? "start" : "center", inline: "center", behavior: "auto" });
    });
    ro.observe(document.body);
    const stop = window.setTimeout(() => ro.disconnect(), 3100);
    return () => { ro.disconnect(); window.clearTimeout(stop); };
  }, [el, ctx.isMobile]);

  useLayoutEffect(() => {
    if (!cardRef.current) return;
    const r = cardRef.current.getBoundingClientRect();
    if (Math.abs(r.width - cardSize.w) > 1 || Math.abs(r.height - cardSize.h) > 1) setCardSize({ w: r.width, h: r.height });
  });

  // Focus the step title for screen readers and keyboard users, without scrolling the page.
  useEffect(() => { if (found && step) titleRef.current?.focus({ preventScroll: true }); }, [found, step]);

  useEffect(() => {
    if (!tour || status === "closed") return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (status === "running" && e.key === "ArrowRight") { e.preventDefault(); next(); }
      else if (status === "running" && e.key === "ArrowLeft") { e.preventDefault(); back(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tour, status, next, back, close]);

  if (!tour || status === "closed") return null;

  if (status === "done") {
    return createPortal(
      <div className={`tour-card tour-center ${ctx.isMobile ? "tour-sheet" : ""}`} role="dialog" aria-modal="false" aria-labelledby="tour-done-title">
        <h2 id="tour-done-title" ref={titleRef} tabIndex={-1}>{tour.label} tour complete</h2>
        <p>{tour.summary.lead}</p>
        <ol className="tour-flow" aria-label="Workflow">
          {tour.summary.flow.map((s) => <li key={s}>{s}</li>)}
        </ol>
        <div className="tour-actions">
          <button className="btn" onClick={restart}>Restart {tour.label.toLowerCase()} tour</button>
          <button className="btn primary" onClick={close}>Explore ThermalTrace</button>
        </div>
      </div>,
      document.body,
    );
  }

  if (!step || !found || found.stepId !== step.id) {
    return createPortal(<div className="tour-loading" role="status" aria-live="polite">Loading the next part of the tour…</div>, document.body);
  }

  const body = typeof step.body === "function" ? step.body(ctx) : step.body;
  const missingEvent = step.needsEvent && !ctx.featured;
  const missingTarget = !missingEvent && targetId && !el;
  const vw = window.innerWidth, vh = window.innerHeight;
  const pad = 6;
  const spot = box ? { top: box.top - pad, left: box.left - pad, width: box.width + pad * 2, height: box.height + pad * 2 } : null;
  const pos = !ctx.isMobile && spot ? placePopover(spot, cardSize.w, cardSize.h, vw, vh) : null;
  // Phones: the sheet normally sits at the bottom; if the target itself lives down there (e.g. the map's
  // event sheet, which cannot scroll), put the explanation at the top so it never covers what it describes.
  const sheetAtTop = ctx.isMobile && !!spot && spot.top + spot.height / 2 > vh * 0.55;
  const terms = (step.terms ?? []).map((k) => GLOSSARY[k]).filter(Boolean);

  return createPortal(
    <>
      {spot && <div className={`tour-spotlight ${reduceMotion ? "" : "animate"}`} aria-hidden style={{ top: spot.top, left: spot.left, width: spot.width, height: spot.height }} />}
      <div ref={cardRef} className={`tour-card ${ctx.isMobile ? `tour-sheet${sheetAtTop ? " at-top" : ""}` : pos ? "" : "tour-center"}`} role="dialog" aria-modal="false"
        aria-labelledby="tour-step-title" aria-describedby="tour-step-body" data-placement={pos?.placement}
        style={pos ? { top: pos.top, left: pos.left } : undefined}>
        <div className="tour-progress">Step {index + 1} of {tour.steps.length} · {tour.label} tour</div>
        <h2 id="tour-step-title" ref={titleRef} tabIndex={-1}>{step.title}</h2>
        <p id="tour-step-body">{missingEvent ? step.fallback ?? body : body}</p>
        {missingTarget && <p className="tour-note">This part of the screen is not available right now, so it is described here instead.</p>}
        {step.why && !missingEvent && <div className="tour-why"><b>Why this matters.</b> {step.why}</div>}
        {step.limits && !missingEvent && <div className="tour-limit"><b>Limitation.</b> {step.limits}</div>}
        {(step.learnMore || step.how || terms.length > 0) && (
          <details className="tour-more">
            <summary>{terms.length ? `Learn more · ${terms.map((t) => t.term).join(", ")}` : "Learn more"}</summary>
            {step.how && <p><b>How it is generated.</b> {step.how}</p>}
            {step.learnMore && <p>{step.learnMore}</p>}
            {terms.length > 0 && <dl>{terms.map((t) => <div key={t.term}><dt>{t.term}</dt><dd>{t.definition}</dd></div>)}</dl>}
          </details>
        )}
        <div className="tour-actions">
          <button className="btn ghost sm" onClick={skip}>Skip tour</button>
          <span className="spacer" />
          <button className="btn sm" onClick={back} disabled={index === 0}>Back</button>
          <button className="btn primary sm" onClick={next}>{index === tour.steps.length - 1 ? "Finish" : "Next"}</button>
        </div>
      </div>
    </>,
    document.body,
  );
}
