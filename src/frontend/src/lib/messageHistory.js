export function parseHistory(history) {
  const mapped = [];
  let dividerInsertAfter = -1;
  const cutoff = history.summary_created_at ? new Date(history.summary_created_at) : null;

  function ensureAssistant() {
    const last = mapped[mapped.length - 1];
    if (last?.type === 'assistant') return last;
    const msg = { type: 'assistant', parts: [] };
    mapped.push(msg);
    return msg;
  }

  for (const m of history.messages) {
    if (m.role === 'user') {
      mapped.push({ type: 'user', content: m.content });
    } else if (m.role === 'assistant') {
      const asst = ensureAssistant();
      if (m.content) asst.parts.push({ kind: 'text', content: m.content });
    } else if (m.role === 'tool_call') {
      const asst = ensureAssistant();
      asst.parts.push({ kind: 'tool_call', name: m.tool_name, arguments: m.arguments ?? {}, result: null });
    } else if (m.role === 'tool_result') {
      const asst = ensureAssistant();
      const pending = asst.parts.findLastIndex((p) => p.kind === 'tool_call' && p.result === null);
      if (pending !== -1) asst.parts[pending] = { ...asst.parts[pending], result: m.content };
    }
    if (cutoff && new Date(m.created_at) <= cutoff) {
      dividerInsertAfter = mapped.length - 1;
    }
  }

  if (dividerInsertAfter >= 0) {
    mapped.splice(dividerInsertAfter + 1, 0, { type: 'divider' });
  }

  return mapped;
}
