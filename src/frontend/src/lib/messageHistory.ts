import type { Message, OpenAIMessage, Part } from './types.js';

interface RawMessage {
  id?: number;
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result';
  content?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  hidden?: boolean;
  created_at?: string;
  is_primary_model?: boolean;
}

interface HistoryResponse {
  messages: RawMessage[];
  summary_created_at?: string;
  summary?: string;
  has_more?: boolean;
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
      if (m.content?.trim()) asst.parts.push({ kind: 'text', content: m.content, hidden: m.hidden });
      // Every assistant row in this grouped turn overwrites dbId (and isPrimaryModel
      // alongside it), so by the time the group closes (next 'user' row) both hold the
      // values of the *last* row — which is exactly the final, no-tool_calls reply row
      // feedback should attach to / be gated by.
      if (m.id !== undefined) asst.dbId = m.id;
      asst.isPrimaryModel = m.is_primary_model ?? false;
    } else if (m.role === 'tool_call') {
      const asst = ensureAssistant();
      asst.parts.push({ kind: 'tool_call', name: m.tool_name ?? '', arguments: m.arguments ?? {}, result: null, hidden: m.hidden });
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
    mapped.splice(dividerInsertAfter + 1, 0, { type: 'divider', summary: history.summary, key: history.summary_created_at });
  }

  return mapped;
}

// Converts an OpenAI-message-shape turn (as stored in training_examples.response —
// tool_calls embedded on the assistant message, tool results as separate 'tool' role
// messages) into the frontend's Part[] shape, so it can be rendered by the same
// <Message> component the main chat page uses. This is a different raw shape than
// parseHistory's RawMessage (DB rows with separate tool_call/tool_result rows).
export function openAIResponseToParts(response: OpenAIMessage[]): Part[] {
  const parts: Part[] = [];
  const pendingIndexByCallId = new Map<string, number>();

  for (const m of response) {
    if (m.role === 'assistant') {
      if (typeof m.content === 'string' && m.content.trim()) {
        parts.push({ kind: 'text', content: m.content });
      }
      const toolCalls = (m.tool_calls as { id: string; function: { name: string; arguments: string } }[] | undefined) ?? [];
      for (const tc of toolCalls) {
        let args: Record<string, unknown> = {};
        try {
          args = JSON.parse(tc.function.arguments || '{}');
        } catch (_) {
          // malformed/truncated arguments — show empty rather than failing to render
        }
        pendingIndexByCallId.set(tc.id, parts.length);
        parts.push({ kind: 'tool_call', name: tc.function.name, arguments: args, result: null });
      }
    } else if (m.role === 'tool') {
      const callId = m.tool_call_id as string | undefined;
      const idx = callId !== undefined ? pendingIndexByCallId.get(callId) : undefined;
      if (idx !== undefined) {
        const existing = parts[idx];
        if (existing.kind === 'tool_call') {
          parts[idx] = { ...existing, result: (m.content as string) ?? '' };
        }
      }
    }
  }
  return parts;
}

// Reverse of openAIResponseToParts, for the correction-editing UI (Feedback.svelte) —
// lets a user edit/remove parts in the rendered view and serialize back to the JSON
// shape `resolve_feedback` expects. Not a byte-for-byte inverse: the original response
// may interleave multiple tool_calls into one assistant message before any results come
// back (a "parallel" tool-call turn); this always emits one assistant+tool message pair
// per tool_call. Semantically equivalent (same calls, same order, same results) but
// restructured — reasonable since parts have no record of which calls were originally
// batched together once a user has added/removed/reordered them.
export function partsToOpenAIResponse(parts: Part[]): OpenAIMessage[] {
  const messages: OpenAIMessage[] = [];
  let pendingText: string[] = [];
  let callCounter = 0;

  for (const part of parts) {
    if (part.kind === 'text') {
      if (part.content) pendingText.push(part.content);
    } else if (part.kind === 'tool_call') {
      const id = `call_${callCounter++}`;
      messages.push({
        role: 'assistant',
        content: pendingText.length ? pendingText.join('\n\n') : undefined,
        tool_calls: [
          { id, type: 'function', function: { name: part.name, arguments: JSON.stringify(part.arguments ?? {}) } },
        ],
      });
      pendingText = [];
      messages.push({ role: 'tool', tool_call_id: id, content: part.result ?? '' });
    }
    // reasoning parts never appear in this shape (see openAIResponseToParts) — nothing to emit.
  }

  if (pendingText.length || messages.length === 0) {
    messages.push({ role: 'assistant', content: pendingText.join('\n\n') });
  }

  return messages;
}
