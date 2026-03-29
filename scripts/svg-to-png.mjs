#!/usr/bin/env node
/**
 * SVG-to-PNG batch converter for OG images and favicons.
 *
 * Usage:
 *   node scripts/svg-to-png.mjs <directory> [--favicon]
 *
 * Without --favicon: converts og.svg → og-image.png at 1200x630
 * With --favicon:    converts favicon.svg → icon-192.png (192x192) and icon-512.png (512x512)
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join, basename } from 'path';
import { Resvg } from '@resvg/resvg-js';

const dir = process.argv[2];
const isFavicon = process.argv.includes('--favicon');

if (!dir) {
  console.error('Usage: node scripts/svg-to-png.mjs <directory> [--favicon]');
  process.exit(1);
}

function renderSvgToPng(svgPath, outputPath, width, height) {
  const svg = readFileSync(svgPath, 'utf-8');
  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: width },
    font: { loadSystemFonts: true },
  });
  const rendered = resvg.render();
  const png = rendered.asPng();
  writeFileSync(outputPath, png);
  console.log(`  ✓ ${basename(outputPath)} (${width}x${height})`);
}

if (isFavicon) {
  const svgPath = join(dir, 'favicon.svg');
  if (!existsSync(svgPath)) {
    console.error(`No favicon.svg found in ${dir}`);
    process.exit(1);
  }
  console.log(`Converting favicon: ${svgPath}`);
  renderSvgToPng(svgPath, join(dir, 'icon-192.png'), 192, 192);
  renderSvgToPng(svgPath, join(dir, 'icon-512.png'), 512, 512);
} else {
  // Look for og.svg or any *-og.svg files
  const ogSvg = join(dir, 'og.svg');
  if (existsSync(ogSvg)) {
    console.log(`Converting OG image: ${ogSvg}`);
    renderSvgToPng(ogSvg, join(dir, 'og-image.png'), 1200, 630);
  }

  // Also convert any game OG svgs (og-hydration-hustle.svg, og-cthulhu-fact-frenzy.svg, etc.)
  const gamePatterns = [
    'og-hydration-hustle.svg',
    'og-cthulhu-fact-frenzy.svg',
  ];
  for (const name of gamePatterns) {
    const path = join(dir, name);
    if (existsSync(path)) {
      const pngName = name.replace('.svg', '.png');
      console.log(`Converting game OG: ${path}`);
      renderSvgToPng(path, join(dir, pngName), 1200, 630);
    }
  }

  // Convert any og-*.svg in images/ subdirectory (for codyjo.com per-product images)
  const imagesDir = join(dir, 'images');
  if (existsSync(imagesDir)) {
    const { readdirSync } = await import('fs');
    const svgs = readdirSync(imagesDir).filter(f => f.startsWith('og-') && f.endsWith('.svg'));
    for (const svgFile of svgs) {
      const svgPath = join(imagesDir, svgFile);
      const pngName = svgFile.replace('.svg', '.png');
      console.log(`Converting product OG: ${svgPath}`);
      renderSvgToPng(svgPath, join(imagesDir, pngName), 1200, 630);
    }
  }
}

console.log('Done.');
