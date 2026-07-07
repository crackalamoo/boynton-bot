<script lang="ts">
  import { onMount } from 'svelte';
  import type { Feedback, OpenAIMessage } from '../lib/types.js';

  let { messageId }: { messageId: number } = $props();

  // 'idle' — nothing recorded yet, thumbs shown.
  // 'up' — thumbs-up recorded, nothing else to do.
  // 'noting' — thumbs-down just recorded, note box shown.
  // 'drafting' — note submitted (or skipped straight into review-less pending), waiting on the draft.
  // 'reviewing' — a draft correction is ready for approve/edit/reject.
  // 'resolved' — approved or rejected; correction_status reflects which.
  // 'error' — drafting failed.
  type UiState = 'idle' | 'up' | 'noting' | 'down-pending' | 'drafting' | 'reviewing' | 'resolved' | 'error';

  let uiState = $state<UiState>('idle');
  let feedback = $state<Feedback | null>(null);
  let noteText = $state('');
  let correctionText = $state('');
  let submitting = $state(false);
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  function stateFromFeedback(f: Feedback): UiState {
    if (f.label === 'up') return 'up';
    switch (f.correction_status) {
      case 'pending':
        return 'down-pending';
      case 'drafting':
        return 'drafting';
      case 'drafted':
        return 'reviewing';
      case 'approved':
      case 'rejected':
        return 'resolved';
      case 'error':
        return 'error';
      default:
        return 'down-pending';
    }
  }

  function stopPolling() {
    if (pollHandle !== null) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  }

  function startPolling(exampleId: number) {
    stopPolling();
    pollHandle = setInterval(async () => {
      const res = await fetch(`/api/feedback/${exampleId}`);
      if (!res.ok) return;
      const f = (await res.json()) as Feedback;
      feedback = f;
      uiState = stateFromFeedback(f);
      if (f.correction_status === 'drafted') {
        correctionText = JSON.stringify(f.correction, null, 2);
      }
      if (uiState !== 'drafting') stopPolling();
    }, 3000);
  }

  onMount(() => {
    (async () => {
      const res = await fetch(`/api/feedback/message/${messageId}`);
      if (!res.ok) return;
      const f = (await res.json().catch(() => null)) as Feedback | null;
      if (!f) return;
      feedback = f;
      uiState = stateFromFeedback(f);
      if (f.correction) correctionText = JSON.stringify(f.correction, null, 2);
      if (uiState === 'drafting') startPolling(f.id);
    })();
    return stopPolling;
  });

  async function submitLabel(label: 'up' | 'down') {
    if (submitting) return;
    submitting = true;
    try {
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: messageId, label }),
      });
      if (!res.ok) return;
      feedback = (await res.json()) as Feedback;
      uiState = label === 'up' ? 'up' : 'noting';
    } finally {
      submitting = false;
    }
  }

  async function submitNote() {
    if (!feedback || submitting) return;
    submitting = true;
    try {
      const res = await fetch(`/api/feedback/${feedback.id}/note`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: noteText }),
      });
      if (!res.ok) return;
      feedback = (await res.json()) as Feedback;
      uiState = 'drafting';
      startPolling(feedback.id);
    } finally {
      submitting = false;
    }
  }

  function skipNote() {
    uiState = 'down-pending';
  }

  async function resolve(action: 'approve' | 'reject') {
    if (!feedback || submitting) return;
    submitting = true;
    try {
      let correction: OpenAIMessage[] | undefined;
      if (action === 'approve') {
        try {
          correction = JSON.parse(correctionText);
        } catch (_) {
          alert('Correction is not valid JSON — fix it before approving.');
          submitting = false;
          return;
        }
      }
      const res = await fetch(`/api/feedback/${feedback.id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, correction }),
      });
      if (!res.ok) return;
      feedback = (await res.json()) as Feedback;
      uiState = 'resolved';
    } finally {
      submitting = false;
    }
  }
</script>

<div class="feedback" class:idle-fade={uiState === 'idle'}>
  {#if uiState === 'idle'}
    <button class="fb-btn" onclick={() => submitLabel('up')} disabled={submitting} aria-label="Good response">👍</button>
    <button class="fb-btn" onclick={() => submitLabel('down')} disabled={submitting} aria-label="Bad response">👎</button>
  {:else if uiState === 'up'}
    <span class="fb-status">👍 thanks</span>
  {:else if uiState === 'noting'}
    <div class="fb-note">
      <span class="fb-status">👎 what went wrong? (optional)</span>
      <textarea bind:value={noteText} placeholder="e.g. should have checked HN before answering" rows="2"></textarea>
      <div class="fb-note-actions">
        <button class="fb-link-btn" onclick={submitNote} disabled={submitting}>submit &amp; draft correction</button>
        <button class="fb-link-btn" onclick={skipNote} disabled={submitting}>skip</button>
      </div>
    </div>
  {:else if uiState === 'down-pending'}
    <span class="fb-status">👎 recorded</span>
  {:else if uiState === 'drafting'}
    <span class="fb-status">👎 drafting a correction…</span>
  {:else if uiState === 'reviewing'}
    <div class="fb-review">
      <span class="fb-status">correction drafted — review before it's used for training</span>
      <textarea class="fb-correction" bind:value={correctionText} rows="6"></textarea>
      <div class="fb-note-actions">
        <button class="fb-link-btn" onclick={() => resolve('approve')} disabled={submitting}>approve</button>
        <button class="fb-link-btn" onclick={() => resolve('reject')} disabled={submitting}>reject</button>
      </div>
    </div>
  {:else if uiState === 'resolved'}
    <span class="fb-status">
      {feedback?.correction_status === 'approved' ? 'correction approved' : 'correction rejected'}
    </span>
  {:else if uiState === 'error'}
    <span class="fb-status">correction drafting failed</span>
  {/if}
</div>

<style>
  .feedback {
    margin-block-start: 0.4rem;
    font-size: 0.8rem;
  }

  /* The resting thumbs-up/down are only an affordance, not information — hide them
     until the message is actually hovered (or focused, for keyboard use) so a normal
     conversation isn't a wall of buttons. Once feedback is recorded or in progress,
     it's real state, so it stays visible unconditionally. */
  .feedback.idle-fade {
    opacity: 0;
    transition: opacity 0.15s;
  }

  :global(.msg:hover) .feedback.idle-fade,
  .feedback.idle-fade:focus-within {
    opacity: 1;
  }

  /* On a device with no hover capability (touch), there's no hover state to reveal
     these on — fading them out would just make them permanently invisible. */
  @media (hover: none) {
    .feedback.idle-fade {
      opacity: 1;
    }
  }

  .fb-btn {
    background: none;
    border: 1px solid var(--button-border);
    border-radius: 6px;
    cursor: pointer;
    padding: 0.15rem 0.5rem;
    margin-inline-end: 0.35rem;
    font-size: 0.85rem;
    line-height: 1.4;
  }

  .fb-btn:hover:not(:disabled) {
    background: var(--button-bg);
  }

  .fb-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .fb-status {
    color: var(--muted-color);
    font-style: italic;
  }

  .fb-note,
  .fb-review {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    max-width: 30rem;
  }

  .fb-note textarea,
  .fb-correction {
    font-family: inherit;
    font-size: 0.8rem;
    color: var(--text-color);
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 6px;
    padding: 0.4rem 0.5rem;
    resize: vertical;
  }

  .fb-correction {
    font-family: monospace;
  }

  .fb-note-actions {
    display: flex;
    gap: 0.75rem;
  }

  .fb-link-btn {
    background: none;
    border: none;
    color: var(--muted-color);
    cursor: pointer;
    padding: 0;
    font-size: 0.8rem;
    text-decoration: underline;
  }

  .fb-link-btn:hover:not(:disabled) {
    color: var(--text-color);
  }

  .fb-link-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
