export type TextPart = { kind: 'text'; content: string; hidden?: boolean };
export type ToolCallPart = {
  kind: 'tool_call';
  name: string;
  arguments: Record<string, unknown>;
  result: string | null;
  hidden?: boolean;
};
export type ReasoningPart = { kind: 'reasoning'; content: string; hidden?: boolean };
export type Part = TextPart | ToolCallPart | ReasoningPart;

export type UserMessage = { type: 'user'; content: string; id?: number; queued?: boolean };
// `id` is a transient, client-only id used to track a bubble during streaming.
// `dbId` is the real `messages.id` of the final (no-tool_calls) assistant row of this
// turn, once known — used to attach feedback to the right row.
export type AssistantMessage = { type: 'assistant'; parts: Part[]; id?: number; dbId?: number };
export type DividerMessage = { type: 'divider'; summary?: string };
export type Message = UserMessage | AssistantMessage | DividerMessage;

// SSE event shapes from /api/chat
export type TokenEvent = { type: 'token'; content: string };
export type ToolCallEvent = { type: 'tool_call'; name: string; arguments: Record<string, unknown> };
export type ToolResultEvent = { type: 'tool_result'; content: string };
export type ReasoningEvent = { type: 'reasoning'; content?: string; summary?: string };
export type DoneEvent = { type: 'done'; summarized?: boolean; message_id?: number };
export type ErrorEvent = { type: 'error'; message: string };
export type QueuedEvent = { type: 'queued' };
export type SSEEvent = TokenEvent | ToolCallEvent | ToolResultEvent | ReasoningEvent | DoneEvent | ErrorEvent | QueuedEvent;

// /api/feedback* shapes (training_examples rows)
export type OpenAIMessage = { role: string; content?: string; [key: string]: unknown };
export type FeedbackLabel = 'up' | 'down';
export type CorrectionStatus = 'pending' | 'drafting' | 'drafted' | 'approved' | 'rejected' | 'error';
export type Feedback = {
  id: number;
  message_id: number;
  label: FeedbackLabel;
  prompt: OpenAIMessage[];
  response: OpenAIMessage[];
  note: string | null;
  correction: OpenAIMessage[] | null;
  correction_status: CorrectionStatus | null;
};
