/** Locating tour targets in the real UI: event-driven waiting (MutationObserver), no fixed sleeps. */

/** Attribute selector for a tour id (ids are our own constants; quotes and backslashes are escaped anyway). */
export const selector = (id: string) => `[data-tour-id="${id.replace(/["\\]/g, (c) => `\\${c}`)}"]`;

function visible(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

/** Resolve when an element with `data-tour-id=id` is mounted and has a size, or null after `timeoutMs`. */
export function waitForTarget(id: string, timeoutMs = 15_000, root: ParentNode = document): Promise<HTMLElement | null> {
  const find = () => {
    const el = root.querySelector<HTMLElement>(selector(id));
    return el && visible(el) ? el : null;
  };
  const now = find();
  if (now) return Promise.resolve(now);
  return new Promise((resolve) => {
    let done = false;
    const finish = (el: HTMLElement | null) => {
      if (done) return;
      done = true;
      observer.disconnect();
      window.clearTimeout(timer);
      resolve(el);
    };
    const observer = new MutationObserver(() => {
      const el = find();
      if (el) finish(el);
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-tour-id", "class", "style"] });
    const timer = window.setTimeout(() => finish(find()), timeoutMs);
  });
}

export interface Box { top: number; left: number; width: number; height: number }

export interface PopoverPosition { top: number; left: number; placement: "top" | "bottom" | "left" | "right" | "inside" }

/** Place a popover of size (w, h) next to `target` inside a viewport (vw, vh), never outside it. */
export function placePopover(target: Box, w: number, h: number, vw: number, vh: number, gap = 12, margin = 12): PopoverPosition {
  const clampX = (x: number) => Math.max(margin, Math.min(x, vw - w - margin));
  const clampY = (y: number) => Math.max(margin, Math.min(y, vh - h - margin));
  const cx = target.left + target.width / 2 - w / 2;
  const cy = target.top + target.height / 2 - h / 2;
  const below = vh - (target.top + target.height);
  const above = target.top;
  const right = vw - (target.left + target.width);
  if (target.height < vh * 0.6) {
    if (below >= h + gap + margin) return { top: clampY(target.top + target.height + gap), left: clampX(cx), placement: "bottom" };
    if (above >= h + gap + margin) return { top: clampY(target.top - h - gap), left: clampX(cx), placement: "top" };
  }
  if (right >= w + gap + margin) return { top: clampY(cy), left: target.left + target.width + gap, placement: "right" };
  if (target.left >= w + gap + margin) return { top: clampY(cy), left: target.left - w - gap, placement: "left" };
  // Large targets (e.g. the map): sit inside the top-right corner of the target, still within the viewport.
  return { top: clampY(Math.max(target.top, 0) + margin), left: clampX(target.left + target.width - w - margin), placement: "inside" };
}
