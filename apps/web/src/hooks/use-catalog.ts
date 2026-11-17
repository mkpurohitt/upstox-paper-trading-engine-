"use client";
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api";

export function useIndicatorCatalog() {
  return useQuery({
    queryKey: ["indicator-catalog"],
    queryFn: () => unwrap(api.GET("/api/strategies/indicators")),
    staleTime: Infinity,
  });
}
