<script lang="ts">
  import { routerState } from './lib/router.svelte.js';
  import ChatPage from './pages/ChatPage.svelte';
  import SettingsPage from './pages/SettingsPage.svelte';

  // Routes: '/' and '/chat' both render the chat UI, matching the
  // backend's catch-all which serves index.html for any path. '/settings'
  // renders the settings page. Any other path falls back to the chat page.
  const Route = $derived.by(() => {
    switch (routerState.path) {
      case '/':
      case '/chat':
        return ChatPage;
      case '/settings':
        return SettingsPage;
      default:
        return ChatPage;
    }
  });
</script>

<Route />
