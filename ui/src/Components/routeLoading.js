export function getRouteLoadingLabel(pathname) {
  return pathname === "/" || pathname === "/home"
    ? "Loading dashboard"
    : "Loading page";
}
