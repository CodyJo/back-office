# OG Image & Social Meta Standards

## Open Graph Image Requirements

| Property | Requirement |
|----------|-------------|
| Dimensions | 1200x630px |
| Format | PNG (raster), SVG (source) |
| File size | Under 300KB for PNG |
| Aspect ratio | 1.91:1 |
| Min dimensions | 600x315px (Facebook minimum) |

## Required Meta Tags

### Open Graph (Facebook, LinkedIn, Discord)

```html
<meta property="og:type" content="website" />
<meta property="og:title" content="Product Name — Tagline" />
<meta property="og:description" content="..." />
<meta property="og:image" content="https://domain.com/og-image.png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:url" content="https://domain.com/" />
```

### Twitter Card

```html
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="Product Name — Tagline" />
<meta name="twitter:description" content="..." />
<meta name="twitter:image" content="https://domain.com/og-image.png" />
```

### Favicon

```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<link rel="shortcut icon" href="/favicon.svg" />
<link rel="apple-touch-icon" href="/icon-192.png" />
```

## Title Format

Titles should lead with the product name:
- Good: "Fuel — Diet & Exercise Tracker"
- Bad: "GLP-1 Health Tracking | Fuel"

## PWA Manifest Icons

```json
{
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

## Platform-Specific Notes

- **Facebook**: Caches OG images aggressively. Use Facebook Sharing Debugger to refresh.
- **Discord**: Respects og:image. Refreshes on link re-paste.
- **iMessage**: Uses og:image with summary_large_image twitter card.
- **Slack**: Uses og:image, refreshes periodically.
- **LinkedIn**: Uses og:image, can be refreshed via Post Inspector.

## SVG Source Conventions

- ViewBox: `0 0 1200 630`
- Font: `system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif`
- File: `public/og.svg` (source), `public/og-image.png` (raster output)
- Convert with: `node scripts/svg-to-png.mjs <public-dir>`
