/** ThermalTrace identity marks: the flame and the outline of India. Plain SVG, no assets to load. */
import { useId } from "react";

export const FLAME_OUTER = "M12.6 2.2c.5 2.9-.6 4.6-2 6.3-1.5 1.8-3.3 3.6-3.3 6.8 0 3.6 2.6 6.5 6 6.5 3.5 0 6.2-2.7 6.2-6.4 0-2.9-1.4-4.9-2.7-6.4-.3 1.4-1 2.4-2.1 3 .3-3.6-.5-7.2-2.1-9.8z";
export const FLAME_INNER = "M12.3 12.4c-.2 1.3-1.1 2-1.7 2.9-.5.7-.8 1.4-.8 2.3 0 1.6 1.2 2.8 2.7 2.8s2.7-1.2 2.7-2.9c0-1.4-.8-2.4-1.5-3.2-.1.7-.5 1.2-1 1.4.1-1.2-.1-2.3-.4-3.3z";

/** Flame glyph (24x24 box, base at the bottom centre). Decorative unless a `title` is given. */
export function Flame({ size = 16, title, className = "" }: { size?: number; title?: string; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={`tt-flame ${className}`} role={title ? "img" : undefined}
      aria-label={title} aria-hidden={title ? undefined : true}>
      <defs>
        <linearGradient id={`f${id}`} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#ff5a1f" />
          <stop offset="60%" stopColor="#ff8a3d" />
          <stop offset="100%" stopColor="#ffc46b" />
        </linearGradient>
      </defs>
      <path d={FLAME_OUTER} fill={`url(#f${id})`} />
      <path d={FLAME_INNER} fill="#ffe7c2" opacity="0.9" />
    </svg>
  );
}

/**
 * Outline of mainland India, drawn to scale (equirectangular at 21.4 deg N; 68.77-97.04 deg E, 7.95-34.85 deg N).
 * Derived from GeoNames populated places coded IN (CC BY 4.0) already in this database: places were binned on a 0.2 deg
 * grid, the occupied cells merged, smoothed (buffer, Chaikin) and simplified with PostGIS. It follows the extent of
 * populated places, so it is an approximate outline, not an official boundary: in the north it does not show the full
 * boundary depicted on Survey of India maps, and islands are omitted. Replace INDIA_PATH with an official outline if one
 * is required.
 */
