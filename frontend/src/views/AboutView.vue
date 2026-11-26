<!--
  About and credits. TMDB's terms ask for its notice and one of its approved logos, unmodified, in an About or
  Credits section, less prominent than the app's own name (public/tmdb.svg is their "blue short" logo as published).
-->
<template>
  <div class="stack">
    <div class="row">
      <RouterLink to="/" class="btn btn-quiet btn-sm back" aria-label="Back to my things">‹ Back</RouterLink>
    </div>
    <h1>About Provenance</h1>
    <p>Provenance catalogs the things you own, down to the edition. Your items, photos and notes are private.
      Works and releases are a shared catalog that everyone's scans and confirmations build up.</p>

    <section class="card card-pad stack">
      <h2>Credits</h2>
      <div class="credit">
        <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer"><img src="/tmdb.svg" alt="TMDB" class="tmdb" /></a>
        <p class="small">Film and TV data come from TMDB. This product uses TMDB and the TMDB APIs but is not endorsed,
          certified, or otherwise approved by TMDB.</p>
      </div>
      <p class="small">Book data come from <a href="https://openlibrary.org" target="_blank" rel="noopener noreferrer">Open Library</a>, the Internet Archive's open catalog.</p>
      <p class="small">Barcode lookups use <a href="https://www.upcitemdb.com" target="_blank" rel="noopener noreferrer">UPCitemdb</a>.</p>
    </section>
  </div>
</template>

<style scoped>
.back { margin-left: -12px; }
.credit { display: grid; gap: 8px; }
.tmdb { height: 12px; width: auto; display: block; }
</style>
