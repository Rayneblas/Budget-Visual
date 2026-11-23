// Chart colors shared by every page (dashboard and setup preview), so a
// category keeps the same color everywhere.
// The 1st category gets the 1st color, the 2nd gets the 2nd, and so on.
// After 7 categories the colors repeat.
//
// None of these are red or pink: red only ever means overspending.
//          indigo     sky        teal       amber      purple     violet     lime
const CATEGORY_COLORS = ["#6366f1", "#0ea5e9", "#14b8a6", "#f59e0b", "#a855f7", "#8b5cf6", "#84cc16"];

// Red, used only for money spent beyond a category's plan
const OVER_COLOR = "#dc2626";

// Gray for the part of a chart that isn't a category
// ("Not spent yet" on the dashboard, "Unassigned" on both pages)
const EMPTY_COLOR = "#e5e7eb";

// Fully see-through, for the padding slices that make both rings the same scale
const TRANSPARENT = "rgba(0, 0, 0, 0)";

// Color for the category at position i (counting from 0)
function categoryColor(i) {
  return CATEGORY_COLORS[i % CATEGORY_COLORS.length];
}
