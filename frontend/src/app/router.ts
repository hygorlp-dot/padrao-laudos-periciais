import { useEffect, useState, type MouseEvent } from "react";

const ROUTE_CHANGE_EVENT = "arcd:navigate";

export function useCurrentPath() {
  const [currentPath, setCurrentPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const updatePath = () => setCurrentPath(window.location.pathname);
    window.addEventListener("popstate", updatePath);
    window.addEventListener(ROUTE_CHANGE_EVENT, updatePath);
    return () => {
      window.removeEventListener("popstate", updatePath);
      window.removeEventListener(ROUTE_CHANGE_EVENT, updatePath);
    };
  }, []);

  return currentPath;
}

export function navigate(event: MouseEvent<HTMLAnchorElement>) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }

  const destination = new URL(event.currentTarget.href);
  if (destination.origin !== window.location.origin) {
    return;
  }

  event.preventDefault();
  if (destination.pathname !== window.location.pathname) {
    window.history.pushState(null, "", destination.pathname);
    window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT));
  }
}
