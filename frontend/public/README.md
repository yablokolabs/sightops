# Static assets

`SightOps.png` — the official project logo — must be copied into this directory
so it is served at `/SightOps.png`:

```bash
cp ../SightOps.png frontend/public/SightOps.png
```

The logo is referenced by both the browser tab icon and the application header.
The source of truth stays the `SightOps.png` at the repository root, which is
never modified. If the copy is missing the header falls back to a text wordmark
rather than showing a broken image.
