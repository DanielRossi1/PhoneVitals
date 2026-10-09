<script>
  import ThemeSwitch from '../components/ThemeSwitch.svelte';

  let { children } = $props();
</script>

<div class="state scroll">
  <header>
    <div class="brand">
      <img class="logo" src="./icon.png" alt="" width="30" height="30" />
      PhoneVitals
    </div>
    <ThemeSwitch />
  </header>
  <main>{@render children()}</main>
</div>

<style>
  .state { height: 100%; display: flex; flex-direction: column; }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
  }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 15px; }
  .logo { width: 30px; height: 30px; flex: none; }
  main {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px 24px 64px;
  }
</style>
