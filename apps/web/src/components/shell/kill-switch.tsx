"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, ShieldCheck } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tooltip } from "@/components/ui/tooltip";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";

interface KillState {
  user_engaged: boolean;
  global_engaged: boolean;
}

export function useKillSwitch() {
  return useQuery({
    queryKey: ["kill-switch"],
    queryFn: () => apiJson<KillState>("/api/risk/kill-switch"),
    refetchInterval: 30_000,
    retry: false,
  });
}

export function KillSwitchDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const { data } = useKillSwitch();
  const engaged = !!data?.user_engaged;
  const m = useMutation({
    mutationFn: (engage: boolean) =>
      apiJson<KillState>("/api/risk/kill-switch", { method: "POST", body: JSON.stringify({ engaged: engage, square_off: engage }) }),
    onSuccess: (s) => {
      qc.setQueryData(["kill-switch"], s);
      qc.invalidateQueries({ queryKey: ["deployments"] });
      toast[s.user_engaged ? "error" : "success"](
        s.user_engaged ? "Kill switch engaged — orders blocked, strategies halted" : "Kill switch released",
      );
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <OctagonX className="h-5 w-5 text-loss" /> {engaged ? "Release kill switch?" : "Engage kill switch?"}
          </DialogTitle>
          <DialogDescription>
            {engaged
              ? "New orders will be accepted again. Stopped strategies stay stopped until you restart them."
              : "Immediately blocks every new order, cancels open orders, squares off open intraday positions (paper & live) and stops all running strategies. This action is audited."}
          </DialogDescription>
        </DialogHeader>
        {data?.global_engaged ? (
          <p className="rounded-md bg-loss/10 p-2 text-xs text-loss">A platform-wide kill switch is engaged by an administrator.</p>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant={engaged ? "default" : "destructive"} loading={m.isPending} onClick={() => m.mutate(!engaged)}>
            {engaged ? "Release" : "Engage kill switch"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function KillSwitchButton({ onClick }: { onClick: () => void }) {
  const { data } = useKillSwitch();
  const engaged = !!(data?.user_engaged || data?.global_engaged);
  return (
    <Tooltip content={engaged ? "Kill switch engaged" : "Emergency kill switch"}>
      <Button
        size="sm"
        variant={engaged ? "destructive" : "outline"}
        onClick={onClick}
        className={cn("gap-1.5", !engaged && "border-loss/40 text-loss hover:bg-loss/10 hover:text-loss")}
        aria-label="Kill switch"
      >
        {engaged ? <OctagonX /> : <ShieldCheck />}
        <span className="hidden lg:inline">{engaged ? "KILLED" : "Kill switch"}</span>
      </Button>
    </Tooltip>
  );
}
