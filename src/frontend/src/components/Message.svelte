<script lang="ts">
  import MessageParts from './MessageParts.svelte';
  import Feedback from './Feedback.svelte';
  import type { Feedback as FeedbackType, Message } from '../lib/types.js';

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
      <MessageParts parts={msg.parts} {showHidden} />
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

  .thinking {
    font-size: 0.9rem;
    color: var(--muted-color);
    font-style: italic;
  }

  .queued {
    opacity: 0.5;
  }
</style>
