import type { ReactNode } from 'react';

export { SectionCard } from './SectionCard';
export { WarningsList } from './WarningsList';
export { EditableTable, type EditableTableColumn } from './EditableTable';
export { SourceImageViewer, type BboxOverlay } from './SourceImageViewer';

/** 文本输入字段。 */
export function Field({ label, value, onChange, readOnly }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  readOnly?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="w-24 shrink-0 text-[11px] text-text-3">{label}</label>
      <input
        type="text"
        className="flex-1 rounded border border-border bg-bg px-2 py-1 font-mono text-xs text-text outline-none focus:border-accent disabled:opacity-70"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        readOnly={readOnly}
      />
    </div>
  );
}

/** 数值+单位字段。 */
export function QuantityField({ label, q, onChangeValue, onChangeUnit, readOnly, min, max }: {
  label: string;
  q?: { value?: number | null; unit?: string };
  onChangeValue: (v: number | null) => void;
  onChangeUnit: (v: string) => void;
  readOnly?: boolean;
  min?: number;
  max?: number;
}) {
  const value = q?.value ?? '';
  const outOfRange = typeof value === 'number'
    && ((min != null && value < min) || (max != null && value > max));
  return (
    <div className="flex items-center gap-2">
      <label className="w-24 shrink-0 text-[11px] text-text-3">{label}</label>
      <input
        type="number"
        className={`w-28 rounded border bg-bg px-2 py-1 font-mono text-xs text-text outline-none focus:border-accent disabled:opacity-70 ${outOfRange ? 'border-red' : 'border-border'}`}
        value={value}
        onChange={(e) => onChangeValue(e.target.value === '' ? null : Number(e.target.value))}
        readOnly={readOnly}
        min={min}
        max={max}
      />
      <input
        type="text"
        className="w-16 rounded border border-border bg-bg px-2 py-1 font-mono text-xs text-text-2 outline-none focus:border-accent disabled:opacity-70"
        value={q?.unit ?? ''}
        onChange={(e) => onChangeUnit(e.target.value)}
        readOnly={readOnly}
      />
      {outOfRange && <span className="text-[10px] text-red">超出范围</span>}
    </div>
  );
}

/** 下拉选择字段。 */
export function SelectField({ label, value, options, onChange, readOnly }: {
  label: string;
  value: string;
  options: Array<{ v: string; l: string }>;
  onChange: (v: string) => void;
  readOnly?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="w-24 shrink-0 text-[11px] text-text-3">{label}</label>
      <select
        className="flex-1 rounded border border-border bg-bg px-2 py-1 text-xs text-text outline-none focus:border-accent disabled:opacity-70"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={readOnly}
      >
        {options.map((o) => (
          <option key={o.v} value={o.v}>{o.l}</option>
        ))}
      </select>
    </div>
  );
}

/** 复选框字段。 */
export function CheckboxField({ label, checked, onChange, readOnly }: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  readOnly?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <label className="w-24 shrink-0 text-[11px] text-text-3">{label}</label>
      <input
        type="checkbox"
        className="h-4 w-4"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={readOnly}
      />
    </div>
  );
}

/** 元信息格（label + value + 可选高亮色）。 */
export function InfoCell({ label, value, highlight }: {
  label: string;
  value: string | number;
  highlight?: 'green' | 'orange' | 'red';
}) {
  const color =
    highlight === 'green' ? 'text-green' :
    highlight === 'orange' ? 'text-orange' :
    highlight === 'red' ? 'text-red' : 'text-text';
  return (
    <div className="rounded-md border border-border bg-bg/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-text-3">{label}</div>
      <div className={`mt-0.5 font-mono text-sm font-semibold ${color}`}>{value}</div>
    </div>
  );
}

/** 位号/类型徽章。color 取 accent/green/orange/purple/cyan/yellow/red。 */
export function TagBadge({ children, color = 'accent' }: {
  children: ReactNode;
  color?: 'accent' | 'green' | 'orange' | 'purple' | 'cyan' | 'yellow' | 'red';
}) {
  const classes: Record<string, string> = {
    accent: 'bg-accent/10 text-accent',
    green: 'bg-green/10 text-green',
    orange: 'bg-orange/10 text-orange',
    purple: 'bg-purple/10 text-purple',
    cyan: 'bg-cyan/10 text-cyan',
    yellow: 'bg-yellow/10 text-yellow',
    red: 'bg-red/10 text-red',
  };
  return (
    <span className={`rounded px-2 py-0.5 font-mono text-xs font-bold ${classes[color]}`}>
      {children}
    </span>
  );
}

/** 无数据占位。 */
export function EmptyState({ text = '暂无数据' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-8 text-xs text-text-3">
      {text}
    </div>
  );
}