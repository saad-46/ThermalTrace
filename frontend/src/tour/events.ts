/** Window events the tour uses to drive existing components without coupling them to the tour. */
export const TOUR_SEARCH_EVENT = "thermaltrace:tour-search";

/** Show search results for `query`; an empty string clears the box and closes the results. */
export function demoSearch(query: string): void {
  window.dispatchEvent(new CustomEvent(TOUR_SEARCH_EVENT, { detail: query }));
}
