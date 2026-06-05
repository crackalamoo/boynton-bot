import type { Message, Part } from './types.js';

interface RawMessage {
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result';
  content?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  created_at?: string;
}

interface HistoryResponse {
  messages: RawMessage[];
  summary_created_at?: string;
}

export function parseHistory(history: HistoryResponse): Message[] {
  const mapped: Message[] = [];
  let dividerInsertAfter = -1;
  const cutoff = history.summary_created_at ? new Date(history.summary_created_at) : null;

  function ensureAssistant(): Extract<Message, { type: 'assistant' }> {
    const last = mapped[mapped.length - 1];
    if (last?.type === 'assistant') return last;
    const msg: Extract<Message, { type: 'assistant' }> = { type: 'assistant', parts: [] };
    mapped.push(msg);
    return msg;
  }

  for (const m of history.messages) {
    if (m.role === 'user') {
      mapped.push({ type: 'user', content: m.content ?? '' });
    } else if (m.role === 'assistant') {
      const asst = ensureAssistant();
      if (m.content) asst.parts.push({ kind: 'text', content: m.content });
    } else if (m.role === 'tool_call') {
      const asst = ensureAssistant();
      asst.parts.push({ kind: 'tool_call', name: m.tool_name ?? '', arguments: m.arguments ?? {}, result: null });
    } else if (m.role === 'tool_result') {
      const asst = ensureAssistant();
      const pending = asst.parts.findLastIndex((p: Part) => p.kind === 'tool_call' && p.result === null);
      if (pending !== -1) {
        const existing = asst.parts[pending];
        if (existing.kind === 'tool_call') {
          asst.parts[pending] = { ...existing, result: m.content ?? '' };
        }
      }
    }
    if (cutoff && m.created_at && new Date(m.created_at) <= cutoff) {
      dividerInsertAfter = mapped.length - 1;
    }
  }

  if (dividerInsertAfter >= 0) {
    mapped.splice(dividerInsertAfter + 1, 0, { type: 'divider' });
  }

  return mapped;
}
