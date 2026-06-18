# Frontend

Svelte 5 + Vite + TypeScript. Built with `npm run build` into `dist/`, served by nginx.

## Structure

- `src/App.svelte` — root component, handles routing between pages
- `src/pages/ChatPage.svelte` — main chat UI
- `src/pages/SettingsPage.svelte` — cron job management + settings
- `src/components/` — `MessageList`, `Message`, `ChatInput`, `ToolCall`

## SSE streaming

The chat page connects to the backend's `/api/chat` SSE endpoint. Event types from the stream:

- `token` — append `content` to the in-progress bubble
- `tool_call` / `tool_result` — render tool use inline
- `done` — finalize the message
- `error` — display error state

The lazy bot bubble appears on the first `token` event and is committed on `done`.

## Svelte 5 notes

Uses runes (`$state`, `$derived`, `$effect`) — not the old Options API.

## Building

```sh
cd src/frontend
npm run build     # outputs to dist/
npm run dev       # dev server with HMR (separate from the Flask backend)
npm run check     # type-check with svelte-check
```
