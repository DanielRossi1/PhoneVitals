import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';
import { initTheme } from './lib/theme.svelte.js';

initTheme();
mount(App, { target: document.getElementById('app') });
