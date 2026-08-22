/** 警告列表统一样式。 */
export function WarningsList({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <section className="rounded-md border border-orange/30 bg-orange/5 p-4">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-orange">
        <span className="h-3 w-1 rounded-sm bg-orange" />
        警告（{warnings.length}）
      </h3>
      <ul className="flex flex-col gap-1.5">
        {warnings.map((w, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-text-2">
            <span className="mt-0.5 text-orange">•</span>
            <span>{w}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}