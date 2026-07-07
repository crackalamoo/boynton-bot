<script lang="ts">
  import { marked } from 'marked';
  import ToolCall from './ToolCall.svelte';
  import Feedback from './Feedback.svelte';
  import type { Feedback as FeedbackType, Message } from '../lib/types.js';

  marked.setOptions({ breaks: true });

  // `feedbackData` lets a caller that already has this message's feedback (e.g. the
  // feedback review page) pass it straight through, so <Feedback> never renders its
  // idle thumbs-up/down default for a message that's guaranteed to already have real
  // feedback recorded.
  let { msg, showHidden = false, feedbackData }: {
    msg: Message;
    showHidden?: boolean;
    feedbackData?: Omit<FeedbackType, 'prompt'>;
  } = $props();
</script>

<div class="msg {msg.type}">
  <div class="msg-label">{msg.type === 'user' ? 'you' : 'boynton bot'}</div>
  {#if msg.type === 'assistant'}
    {#if !msg.parts || msg.parts.length === 0}
      <div class="thinking">thinking…</div>
    {:else}
      {#each msg.parts as part}
        {#if part.kind === 'text'}
          <div class="msg-content markdown" class:hidden-part={showHidden && part.hidden}>{@html marked(part.content)}</div>
        {:else if part.kind === 'tool_call'}
          <ToolCall {part} {showHidden} />
        {:else if part.kind === 'reasoning'}
          <div class="thinking reasoning-trace" class:hidden-part={showHidden && part.hidden}>{part.content}</div>
        {/if}
      {/each}
      {@const lastPart = msg.parts[msg.parts.length - 1]}
      {#if lastPart.kind === 'tool_call' && lastPart.result !== null}
        <div class="thinking">thinking…</div>
      {:else if msg.dbId !== undefined && msg.isPrimaryModel}
        <Feedback messageId={msg.dbId} initialFeedback={feedbackData} />
      {/if}
    {/if}
  {:else if msg.type === 'user'}
    <div class="msg-content" class:queued={msg.queued}>{msg.content}</div>
  {/if}
</div>

<style>
  .msg {
    max-width: 85%;
  }
  .msg.user {
    align-self: flex-end;
    text-align: right;
  }
  .msg.assistant {
    align-self: flex-start;
  }
  .msg-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted-color);
    margin-block-end: 0.25rem;
  }
  .msg-content {
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .msg-content.markdown {
    white-space: normal;
  }
  .msg-content.markdown :global(p) { margin-block: 0.4rem; }
  .msg-content.markdown :global(p:first-child) { margin-block-start: 0; }
  .msg-content.markdown :global(p:last-child) { margin-block-end: 0; }
  .msg-content.markdown :global(ul),
  .msg-content.markdown :global(ol) { padding-inline-start: 1.4rem; margin-block: 0.4rem; }
  .msg-content.markdown :global(li) { margin-block: 0.15rem; }
  .msg-content.markdown :global(code) {
    font-family: monospace;
    font-size: 0.9em;
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 3px;
    padding: 0.1em 0.35em;
  }
  .msg-content.markdown :global(pre) {
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    overflow-x: auto;
    margin-block: 0.5rem;
  }
  .msg-content.markdown :global(pre code) {
    background: none;
    border: none;
    padding: 0;
    font-size: 0.85em;
  }
  .msg-content.markdown :global(h1),
  .msg-content.markdown :global(h2),
  .msg-content.markdown :global(h3) { margin-block: 0.6rem 0.3rem; }
  .msg-content.markdown :global(blockquote) {
    border-inline-start: 3px solid var(--hr-color);
    margin-inline-start: 0;
    padding-inline-start: 0.75rem;
    color: var(--muted-color);
  }

  .thinking {
    font-size: 0.9rem;
    color: var(--muted-color);
    font-style: italic;
  }

  .reasoning-trace {
    white-space: pre-wrap;
  }

  .hidden-part {
    color: var(--muted-color);
    opacity: 0.7;
  }

  .queued {
    opacity: 0.5;
  }
</style>
