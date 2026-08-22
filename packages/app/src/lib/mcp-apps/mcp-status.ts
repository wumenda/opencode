export type McpListPayload = { data?: Array<{ name: string; status?: { status?: string } }> } | Record<string, { status?: string }>

export function mcpServerStatus(payload: unknown, server: string): string | undefined {
  const record = payload as McpListPayload
  if (Array.isArray(record.data)) return record.data.find((e) => e.name === server)?.status?.status
  return (record as Record<string, { status?: string }>)[server]?.status
}