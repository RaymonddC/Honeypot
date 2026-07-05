export function ScreenPlaceholder({
  title,
  module,
  phase,
  blurb,
}: {
  title: string;
  module: string;
  phase: string;
  blurb: string;
}) {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="eyebrow mb-1">{module}</div>
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>

      <div className="mt-6 rounded-card border border-line bg-card p-8">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
          <span className="font-mono text-xs text-accent-bright">
            coming in {phase}
          </span>
        </div>
        <p className="mt-3 text-sm leading-relaxed text-muted">{blurb}</p>
      </div>
    </div>
  );
}
