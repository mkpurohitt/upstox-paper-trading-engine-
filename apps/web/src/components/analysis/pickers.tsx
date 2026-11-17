"use client";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { Field } from "@/components/dashboard";
import { Select } from "@/components/ui/select";
import { apiJson } from "@/lib/api";
import { shortDate } from "@/lib/format";

export const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK", "BAJFINANCE"];

export function UnderlyingExpiry({
  underlying,
  setUnderlying,
  expiry,
  setExpiry,
}: {
  underlying: string;
  setUnderlying: (u: string) => void;
  expiry: string | undefined;
  setExpiry: (e: string | undefined) => void;
}) {
  const exp = useQuery({ queryKey: ["expiries", underlying], queryFn: () => apiJson<string[]>(`/api/market/expiries?underlying=${underlying}`) });
  React.useEffect(() => setExpiry(undefined), [underlying, setExpiry]);
  return (
    <>
      <Field label="Underlying">
        <Select value={underlying} onValueChange={setUnderlying} options={UNDERLYINGS.map((u) => ({ value: u, label: u }))} />
      </Field>
      <Field label="Expiry">
        <Select value={expiry ?? exp.data?.[0]} onValueChange={setExpiry} options={(exp.data ?? []).map((e) => ({ value: e, label: shortDate(e) }))} />
      </Field>
    </>
  );
}
