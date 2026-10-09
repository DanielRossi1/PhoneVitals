<script>
  /** Stroke icons drawn on a 24×24 grid (shapes after the Lucide set). */
  let { name, size = 18, stroke = 1.9, class: cls = '' } = $props();

  const PATHS = {
    overview: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
    shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4',
    health: 'M22 12h-4l-3 9L9 3l-3 9H2',
    tests: 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11',
    live: 'M2 12h3l3-8 4 16 4-12 2 4h4',
    chip: 'M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM9 9h6v6H9z',
    data: 'M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1M16 3h1a2 2 0 0 1 2 2v5a2 2 0 0 0 2 2 2 2 0 0 0-2 2v5a2 2 0 0 1-2 2h-1',
    sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
    moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
    monitor: 'M4 4h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM8 20h8M12 16v4',
    download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
    refresh: 'M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5',
    usb: 'M12 2v14M12 2l-3 3M12 2l3 3M8 10H6v3l6 3 6-3V9h-2M12 22a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
    alert: 'M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01',
    error: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM15 9l-6 6M9 9l6 6',
    ok: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM8 12l3 3 5-6',
    info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
    right: 'M9 18l6-6-6-6',
    down: 'M6 9l6 6 6-6',
    play: 'M6 4l14 8-14 8z',
    stop: 'M6 6h12v12H6z',
    phone: 'M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM11 18h2',
    search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3',
    copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
    battery: 'M4 7h13a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zM22 11v2M6 10v4M9 10v4',
    storage: 'M22 12H2M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6zM6 16h.01M10 16h.01',
    lock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4',
    fingerprint: 'M12 11v3a8 8 0 0 1-1 4M8 12a4 4 0 0 1 8 0v2M5 10a7 7 0 0 1 14 0v4a12 12 0 0 1-.6 3.7M8.5 21a12 12 0 0 0 1-3.5M3 15v-2a9 9 0 0 1 1-4',
    patch: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2',
    close: 'M18 6L6 18M6 6l12 12',
    sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z',
    vibrate: 'M8 4h8v16H8zM4 8v8M20 8v8M1 10v4M23 10v4',
    flash: 'M13 2L4 14h7l-1 8 9-12h-7z',
    touch: 'M9 11V5a2 2 0 0 1 4 0v6M13 10a2 2 0 0 1 4 0v2a2 2 0 0 1 4 0v3a7 7 0 0 1-7 7h-1a7 7 0 0 1-6-3.4L4 15a2 2 0 0 1 3.4-2L9 15',
    eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    speaker: 'M11 5L6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14',
    compass: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM16 8l-2 6-6 2 2-6z',
    wifi: 'M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M2 9a15 15 0 0 1 20 0M12 20h.01',
    buttons: 'M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM19 7h2M19 11h2M3 9h2',
    clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 7v5l3 2',
  };
</script>

<svg class="icon {cls}" width={size} height={size} viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width={stroke} stroke-linecap="round"
     stroke-linejoin="round" aria-hidden="true">
  <path d={PATHS[name] ?? PATHS.info} />
</svg>