export const INDIA_VIEWBOX = "0 0 100 102.2";
export const INDIA_PATH =
  "M0.3 46.7 L0.8 45.9 L0.9 45.4 L0.8 45.0 L0.2 44.5 L0.0 43.9 L0.1 42.3 L0.4 41.8 L0.9 42.0 L1.2 42.8 L1.8 43.2 L3.7 43.3 L5.0 42.7 L6.3 42.6 L7.2 42.8 L7.9 43.7 L8.5 44.1 L9.3 44.2 L9.9 44.0 L10.2 43.5 L10.2 42.9 L9.4 41.4 L9.1 40.6 L9.2 39.9 L9.6 39.0 L9.8 38.1 L9.5 37.3 L8.5 35.2 L8.4 34.6 L8.6 34.2 L9.3 33.5 L9.8 33.5 L10.3 33.7 L10.5 34.1 L10.1 34.7 L10.1 35.2 L10.3 35.9 L10.9 36.4 L11.7 36.3 L12.0 36.0 L12.2 35.5 L11.7 34.2 L11.7 33.8 L12.1 33.5 L13.8 33.3 L14.2 33.1 L15.1 32.0 L16.2 31.8 L16.7 31.2 L16.8 29.9 L16.5 28.9 L15.5 27.6 L14.3 26.8 L14.2 24.7 L13.5 23.7 L13.4 23.3 L13.6 23.0 L14.7 22.7 L15.3 22.2 L16.0 20.7 L16.4 18.4 L17.7 17.5 L18.4 16.2 L19.6 14.4 L19.9 13.4 L19.8 11.8 L20.6 10.3 L20.5 9.5 L19.1 6.9 L18.8 5.6 L17.9 4.0 L17.7 1.5 L18.1 0.0 L18.7 0.1 L19.4 0.6 L21.5 1.0 L22.4 1.9 L23.5 2.5 L23.9 4.4 L24.2 4.9 L25.3 6.0 L26.1 8.0 L27.1 9.1 L27.9 9.4 L28.3 9.3 L29.1 8.5 L29.6 8.4 L29.8 8.6 L30.2 10.9 L31.0 11.8 L31.9 12.3 L32.4 14.0 L33.9 14.5 L35.7 14.5 L36.4 14.7 L37.3 15.6 L38.3 16.1 L38.8 17.8 L39.8 18.7 L40.5 18.7 L41.2 18.3 L41.8 18.3 L42.0 18.6 L41.9 19.2 L40.7 21.8 L40.8 22.8 L41.8 23.6 L42.8 24.9 L44.0 25.2 L47.8 27.2 L49.7 27.5 L50.5 27.8 L52.2 27.4 L54.2 28.7 L56.3 29.1 L58.3 30.2 L59.6 30.5 L60.4 31.0 L61.8 31.3 L62.6 31.8 L63.5 31.8 L64.9 31.2 L66.0 31.9 L66.6 32.0 L67.6 31.4 L68.0 29.7 L68.4 29.1 L68.6 28.3 L69.2 27.7 L69.8 27.4 L70.2 27.5 L71.8 29.4 L73.0 29.8 L73.7 30.9 L78.2 31.1 L81.0 30.7 L81.5 30.1 L81.6 29.6 L81.3 28.9 L80.7 28.2 L80.6 27.8 L80.8 27.4 L81.4 27.4 L82.5 28.0 L83.6 28.2 L84.8 28.2 L85.6 28.0 L86.1 27.3 L86.5 26.0 L87.1 25.9 L88.1 26.9 L88.8 26.8 L89.8 25.7 L90.0 24.0 L90.6 23.7 L91.9 23.7 L93.1 22.8 L94.4 23.3 L96.1 22.8 L96.4 23.2 L96.7 24.1 L97.2 24.8 L98.5 25.2 L99.8 26.0 L100.0 26.3 L99.9 26.7 L99.7 26.8 L98.4 26.6 L97.6 26.9 L97.3 27.5 L97.0 28.9 L96.3 29.6 L94.6 30.4 L93.4 31.8 L92.3 34.1 L91.3 35.8 L91.2 36.3 L91.4 38.2 L90.9 39.3 L90.8 40.0 L90.2 40.5 L87.9 40.7 L87.2 41.1 L87.0 41.9 L87.2 43.2 L86.7 44.5 L86.5 46.8 L86.2 47.5 L85.7 47.8 L85.1 48.8 L84.7 49.0 L84.5 49.0 L84.3 48.5 L84.3 46.7 L83.1 45.2 L82.6 44.9 L81.3 45.0 L80.5 44.9 L79.7 44.2 L79.3 43.2 L79.2 42.0 L79.5 40.8 L80.2 40.3 L81.2 40.2 L81.8 39.9 L82.3 39.0 L82.2 38.5 L82.0 38.1 L80.9 37.6 L80.2 36.4 L79.6 36.2 L78.6 36.4 L77.9 37.5 L77.3 37.5 L76.6 36.3 L75.1 36.1 L74.4 35.7 L73.8 34.3 L72.2 33.1 L71.3 32.9 L70.4 33.4 L70.1 33.8 L70.1 34.4 L71.0 35.9 L71.0 36.4 L70.8 36.7 L69.7 37.2 L69.4 38.0 L69.6 38.8 L70.6 39.5 L70.9 40.2 L71.0 42.9 L71.6 44.2 L71.7 45.4 L71.6 46.9 L71.2 48.0 L69.9 49.1 L67.3 50.4 L65.3 50.8 L64.6 51.2 L64.2 52.1 L63.9 54.4 L63.6 55.6 L62.3 56.3 L61.3 57.8 L60.8 58.0 L59.7 58.0 L59.0 58.1 L58.1 59.5 L57.2 60.0 L56.8 60.3 L56.0 61.8 L55.3 62.1 L54.1 63.2 L53.1 63.8 L52.1 65.4 L49.2 67.0 L48.8 67.5 L48.4 69.1 L47.9 69.9 L45.3 70.6 L43.8 71.7 L42.2 72.3 L41.1 73.4 L40.3 75.0 L40.2 75.9 L40.5 77.3 L40.5 79.8 L41.2 81.5 L41.3 83.3 L41.1 84.7 L39.8 87.7 L39.8 91.7 L39.6 93.4 L39.3 93.8 L38.2 94.1 L37.3 95.1 L37.2 95.6 L37.7 97.0 L37.6 97.4 L35.5 97.8 L34.3 98.5 L33.7 99.1 L33.5 100.1 L33.1 100.8 L31.6 101.9 L30.7 102.2 L29.8 102.1 L28.5 101.4 L27.9 100.2 L27.1 99.2 L26.6 97.4 L26.2 96.7 L26.0 94.7 L24.8 92.1 L24.6 90.9 L23.4 89.1 L22.9 88.0 L21.9 86.8 L21.6 85.9 L21.3 85.4 L21.1 84.2 L20.5 82.7 L20.3 80.9 L19.9 80.1 L19.5 78.5 L17.1 74.0 L16.7 72.4 L16.3 71.7 L16.2 69.7 L15.7 68.8 L15.4 67.1 L14.9 66.4 L14.7 64.6 L14.1 62.8 L13.9 60.4 L13.5 59.4 L13.4 56.4 L14.0 54.1 L13.7 53.1 L13.0 52.3 L12.1 52.1 L11.4 52.3 L10.0 53.5 L8.6 54.2 L7.2 54.3 L6.2 54.1 L4.5 53.0 L3.8 51.0 L2.6 50.1 L0.9 48.5 L0.0 48.0 L0.0 47.4 L0.3 46.7Z";

export function IndiaOutline({ size = 40, className = "", title }: { size?: number; className?: string; title?: string }) {
  return (
    <svg viewBox={INDIA_VIEWBOX} width={size} height={size * 1.022} className={`tt-india ${className}`}
      role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <path d={INDIA_PATH} className="tt-india-land" />
    </svg>
  );
}
