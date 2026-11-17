"use client";
import { Clock, CalendarDays, CandlestickChart, FolderTree, GitCompareArrows, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { DAYS, OP_LABEL, OPS, PATTERNS, PRICE_FIELDS, type Compare, type Condition, type DayCond, type Group, type Operand, type PatternCond, type TimeCond } from "@/lib/dsl";
import { cn } from "@/lib/utils";

function OperandPicker({ value, onChange, refs }: { value: Operand; onChange: (o: Operand) => void; refs: string[] }) {
  const type = value.type ?? "indicator";
  return (
    <div className="flex items-center gap-1">
      <Select
        ariaLabel="Operand type"
        className="h-8 w-[104px] text-xs"
        value={type}
        onValueChange={(t) =>
          onChange(t === "const" ? { type: "const", value: 0 } : t === "price" ? { type: "price", field: "close", offset: 0 } : { type: "indicator", ref: refs[0] ?? "", offset: 0 })
        }
        options={[
          { value: "indicator", label: "Indicator" },
          { value: "price", label: "Price" },
          { value: "const", label: "Value" },
        ]}
      />
      {value.type === "const" ? (
        <Input aria-label="Value" type="number" step="any" className="h-8 w-24 text-xs" value={value.value} onChange={(e) => onChange({ type: "const", value: Number(e.target.value) })} />
      ) : value.type === "price" ? (
        <Select ariaLabel="Price field" className="h-8 w-24 text-xs" value={value.field ?? "close"} onValueChange={(f) => onChange({ ...value, field: f as typeof value.field })} options={PRICE_FIELDS.map((f) => ({ value: f, label: f }))} />
      ) : (
        <Select
          ariaLabel="Indicator"
          className="h-8 w-36 text-xs"
          value={value.ref || undefined}
          placeholder="pick indicator"
          onValueChange={(r) => onChange({ ...value, type: "indicator", ref: r })}
          options={refs.map((r) => ({ value: r, label: r }))}
        />
      )}
      {value.type !== "const" && (
        <Input
          aria-label="Bars ago"
          title="Bars ago (0 = current bar)"
          type="number"
          min={0}
          max={50}
          className="h-8 w-14 text-xs"
          value={value.offset ?? 0}
          onChange={(e) => onChange({ ...value, offset: Math.max(0, Math.min(50, Number(e.target.value))) })}
        />
      )}
    </div>
  );
}

function newCondition(kind: string, refs: string[]): Condition {
  switch (kind) {
    case "time":
      return { kind: "time", after: "09:30", before: "15:00" };
    case "day_of_week":
      return { kind: "day_of_week", days: ["MON", "TUE", "WED", "THU", "FRI"] };
    case "pattern":
      return { kind: "pattern", name: "bullish_engulfing", lookback: 20 };
    case "group":
      return { kind: "any", conditions: [] };
    default:
      return {
        kind: "compare",
        left: refs[0] ? { type: "indicator", ref: refs[0], offset: 0 } : { type: "price", field: "close", offset: 0 },
        op: ">",
        right: refs[1] ? { type: "indicator", ref: refs[1], offset: 0 } : { type: "const", value: 0 },
      };
  }
}

function AddMenu({ onAdd, label = "Add condition" }: { onAdd: (k: string) => void; label?: string }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="xs" className="text-primary">
          <Plus /> {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={() => onAdd("compare")}>
          <GitCompareArrows /> Compare / crossover
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAdd("time")}>
          <Clock /> Time window
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAdd("day_of_week")}>
          <CalendarDays /> Day of week
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAdd("pattern")}>
          <CandlestickChart /> Price-action pattern
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAdd("group")}>
          <FolderTree /> Nested group (AND/OR)
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ConditionRow({ cond, onChange, onRemove, refs, depth }: { cond: Condition; onChange: (c: Condition) => void; onRemove: () => void; refs: string[]; depth: number }) {
  if (cond.kind === "all" || cond.kind === "any") {
    return <GroupEditor group={cond as Group} onChange={onChange} onRemove={onRemove} refs={refs} depth={depth + 1} />;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border bg-background/60 p-1.5">
      {cond.kind === "compare" && (
        <>
          <OperandPicker refs={refs} value={(cond as Compare).left as Operand} onChange={(o) => onChange({ ...(cond as Compare), left: o })} />
          <Select
            ariaLabel="Operator"
            className="h-8 w-[150px] text-xs font-medium"
            value={(cond as Compare).op}
            onValueChange={(op) => onChange({ ...(cond as Compare), op: op as Compare["op"] })}
            options={OPS.map((o) => ({ value: o, label: OP_LABEL[o] }))}
          />
          <OperandPicker refs={refs} value={(cond as Compare).right as Operand} onChange={(o) => onChange({ ...(cond as Compare), right: o })} />
        </>
      )}
      {cond.kind === "time" && (
        <div className="flex items-center gap-1.5 text-xs">
          <Clock className="h-3.5 w-3.5 text-muted-foreground" /> after
          <Input aria-label="After" type="time" className="h-8 w-28 text-xs" value={(cond as TimeCond).after ?? ""} onChange={(e) => onChange({ ...(cond as TimeCond), after: e.target.value || null })} />
          before
          <Input aria-label="Before" type="time" className="h-8 w-28 text-xs" value={(cond as TimeCond).before ?? ""} onChange={(e) => onChange({ ...(cond as TimeCond), before: e.target.value || null })} />
          <span className="text-muted-foreground">IST</span>
        </div>
      )}
      {cond.kind === "day_of_week" && (
        <div className="flex items-center gap-1">
          {DAYS.map((d) => {
            const on = (cond as DayCond).days.includes(d);
            return (
              <button
                key={d}
                type="button"
                aria-pressed={on}
                onClick={() => {
                  const days = on ? (cond as DayCond).days.filter((x) => x !== d) : [...(cond as DayCond).days, d];
                  if (days.length) onChange({ ...(cond as DayCond), days });
                }}
                className={cn("rounded px-2 py-1 text-2xs font-medium", on ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground")}
              >
                {d}
              </button>
            );
          })}
        </div>
      )}
      {cond.kind === "pattern" && (
        <div className="flex items-center gap-1.5 text-xs">
          <Select ariaLabel="Pattern" className="h-8 w-48 text-xs" value={(cond as PatternCond).name} onValueChange={(n) => onChange({ ...(cond as PatternCond), name: n as PatternCond["name"] })} options={PATTERNS.map((p) => ({ value: p, label: p.replace(/_/g, " ") }))} />
          {((cond as PatternCond).name === "breakout_high" || (cond as PatternCond).name === "breakdown_low") && (
            <>
              lookback
              <Input aria-label="Lookback" type="number" className="h-8 w-16 text-xs" value={(cond as PatternCond).lookback ?? 20} onChange={(e) => onChange({ ...(cond as PatternCond), lookback: Number(e.target.value) })} />
            </>
          )}
        </div>
      )}
      <Button variant="ghost" size="icon-sm" className="ml-auto text-muted-foreground hover:text-loss" onClick={onRemove} aria-label="Remove condition">
        <Trash2 />
      </Button>
    </div>
  );
}

export function GroupEditor({ group, onChange, onRemove, refs, depth = 0 }: { group: Group; onChange: (g: Group) => void; onRemove?: () => void; refs: string[]; depth?: number }) {
  const conds = (group.conditions ?? []) as Condition[];
  const set = (i: number, c: Condition) => onChange({ ...group, conditions: conds.map((x, j) => (j === i ? c : x)) as Group["conditions"] });
  const remove = (i: number) => onChange({ ...group, conditions: conds.filter((_, j) => j !== i) as Group["conditions"] });
  return (
    <div className={cn("flex flex-col gap-1.5 rounded-lg", depth > 0 && "border border-dashed border-primary/30 bg-primary/[0.03] p-2")}>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">Match</span>
        <div className="inline-flex rounded-md bg-muted p-0.5" role="radiogroup" aria-label="Group logic">
          {(["all", "any"] as const).map((k) => (
            <button key={k} type="button" role="radio" aria-checked={group.kind === k} onClick={() => onChange({ ...group, kind: k })} className={cn("rounded px-2 py-0.5 text-2xs font-semibold uppercase", group.kind === k ? "bg-background text-foreground shadow" : "text-muted-foreground")}>
              {k === "all" ? "all (AND)" : "any (OR)"}
            </button>
          ))}
        </div>
        {onRemove && (
          <Button variant="ghost" size="xs" className="ml-auto text-muted-foreground" onClick={onRemove}>
            <Trash2 /> group
          </Button>
        )}
      </div>
      {conds.map((c, i) => (
        <ConditionRow key={i} cond={c} refs={refs} depth={depth} onChange={(x) => set(i, x)} onRemove={() => remove(i)} />
      ))}
      <div>
        <AddMenu onAdd={(k) => onChange({ ...group, conditions: [...conds, newCondition(k, refs)] as Group["conditions"] })} />
      </div>
    </div>
  );
}
