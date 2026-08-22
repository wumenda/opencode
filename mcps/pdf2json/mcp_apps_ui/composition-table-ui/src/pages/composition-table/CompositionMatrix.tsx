/**
 * 组成矩阵：行=组分，列=物流，单元格=分数（摩尔/质量可切换）。
 *
 * 适配实际数据结构：stream.composition[] 统一含 mole_fraction/mass_fraction。
 * 单元格按数值热力着色（0=白，1=深色）；缺失值显示"-";可编辑。
 */
import { useState } from 'react';

interface Component {
  name: string;
  molecular_weight?: number | null;
}

interface CompositionEntry {
  component: string;
  mole_fraction?: number | null;
  mass_fraction?: number | null;
}

interface Stream {
  stream_id: string;
  composition?: CompositionEntry[];
}

export function CompositionMatrix({
  components,
  streams,
  readOnly,
  onChange,
}: {
  components: Component[];
  streams: Stream[];
  readOnly: boolean;
  onChange: (streamIdx: number, compName: string, field: 'mole_fraction' | 'mass_fraction', value: number | null) => void;
}) {
  const [mode, setMode] = useState<'mole' | 'mass'>('mole');
  const fieldKey = mode === 'mole' ? 'mole_fraction' : 'mass_fraction';

  const getFraction = (stream: Stream, compName: string): number | null => {
    const entry = (stream.composition ?? []).find((c) => c.component === compName);
    return entry?.[fieldKey] ?? null;
  };

  const heatColor = (v: number | null): string => {
    if (v === null || v === undefined) return 'transparent';
    const alpha = Math.min(Math.max(v, 0), 1);
    return `rgba(49, 104, 255, ${alpha * 0.6})`;
  };

  return (
    <div className="rounded-md border border-border bg-bg-2/60 p-3">
      {/* 模式切换 */}
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[11px] text-text-3">分数类型：</span>
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] transition ${mode === 'mole' ? 'bg-accent text-white' : 'bg-bg-3 text-text-2 hover:bg-bg-3/70 hover:text-text'}`}
          onClick={() => setMode('mole')}
        >
          摩尔分数
        </button>
        <button
          type="button"
          className={`rounded px-2 py-0.5 text-[11px] transition ${mode === 'mass' ? 'bg-accent text-white' : 'bg-bg-3 text-text-2 hover:bg-bg-3/70 hover:text-text'}`}
          onClick={() => setMode('mass')}
        >
          质量分数
        </button>
      </div>

      {/* 矩阵表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-bg-2/60">
            <tr>
              <th className="sticky left-0 border-b border-border px-2 py-1.5 text-left text-[10px] font-bold text-text-3">组分</th>
              {streams.map((s, i) => (
                <th key={i} className="border-b border-border px-2 py-1.5 text-center text-[10px] font-bold text-text-3">
                  {s.stream_id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {components.map((comp, ri) => (
              <tr key={ri} className="hover:bg-bg-3/30">
                <td className="sticky left-0 border-b border-border/60 bg-bg-2/80 px-2 py-1 text-text">
                  {comp.name || '-'}
                </td>
                {streams.map((s, ci) => {
                  const v = getFraction(s, comp.name);
                  return (
                    <td key={ci} className="border-b border-border/60 px-1 py-0.5 text-center" style={{ background: heatColor(v) }}>
                      <input
                        type="number"
                        step="0.001"
                        min="0"
                        max="1"
                        className="w-16 bg-transparent text-center font-mono text-xs text-text outline-none disabled:opacity-70"
                        value={v ?? ''}
                        onChange={(e) => onChange(ci, comp.name, fieldKey, e.target.value === '' ? null : Number(e.target.value))}
                        disabled={readOnly}
                        placeholder="-"
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
            {/* 每列求和行（摩尔/质量分数应≈1） */}
            <tr className="border-t-2 border-border bg-bg-2/40">
              <td className="sticky left-0 bg-bg-2/80 px-2 py-1 text-[10px] font-bold text-text-3">求和</td>
              {streams.map((s, ci) => {
                const sum = components.reduce((acc, comp) => {
                  const entry = (s.composition ?? []).find((c) => c.component === comp.name);
                  return acc + (entry?.[fieldKey] ?? 0);
                }, 0);
                const abnormal = sum > 0 && Math.abs(sum - 1) > 0.05;
                return (
                  <td key={ci} className={`px-1 py-0.5 text-center font-mono text-[10px] ${abnormal ? 'text-red font-bold' : 'text-text-2'}`}>
                    {sum.toFixed(3)}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}