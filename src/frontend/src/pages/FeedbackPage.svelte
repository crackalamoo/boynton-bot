<script lang="ts">
  import { onMount } from 'svelte';
  import { ThumbsUp, ThumbsDown } from '@lucide/svelte';
  import Message from '../components/Message.svelte';
  import { navigate } from '../lib/router.svelte.js';
  import { openAIResponseToParts } from '../lib/messageHistory.js';
  import type { FeedbackListItem, Message as MessageType } from '../lib/types.js';

  type FilterKey = 'all' | 'needs-review' | 'needs-retry' | 'in-progress' | 'resolved';

  const FILTERS: { key: FilterKey; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'needs-review', label: 'Needs review' },
    { key: 'needs-retry', label: 'Needs retry' },
    { key: 'in-progress', label: 'In progress' },
    { key: 'resolved', label: 'Resolved' },
  ];

  function matchesFilter(row: FeedbackListItem, filter: FilterKey): boolean {
    switch (filter) {
      case 'all':
        return true;
      case 'needs-review':
        return row.correction_status === 'drafted';
      case 'needs-retry':
        return row.correction_status === 'error' || row.correction_status === 'rejected';
      case 'in-progress':
        return row.correction_status === 'pending' || row.correction_status === 'drafting';
      case 'resolved':
        return row.correction_status === 'approved' || row.label === 'up';
    }
  }

  let feedbackList = $state<FeedbackListItem[]>([]);
  let loading = $state(true);
  let errorMsg = $state('');
  let activeFilter = $state<FilterKey>('all');

  let filteredList = $derived(feedbackList.filter((row) => matchesFilter(row, activeFilter)));

  async function load() {
    loading = true;
    errorMsg = '';
    try {
      const res = await fetch('/api/feedback');
      if (res.ok) {
        feedbackList = (await res.json()) as FeedbackListItem[];
      } else {
        errorMsg = 'error: could not load feedback';
      }
    } catch (_) {
      errorMsg = 'error: could not reach server';
    }
    loading = false;
  }

  onMount(load);

  function userMessageFor(row: FeedbackListItem): MessageType {
    return { type: 'user', content: row.question };
  }

  function assistantMessageFor(row: FeedbackListItem): MessageType {
    return {
      type: 'assistant',
      parts: openAIResponseToParts(row.response),
      dbId: row.message_id,
      // Every training_examples row is, by construction, from the primary model
      // (build_training_example rejects anything else) — so Feedback always shows.
      isPrimaryModel: true,
    };
  }
</script>

<div class="main">
  <article>
    <div class="header-row">
      <h1>Feedback</h1>
      <button class="link-btn" onclick={() => navigate('/chat')}>back to chat</button>
    </div>
    <hr />

    {#if !loading && !errorMsg && feedbackList.length > 0}
      <div class="filter-row">
        {#each FILTERS as f (f.key)}
          <button
            class="filter-pill"
            class:active={activeFilter === f.key}
            onclick={() => (activeFilter = f.key)}
          >
            {f.label}
            <span class="filter-count">{feedbackList.filter((row) => matchesFilter(row, f.key)).length}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if loading}
      <p class="muted">loading feedback…</p>
    {:else if errorMsg}
      <p class="message">{errorMsg}</p>
    {:else if feedbackList.length === 0}
      <p class="muted">No feedback recorded yet.</p>
    {:else if filteredList.length === 0}
      <p class="muted">No feedback matches this filter.</p>
    {:else}
      <div class="entries">
        {#each filteredList as row (row.id)}
          <div class="entry">
            <div class="entry-meta">
              <span class="entry-label" class:down={row.label === 'down'}>
                {#if row.label === 'up'}<ThumbsUp size={18} />{:else}<ThumbsDown size={18} />{/if}
              </span>
              {#if row.note}<span class="entry-note">note: {row.note}</span>{/if}
            </div>
            <div class="entry-messages">
              <Message msg={userMessageFor(row)} />
              <Message msg={assistantMessageFor(row)} feedbackData={row} />
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </article>
</div>

<style>
  .header-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .link-btn {
    font-size: 0.8rem;
    color: var(--muted-color);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
  }

  .link-btn:hover {
    color: var(--text-color);
  }

  .muted {
    color: var(--muted-color);
  }

  .filter-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-block-end: 1.25rem;
  }

  .filter-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    color: var(--muted-color);
    background: var(--button-bg);
    border: 1px solid var(--button-border);
    border-radius: 999px;
    padding: 0.3rem 0.75rem;
    cursor: pointer;
  }

  .filter-pill:hover {
    color: var(--text-color);
  }

  .filter-pill.active {
    color: var(--text-color);
    border-color: var(--text-color);
  }

  .filter-count {
    font-size: 0.75rem;
    color: var(--muted-color);
  }

  .filter-pill.active .filter-count {
    color: var(--text-color);
  }

  .message {
    font-size: 0.85rem;
    color: var(--muted-color);
  }

  .entries {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    padding-block-end: 1.5rem;
  }

  .entry {
    border: 1.5px solid var(--hr-color);
    border-radius: 10px;
    padding: 0.85rem 1rem 1rem;
  }

  .entry-meta {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    margin-block-end: 0.6rem;
    font-size: 0.85rem;
  }

  .entry-label {
    display: inline-flex;
    align-items: center;
    font-size: 1rem;
    color: #2e7d32;
  }

  .entry-label.down {
    color: #c0392b;
  }

  @media (prefers-color-scheme: dark) {
    .entry-label {
      color: #6fcf74;
    }

    .entry-label.down {
      color: #e57373;
    }
  }

  .entry-note {
    color: var(--muted-color);
    font-style: italic;
  }

  .entry-messages {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
</style>
