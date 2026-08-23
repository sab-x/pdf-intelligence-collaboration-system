import { formatBytes, type LibraryStats } from "@/lib/documents";
import { cn } from "@/lib/utils";

/**
 * Quiet metric tiles, not KPI cards. The restraint is the point: these are
 * reference numbers you glance at, so the label carries the mono/small-caps
 * treatment and only the figure gets scale. No borders between tiles beyond a
 * hairline rule, no icons, no colour — the grid below is what should draw the
 * eye.
 */
function Stat({
  label,
  value,
  suffix,
}: {
  label: string;
  value: string;
  suffix?: string;
}) {
  return (
    <div className="flex-1 px-5 py-4 first:pl-6 last:pr-6 sm:px-6">
      <dt className="meta">{label}</dt>
      <dd className="mt-1.5 font-display text-2xl leading-none tracking-tight tabular-nums">
        {value}
        {suffix && (
          <span className="ml-1.5 font-mono text-xs tracking-normal text-muted-foreground">
            {suffix}
          </span>
        )}
      </dd>
    </div>
  );
}

export function StatStrip({
  stats,
  className,
}: {
  stats: LibraryStats;
  className?: string;
}) {
  const storage = formatBytes(stats.storageBytes);
  // formatBytes returns e.g. "1.4 MB" — split so the unit can be de-emphasised
  // and the figure stays on the serif scale.
  const [storageValue, storageUnit] = storage.split(" ");

  return (
    <dl
      className={cn(
        "flex divide-x divide-border overflow-hidden rounded-xl border border-border bg-card/70",
        className,
      )}
    >
      <Stat label="Documents" value={String(stats.total)} />
      <Stat label="Storage used" value={storageValue} suffix={storageUnit} />
      <Stat
        label="This week"
        value={String(stats.uploadsThisWeek)}
        suffix={stats.uploadsThisWeek === 1 ? "upload" : "uploads"}
      />
      {/* Only surfaces while something is genuinely mid-ingestion, so the
          strip doesn't carry a permanent "0 processing" that means nothing. */}
      {stats.processing > 0 && (
        <Stat label="Processing" value={String(stats.processing)} suffix="now" />
      )}
    </dl>
  );
}
