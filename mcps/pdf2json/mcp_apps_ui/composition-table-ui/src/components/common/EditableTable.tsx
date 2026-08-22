import { type ReactNode } from 'react';

export interface EditableTableColumn<T> {
  key: keyof T & string;
  header: string;
  render: (row: T, rowIndex: number, readOnly: boolean, onChange: (newValue: string) => void) => ReactNode;
  className?: string;
}

/** 可编辑表格：行增删 + 单元格自定义渲染。 */
export function EditableTable<T extends Record<string, unknown>>({
  rows,
  columns,
  readOnly,
  onRowChange,
  onRowAdd,
  onRowDelete,
}: {
  rows: T[];
  columns: EditableTableColumn<T>[];
  readOnly: boolean;
  onRowChange: (index: number, newRow: T) => void;
  onRowAdd: () => void;
  onRowDelete: (index: number) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead className="bg-bg-2/60">
          <tr>
            {columns.map((col) => (
              <th key={col.key} className={`border-b border-border px-2 py-1.5 text-left text-[10px] font-bold text-text-3 ${col.className ?? ''}`}>
                {col.header}
              </th>
            ))}
            {!readOnly && <th className="border-b border-border px-2 py-1.5 text-left text-[10px] text-text-3">操作</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="hover:bg-bg-3/30">
              {columns.map((col) => (
                <td key={col.key} className={`border-b border-border/60 px-2 py-1 ${col.className ?? ''}`}>
                  {col.render(row, ri, readOnly, (nv) => onRowChange(ri, { ...row, [col.key]: nv }))}
                </td>
              ))}
              {!readOnly && (
                <td className="border-b border-border/60 px-2 py-1">
                  <button
                    type="button"
                    className="text-[11px] text-red hover:underline"
                    onClick={() => onRowDelete(ri)}
                  >
                    删除
                  </button>
                </td>
              )}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + (readOnly ? 0 : 1)} className="px-2 py-4 text-center text-text-3">
                无数据
              </td>
            </tr>
          )}
        </tbody>
        {!readOnly && (
          <tfoot>
            <tr>
              <td colSpan={columns.length + 1} className="px-2 py-1.5">
                <button
                  type="button"
                  className="text-[11px] text-accent hover:underline"
                  onClick={onRowAdd}
                >
                  + 添加行
                </button>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}