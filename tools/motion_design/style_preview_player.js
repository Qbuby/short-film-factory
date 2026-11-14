/* Shared, dependency-free sample playback. DOM state is also accessible to QA. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.StylePreviewPlayer = factory();
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  return class StylePreviewPlayer {
    constructor({document: doc = document, window: win = window} = {}) {
      this.document = doc; this.window = win; this.entries = new Map(); this.active = null;
      this.onVisibility = () => { if (doc.hidden) this.stopAll(); };
      this.onPageHide = () => this.stopAll();
      doc.addEventListener('visibilitychange', this.onVisibility);
      win.addEventListener('pagehide', this.onPageHide);
      this.observer = win.IntersectionObserver ? new win.IntersectionObserver(items => {
        for (const item of items) {
          const entry = this.entries.get(item.target); if (!entry) continue;
          entry.visible = item.isIntersecting;
          if (!entry.visible) this.stop(entry.element);
        }
      }, {threshold: 0}) : null;
    }
    register(element, {video, poster, fallback, isEnabled = () => true}) {
      this.unregister(element);
      const entry = {element, video, poster, fallback, isEnabled, visible:true, failed:false, revision:0, listeners:[]};
      this.entries.set(element, entry);
      video.muted = true; video.loop = true; video.playsInline = true;
      const listen = (target, name, callback) => {
        if (!target) return;
        target.addEventListener(name, callback); entry.listeners.push(() => target.removeEventListener(name, callback));
      };
      listen(element, 'pointerenter', event => { if (event.pointerType !== 'touch') this.start(element); });
      listen(element, 'pointerleave', () => this.stop(element));
      listen(element, 'focus', () => { if (!this.window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) this.start(element); });
      listen(element, 'blur', () => this.stop(element));
      listen(element, 'keydown', event => {
        if (event.key === 'Escape') this.stop(element);
        // Explicit activation is available even when reduced motion disables focus autoplay.
        if (event.key === 'Enter' || event.key === ' ') this.start(element);
      });
      listen(video, 'playing', () => {
        if (!this.wanted(entry) || video.paused) { this.reset(entry); return; }
        this.paint(entry, 'playing');
      });
      listen(video, 'timeupdate', () => {
        if (!this.wanted(entry)) { this.reset(entry); return; }
        element.dataset.previewTime = Number(video.currentTime || 0).toFixed(3);
      });
      listen(video, 'loadedmetadata', () => { if (!this.wanted(entry)) this.reset(entry); });
      const failed = () => { entry.failed = true; this.stop(element); this.paint(entry, 'unavailable'); };
      listen(video, 'error', failed);
      // A child <source> error does not bubble to the video element.
      for (const source of video.querySelectorAll?.('source') || []) listen(source, 'error', failed);
      listen(poster, 'error', () => { poster.hidden = true; if (fallback) fallback.hidden = false; });
      listen(poster, 'load', () => { poster.hidden = false; if (fallback) fallback.hidden = true; });
      if (poster?.complete && poster.naturalWidth === 0) { poster.hidden = true; if (fallback) fallback.hidden = false; }
      this.paint(entry, 'idle'); this.observer?.observe(element);
      return () => this.unregister(element);
    }
    wanted(entry) {
      return this.entries.get(entry.element) === entry && this.active === entry && !entry.failed &&
        !this.document.hidden && entry.visible && entry.isEnabled() && entry.element.getClientRects().length > 0;
    }
    paint(entry, state) {
      entry.element.dataset.previewState = state;
      if (state !== 'playing') entry.element.dataset.previewTime = '0.000';
      entry.element.classList.toggle('playing', state === 'playing');
    }
    reset(entry) {
      entry.video.pause();
      try { entry.video.currentTime = 0; } catch { /* Metadata may not be available yet. */ }
      this.paint(entry, entry.failed ? 'unavailable' : 'idle');
    }
    start(element) {
      const entry = this.entries.get(element); if (!entry || entry.failed) return;
      if (this.active === entry && this.wanted(entry)) return;
      this.stopAll(); this.active = entry;
      if (!this.wanted(entry)) { this.stop(element); return; }
      const revision = ++entry.revision;
      this.paint(entry, 'loading');
      const settled = () => {
        if (entry.revision !== revision || !this.wanted(entry)) {
          // Do not let an old promise interrupt a newer request for the same video.
          if (this.active !== entry) this.reset(entry);
        }
      };
      try {
        const playing = entry.video.play();
        if (playing?.then) playing.then(settled, error => {
          if (entry.revision !== revision) { settled(); return; }
          if (error?.name === 'NotSupportedError') entry.failed = true;
          this.stop(element);
        });
      } catch (error) {
        if (error?.name === 'NotSupportedError') entry.failed = true;
        this.stop(element);
      }
    }
    stop(element) {
      const entry = this.entries.get(element); if (!entry) return;
      entry.revision++;
      if (this.active === entry) this.active = null;
      this.reset(entry);
    }
    stopAll() { for (const element of this.entries.keys()) this.stop(element); }
    unregister(element) {
      const entry = this.entries.get(element); if (!entry) return;
      this.stop(element); entry.listeners.forEach(remove => remove());
      this.observer?.unobserve(element); this.entries.delete(element);
    }
    destroy() {
      for (const element of this.entries.keys()) this.unregister(element);
      this.observer?.disconnect();
      this.document.removeEventListener('visibilitychange', this.onVisibility);
      this.window.removeEventListener('pagehide', this.onPageHide);
    }
  };
});
