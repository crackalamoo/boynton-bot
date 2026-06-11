<script lang="ts">
  import { routerState } from './lib/router.svelte.js';
  import ChatPage from './pages/ChatPage.svelte';

  // Routes: '/' and '/chat' both render the chat UI, matching the
  // backend's catch-all which serves index.html for any path. Any
  // other path falls back to the chat page too, until more pages exist.
  const Route = $derived.by(() => {
    switch (routerState.path) {
      case '/':
      case '/chat':
        return ChatPage;
      default:
        return ChatPage;
    }
  });
</script>

<Route />
