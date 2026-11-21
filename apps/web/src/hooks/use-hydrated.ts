"use client";
import * as React from "react";

/** False during SSR and the first client render; true once React has hydrated (event handlers are attached). */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = React.useState(false);
  React.useEffect(() => setHydrated(true), []);
  return hydrated;
}
