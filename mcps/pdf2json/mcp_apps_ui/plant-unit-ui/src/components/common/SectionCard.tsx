import type { ReactNode } from 'react';

/** 带色条标题的卡片容器。accent 取 accent/green/orange/purple/cyan/yellow/red。 */
export function SectionCard({
  title,
  accent = 'accent',
  count,
  action,
  children,
  className = '',
}: {
  title: string;
  accent?: 'accent' | 'green' | 'orange' | 'purple' | 'cyan' | 'yellow' | 'red';
  count?: number;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const barColor: Record<string, string> = {
    accent: 'bg-accent',
    green: 'bg-green',
    orange: 'bg-orange',
    purple: 'bg-purple',
    cyan: 'bg-cyan',
    yellow: 'bg-yellow',
    red: 'bg-red',
  };
  const titleColor: Record<string, string> = {
    accent: 'text-text',
    green: 'text-text',
    orange: 'text-orange',
    purple: 'text-text',
    cyan: 'text-text',
    yellow: 'text-text',
    red: 'text-red',
  };
  return (
    <section className={`rounded-md border border-border bg-bg-2/60 p-4 ${className}`}>
      <h3 className={`mb-3 flex items-center gap-2 text-sm font-bold ${titleColor[accent]}`}>
        <span className={`h-3 w-1 rounded-sm ${barColor[accent]}`} />
        {title}
        {count !== undefined && <span className="text-xs font-normal text-text-3">（{count}）</span>}
        {action && <span className="ml-auto">{action}</span>}
      </h3>
      {children}
    </section>
  );
}
