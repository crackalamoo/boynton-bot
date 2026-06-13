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

export type UserMessage = { type: 'user'; content: string };
export type AssistantMessage = { type: 'assistant'; parts: Part[] };
export type DividerMessage = { type: 'divider' };
export type Message = UserMessage | AssistantMessage | DividerMessage;

// SSE event shapes from /api/chat
export type TokenEvent = { type: 'token'; content: string };
export type ToolCallEvent = { type: 'tool_call'; name: string; arguments: Record<string, unknown> };
export type ToolResultEvent = { type: 'tool_result'; content: string };
export type ReasoningEvent = { type: 'reasoning'; content?: string; summary?: string };
export type DoneEvent = { type: 'done'; summarized?: boolean };
export type ErrorEvent = { type: 'error'; message: string };
export type SSEEvent = TokenEvent | ToolCallEvent | ToolResultEvent | ReasoningEvent | DoneEvent | ErrorEvent;
